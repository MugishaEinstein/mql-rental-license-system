from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from server.store import router as store_router


APP_NAME = "MQL License API"
DB_PATH = Path(os.getenv("LICENSE_DB_PATH", "./data/licenses.sqlite3"))
DATABASE_URL = os.getenv("LICENSE_DATABASE_URL", "")
ADMIN_API_KEY = os.getenv("LICENSE_ADMIN_API_KEY", "")
DEFAULT_GRACE_SECONDS = int(os.getenv("LICENSE_DEFAULT_GRACE_SECONDS", "21600"))

app = FastAPI(title=APP_NAME, version="1.0.0")
app.include_router(store_router)


# ---------- Time and normalization helpers ----------


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_datetime(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def normalize_text(value: str) -> str:
    return " ".join(value.strip().split())


def normalize_platform(value: str) -> str:
    value = value.strip().lower()
    if value not in {"mt4", "mt5", "both"}:
        raise ValueError("platform must be mt4, mt5, or both")
    return value


def hash_license_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def issue_license_key() -> str:
    return "MQL-" + secrets.token_urlsafe(30)


# ---------- Database ----------


SCHEMA = """
CREATE TABLE IF NOT EXISTS licenses (
    id TEXT PRIMARY KEY,
    product TEXT NOT NULL,
    platform TEXT NOT NULL CHECK(platform IN ('mt4', 'mt5', 'both')),
    license_key_hash TEXT NOT NULL UNIQUE,
    license_key_hint TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'revoked')),
    customer_ref TEXT NOT NULL,
    account_login TEXT NOT NULL,
    broker_server TEXT NOT NULL,
    machine_id TEXT,
    bind_machine_on_first_validation INTEGER NOT NULL DEFAULT 0,
    starts_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    grace_seconds INTEGER NOT NULL DEFAULT 21600,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_validated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_licenses_customer_ref ON licenses(customer_ref);
CREATE INDEX IF NOT EXISTS idx_licenses_account ON licenses(account_login, broker_server);
"""


def using_postgres() -> bool:
    return DATABASE_URL.startswith(("postgresql://", "postgres://"))


class DatabaseConnection:
    """Small placeholder-normalizing wrapper for SQLite and PostgreSQL."""

    def __init__(self, raw: Any, postgres: bool) -> None:
        self.raw = raw
        self.postgres = postgres

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> Any:
        if self.postgres:
            query = query.replace("?", "%s")
        return self.raw.execute(query, params)

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)

    def commit(self) -> None:
        self.raw.commit()

    def rollback(self) -> None:
        self.raw.rollback()

    def close(self) -> None:
        self.raw.close()


@contextmanager
def db_connection() -> Iterator[DatabaseConnection]:
    if using_postgres():
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("Install psycopg[binary] to use LICENSE_DATABASE_URL") from exc
        raw = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        connection = DatabaseConnection(raw, postgres=True)
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    raw = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys=ON")
    raw.execute("PRAGMA journal_mode=WAL")
    connection = DatabaseConnection(raw, postgres=False)
    try:
        yield connection
    finally:
        connection.close()


def initialize_database() -> None:
    with db_connection() as connection:
        connection.executescript(SCHEMA)


@app.on_event("startup")
def startup() -> None:
    initialize_database()


# ---------- Schemas ----------


class LicenseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product: str = Field(default="my-ea", min_length=1, max_length=100)
    platform: str = Field(default="both")
    customer_ref: str = Field(..., min_length=1, max_length=200)
    account_login: str = Field(..., min_length=1, max_length=100)
    broker_server: str = Field(..., min_length=1, max_length=200)
    machine_id: Optional[str] = Field(default=None, max_length=200)
    bind_machine_on_first_validation: bool = False
    starts_at: Optional[str] = None
    expires_at: Optional[str] = None
    duration_days: Optional[int] = Field(default=None, ge=1, le=36500)
    grace_seconds: int = Field(default=DEFAULT_GRACE_SECONDS, ge=0, le=2592000)

    @field_validator("platform")
    @classmethod
    def valid_platform(cls, value: str) -> str:
        return normalize_platform(value)

    @field_validator("product", "customer_ref", "account_login", "broker_server", "machine_id")
    @classmethod
    def trimmed(cls, value: Optional[str]) -> Optional[str]:
        return normalize_text(value) if value is not None else value


class LicenseRenew(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_days: int = Field(..., ge=1, le=36500)


class LicenseValidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    license_key: str = Field(..., min_length=10, max_length=200)
    product: str = Field(default="my-ea", min_length=1, max_length=100)
    platform: str = Field(...)
    account_login: str = Field(..., min_length=1, max_length=100)
    broker_server: str = Field(..., min_length=1, max_length=200)
    machine_id: Optional[str] = Field(default=None, max_length=200)
    ea_version: Optional[str] = Field(default=None, max_length=50)

    @field_validator("platform")
    @classmethod
    def valid_platform(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {"mt4", "mt5"}:
            raise ValueError("platform must be mt4 or mt5")
        return value

    @field_validator("product", "account_login", "broker_server", "machine_id", "ea_version")
    @classmethod
    def trimmed(cls, value: Optional[str]) -> Optional[str]:
        return normalize_text(value) if value is not None else value


class LicenseResponse(BaseModel):
    id: str
    product: str
    platform: str
    status: str
    customer_ref: str
    account_login: str
    broker_server: str
    machine_id: Optional[str]
    bind_machine_on_first_validation: bool
    starts_at: str
    expires_at: str
    grace_seconds: int
    created_at: str
    updated_at: str
    last_validated_at: Optional[str]
    license_key: Optional[str] = None


# ---------- Authentication ----------


def require_admin(x_admin_key: Optional[str] = Header(default=None)) -> None:
    if not ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LICENSE_ADMIN_API_KEY is not configured",
        )
    if not x_admin_key or not hmac.compare_digest(x_admin_key, ADMIN_API_KEY):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid admin key")


# ---------- Serialization ----------


def row_to_license(row: sqlite3.Row, include_key: Optional[str] = None) -> dict[str, Any]:
    result = dict(row)
    result["bind_machine_on_first_validation"] = bool(result["bind_machine_on_first_validation"])
    result.pop("license_key_hash", None)
    if include_key is not None:
        result["license_key"] = include_key
    return result


def public_validation(valid: bool, reason: str, row: Optional[sqlite3.Row] = None, *, state: str = "invalid") -> dict[str, Any]:
    now = utc_now()
    response: dict[str, Any] = {
        "valid": valid,
        "state": state,
        "reason": reason,
        "server_time": iso(now),
    }
    if row is not None:
        response.update(
            {
                "license_id": row["id"],
                "product": row["product"],
                "platform": row["platform"],
                "starts_at": row["starts_at"],
                "expires_at": row["expires_at"],
                "grace_seconds": row["grace_seconds"],
            }
        )
    return response


# ---------- Public endpoints ----------


@app.get("/healthz")
def healthz() -> dict[str, str]:
    initialize_database()
    return {"status": "ok", "service": APP_NAME}


@app.post("/v1/validate")
def validate_license(payload: LicenseValidate, request: Request) -> dict[str, Any]:
    del request  # Reserved for a future rate-limit or audit middleware.
    key_hash = hash_license_key(payload.license_key)
    now = utc_now()

    with db_connection() as connection:
        connection.execute("BEGIN IMMEDIATE" if not using_postgres() else "BEGIN")
        row = connection.execute(
            "SELECT * FROM licenses WHERE license_key_hash = ?",
            (key_hash,),
        ).fetchone()
        if row is None:
            connection.commit()
            return public_validation(False, "license_not_found")

        if row["product"] != payload.product:
            connection.commit()
            return public_validation(False, "product_mismatch", row)
        if row["status"] != "active":
            connection.commit()
            return public_validation(False, "license_revoked", row)
        if row["platform"] not in {payload.platform, "both"}:
            connection.commit()
            return public_validation(False, "platform_mismatch", row)
        if row["account_login"] != payload.account_login:
            connection.commit()
            return public_validation(False, "account_mismatch", row)
        if row["broker_server"].lower() != payload.broker_server.lower():
            connection.commit()
            return public_validation(False, "broker_server_mismatch", row)

        bound_machine = row["machine_id"]
        if bound_machine:
            if not payload.machine_id or bound_machine != payload.machine_id:
                connection.commit()
                return public_validation(False, "machine_mismatch", row)
        elif row["bind_machine_on_first_validation"]:
            if not payload.machine_id:
                connection.commit()
                return public_validation(False, "machine_id_required_for_first_binding", row)
            connection.execute(
                "UPDATE licenses SET machine_id = ?, updated_at = ? WHERE id = ?",
                (payload.machine_id, iso(now), row["id"]),
            )
            row = connection.execute("SELECT * FROM licenses WHERE id = ?", (row["id"],)).fetchone()

        starts_at = parse_datetime(row["starts_at"])
        expires_at = parse_datetime(row["expires_at"])
        if now < starts_at:
            connection.commit()
            return public_validation(False, "license_not_started", row, state="not_started")

        if now <= expires_at:
            state = "active"
            valid = True
            reason = "ok"
        elif now <= expires_at + timedelta(seconds=row["grace_seconds"]):
            state = "grace"
            valid = True
            reason = "grace_period"
        else:
            state = "expired"
            valid = False
            reason = "license_expired"

        connection.execute(
            "UPDATE licenses SET last_validated_at = ?, updated_at = ? WHERE id = ?",
            (iso(now), iso(now), row["id"]),
        )
        connection.commit()
        return public_validation(valid, reason, row, state=state)


# ---------- Admin endpoints ----------


@app.post("/v1/admin/licenses", response_model=LicenseResponse, dependencies=[Depends(require_admin)])
def create_license(payload: LicenseCreate) -> dict[str, Any]:
    now = utc_now()
    starts_at = parse_datetime(payload.starts_at) if payload.starts_at else now
    if payload.expires_at:
        expires_at = parse_datetime(payload.expires_at)
    elif payload.duration_days:
        expires_at = starts_at + timedelta(days=payload.duration_days)
    else:
        raise HTTPException(status_code=422, detail="provide expires_at or duration_days")
    if expires_at <= starts_at:
        raise HTTPException(status_code=422, detail="expires_at must be later than starts_at")

    plaintext_key = issue_license_key()
    license_id = str(uuid.uuid4())
    record = (
        license_id,
        payload.product,
        payload.platform,
        hash_license_key(plaintext_key),
        plaintext_key[-8:],
        "active",
        payload.customer_ref,
        payload.account_login,
        payload.broker_server,
        payload.machine_id,
        int(payload.bind_machine_on_first_validation),
        iso(starts_at),
        iso(expires_at),
        payload.grace_seconds,
        iso(now),
        iso(now),
    )
    with db_connection() as connection:
        try:
            connection.execute(
                """INSERT INTO licenses
                (id, product, platform, license_key_hash, license_key_hint, status,
                 customer_ref, account_login, broker_server, machine_id,
                 bind_machine_on_first_validation, starts_at, expires_at, grace_seconds,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                record,
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="could not create unique license") from exc
        row = connection.execute("SELECT * FROM licenses WHERE id = ?", (license_id,)).fetchone()
    return row_to_license(row, plaintext_key)


@app.get("/v1/admin/licenses", response_model=list[LicenseResponse], response_model_exclude_none=True, dependencies=[Depends(require_admin)])
def list_licenses(
    customer_ref: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if customer_ref:
        clauses.append("customer_ref = ?")
        params.append(normalize_text(customer_ref))
    if status_filter:
        if status_filter not in {"active", "revoked"}:
            raise HTTPException(status_code=422, detail="status must be active or revoked")
        clauses.append("status = ?")
        params.append(status_filter)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with db_connection() as connection:
        rows = connection.execute(
            f"SELECT * FROM licenses{where} ORDER BY created_at DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
    return [row_to_license(row) for row in rows]


@app.get("/v1/admin/licenses/{license_id}", response_model=LicenseResponse, response_model_exclude_none=True, dependencies=[Depends(require_admin)])
def get_license(license_id: str) -> dict[str, Any]:
    with db_connection() as connection:
        row = connection.execute("SELECT * FROM licenses WHERE id = ?", (license_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="license not found")
    return row_to_license(row)


@app.post("/v1/admin/licenses/{license_id}/renew", response_model=LicenseResponse, response_model_exclude_none=True, dependencies=[Depends(require_admin)])
def renew_license(license_id: str, payload: LicenseRenew) -> dict[str, Any]:
    now = utc_now()
    with db_connection() as connection:
        row = connection.execute("SELECT * FROM licenses WHERE id = ?", (license_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="license not found")
        current_expiry = parse_datetime(row["expires_at"])
        base = max(now, current_expiry)
        new_expiry = base + timedelta(days=payload.duration_days)
        connection.execute(
            "UPDATE licenses SET expires_at = ?, status = 'active', updated_at = ? WHERE id = ?",
            (iso(new_expiry), iso(now), license_id),
        )
        updated = connection.execute("SELECT * FROM licenses WHERE id = ?", (license_id,)).fetchone()
    return row_to_license(updated)


@app.post("/v1/admin/licenses/{license_id}/revoke", response_model=LicenseResponse, response_model_exclude_none=True, dependencies=[Depends(require_admin)])
def revoke_license(license_id: str) -> dict[str, Any]:
    now = utc_now()
    with db_connection() as connection:
        row = connection.execute("SELECT * FROM licenses WHERE id = ?", (license_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="license not found")
        connection.execute(
            "UPDATE licenses SET status = 'revoked', updated_at = ? WHERE id = ?",
            (iso(now), license_id),
        )
        updated = connection.execute("SELECT * FROM licenses WHERE id = ?", (license_id,)).fetchone()
    return row_to_license(updated)
