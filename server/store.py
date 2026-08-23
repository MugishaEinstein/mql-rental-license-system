"""Browser shop for rental-license purchases.

The shop intentionally supports only a test checkout. It creates a real license
through the same application service used by the administrator API, but it never
collects or charges payment-card details.
"""

from __future__ import annotations

import html
import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field, ValidationError

STORE_ENABLED = os.getenv("LICENSE_STORE_ENABLED", "1").strip().lower() not in {"0", "false", "no"}
STORE_MODE = os.getenv("LICENSE_STORE_MODE", "test").strip().lower()
CATALOG_PATH = Path(__file__).with_name("products.json")

router = APIRouter()


class CatalogProduct(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    product: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=500)
    platform: str = "both"
    duration_days: int = Field(ge=1, le=36500)
    price_cents: int = Field(ge=0)


def esc(value: Any) -> str:
    """Escape catalog and submitted values before placing them in HTML."""
    return html.escape(str(value), quote=True)


def load_catalog() -> dict[str, Any]:
    try:
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="shop catalog is unavailable") from exc
    if not isinstance(catalog, dict) or not isinstance(catalog.get("products"), list):
        raise HTTPException(status_code=500, detail="shop catalog is invalid")
    return catalog


def get_product(plan_id: str) -> CatalogProduct:
    catalog = load_catalog()
    for item in catalog["products"]:
        if isinstance(item, dict) and item.get("id") == plan_id:
            return CatalogProduct.model_validate(item)
    raise HTTPException(status_code=404, detail="plan not found")


def money(cents: int, currency: str = "USD") -> str:
    return f"{esc(currency)} {cents / 100:.2f}"


def page(title: str, body: str) -> HTMLResponse:
    banner = ""
    if STORE_MODE != "live":
        banner = (
            '<div class="banner"><strong>TEST MODE</strong> — no card is charged. '
            "A real license key is still created.</div>"
        )
    html_document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title>{esc(title)}</title>
  <style>
    :root {{ --bg:#09111f; --surface:#111c2e; --surface-2:#0d1728; --line:#263650; --text:#edf4ff; --muted:#9aabc5; --accent:#4f8cff; --accent-2:#83adff; --ok:#45d483; --warn:#f4c76b; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:radial-gradient(900px 420px at 8% -12%, #234b9f55, transparent), var(--bg); color:var(--text); }}
    a {{ color:var(--accent-2); }}
    .wrap {{ max-width:1060px; margin:0 auto; padding:36px 20px 72px; }}
    .topbar {{ display:flex; align-items:center; justify-content:space-between; gap:20px; margin-bottom:58px; }}
    .brand {{ color:var(--text); text-decoration:none; font-weight:800; letter-spacing:-.02em; }}
    .status {{ color:var(--muted); font-size:13px; }}
    .hero {{ max-width:720px; margin-bottom:34px; }}
    .eyebrow {{ color:var(--accent-2); font-size:12px; font-weight:800; letter-spacing:.12em; text-transform:uppercase; }}
    h1 {{ font-size:clamp(34px,6vw,58px); line-height:1.04; letter-spacing:-.05em; margin:12px 0 16px; }}
    h2 {{ margin:0; letter-spacing:-.025em; }}
    p.lead {{ color:var(--muted); font-size:18px; line-height:1.55; margin:0; }}
    .grid {{ display:grid; gap:18px; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); }}
    .card {{ background:linear-gradient(160deg,#14213a,#0e182a); border:1px solid var(--line); border-radius:18px; padding:22px; display:flex; flex-direction:column; gap:12px; box-shadow:0 18px 45px #0000001c; }}
    .card.featured {{ border-color:#4f8cffaa; box-shadow:0 18px 50px #2d67d522; }}
    .tag {{ display:inline-flex; align-self:flex-start; color:#bcd3ff; border:1px solid #4f8cff66; background:#2e65bf22; border-radius:999px; padding:5px 9px; font-size:11px; font-weight:800; text-transform:uppercase; letter-spacing:.08em; }}
    .price {{ font-size:30px; font-weight:800; letter-spacing:-.04em; }}
    .muted {{ color:var(--muted); font-size:14px; line-height:1.5; }}
    .meta {{ color:#c9d6ea; font-size:13px; }}
    .btn {{ display:inline-flex; width:100%; justify-content:center; align-items:center; text-align:center; text-decoration:none; cursor:pointer; background:var(--accent); color:white; border:0; border-radius:11px; padding:12px 15px; font-weight:750; font-size:15px; transition:background .15s,transform .15s; }}
    .btn:hover {{ background:#6a9dff; transform:translateY(-1px); }}
    .btn.secondary {{ width:auto; background:transparent; border:1px solid var(--line); color:var(--text); }}
    .banner {{ background:#3b270d; color:#ffe1a1; padding:11px 16px; text-align:center; font-size:14px; border-bottom:1px solid #71511e; }}
    .form-card {{ max-width:650px; margin:0 auto; }}
    label {{ display:block; font-size:13px; color:#b4c2d8; margin:5px 0 7px; }}
    input, select {{ width:100%; padding:12px 13px; border-radius:11px; border:1px solid var(--line); outline:none; background:var(--surface-2); color:var(--text); font:inherit; }}
    input:focus, select:focus {{ border-color:var(--accent); box-shadow:0 0 0 3px #4f8cff2b; }}
    .keybox {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; background:#06101e; border:1px dashed #466182; padding:16px; border-radius:12px; word-break:break-all; color:#d9e8ff; }}
    .ok {{ color:var(--ok); font-weight:800; }}
    .help {{ color:var(--muted); padding-left:20px; line-height:1.7; }}
    .footer {{ color:var(--muted); font-size:13px; margin-top:44px; padding-top:20px; border-top:1px solid var(--line); }}
  </style>
</head>
<body>
  {banner}
  <div class="wrap">
    <nav class="topbar"><a class="brand" href="/shop">EA Rental Shop</a><span class="status">Account-bound licensing</span></nav>
    {body}
    <footer class="footer">Test checkout only. No card data is collected. Each issued key is bound to the account login and broker server entered during checkout.</footer>
  </div>
</body>
</html>"""
    return HTMLResponse(html_document)


@router.get("/", include_in_schema=False)
def root_redirect() -> RedirectResponse:
    return RedirectResponse(url="/shop", status_code=302)


@router.get("/shop", response_class=HTMLResponse)
def shop_home() -> HTMLResponse:
    if not STORE_ENABLED:
        raise HTTPException(status_code=404, detail="store disabled")
    catalog = load_catalog()
    currency = str(catalog.get("currency", "USD"))
    cards: list[str] = []
    for index, raw_item in enumerate(catalog["products"]):
        item = CatalogProduct.model_validate(raw_item)
        featured = " featured" if index == 1 else ""
        badge = '<span class="tag">Most popular</span>' if index == 1 else ""
        cards.append(
            f"""
            <article class="card{featured}">
              {badge}
              <h2>{esc(item.name)}</h2>
              <div class="price">{money(item.price_cents, currency)}</div>
              <p class="muted">{esc(item.description)}</p>
              <p class="meta">Platform: {esc(item.platform)} · {item.duration_days} days</p>
              <a class="btn" href="/shop/buy/{esc(item.id)}">Choose this plan</a>
            </article>"""
        )
    return page(
        str(catalog.get("store_name", "EA Rental Shop")),
        f"""
        <section class="hero">
          <div class="eyebrow">Automated trading rentals</div>
          <h1>Run your EA with confidence.</h1>
          <p class="lead">Choose a rental period for your MT4 or MT5 account. Every license is checked online and bound to your account login and broker server.</p>
        </section>
        <section class="grid">{"".join(cards)}</section>
        """,
    )


@router.get("/shop/buy/{plan_id}", response_class=HTMLResponse)
def shop_buy(plan_id: str) -> HTMLResponse:
    if not STORE_ENABLED:
        raise HTTPException(status_code=404, detail="store disabled")
    plan = get_product(plan_id)
    catalog = load_catalog()
    platform_options = """
          <option value="both" selected>MT4 and MT5</option>
          <option value="mt4">MT4 only</option>
          <option value="mt5">MT5 only</option>"""
    if plan.platform != "both":
        platform_options = f'<option value="{esc(plan.platform)}" selected>{esc(plan.platform.upper())} only</option>'
    return page(
        f"Buy {plan.name}",
        f"""
        <div class="form-card">
          <p class="muted"><a href="/shop">← Back to plans</a></p>
          <h1>{esc(plan.name)}</h1>
          <p class="lead">{esc(plan.description)} · {money(plan.price_cents, str(catalog.get("currency", "USD")))} · {plan.duration_days} days</p>
          <form class="card" method="post" action="/shop/checkout">
            <input type="hidden" name="plan_id" value="{esc(plan.id)}">
            <label for="email">Email (used as customer reference)</label>
            <input id="email" name="email" type="email" required autocomplete="email" placeholder="you@example.com">
            <label for="account_login">MT account login</label>
            <input id="account_login" name="account_login" required inputmode="numeric" maxlength="100" placeholder="123456">
            <label for="broker_server">Broker server name</label>
            <input id="broker_server" name="broker_server" required maxlength="200" placeholder="DemoBroker-Live">
            <label for="platform">Platform</label>
            <select id="platform" name="platform">{platform_options}</select>
            <p class="muted">Enter the account number and server string exactly as they appear in MetaTrader. Test mode creates a real license but does not charge a card.</p>
            <button class="btn" type="submit">Issue rental license</button>
          </form>
        </div>
        """,
    )


@router.post("/shop/checkout", response_class=HTMLResponse)
def shop_checkout(
    request: Request,
    plan_id: str = Form(...),
    email: str = Form(...),
    account_login: str = Form(...),
    broker_server: str = Form(...),
    platform: str = Form("both"),
) -> HTMLResponse:
    if not STORE_ENABLED:
        raise HTTPException(status_code=404, detail="store disabled")
    if STORE_MODE != "test":
        raise HTTPException(status_code=501, detail="Live card payments are not wired yet. Use LICENSE_STORE_MODE=test.")

    email = email.strip()
    account_login = account_login.strip()
    broker_server = broker_server.strip()
    platform = platform.strip().lower()
    if "@" not in email or len(email) > 200:
        raise HTTPException(status_code=422, detail="a valid email is required")
    if platform not in {"mt4", "mt5", "both"}:
        raise HTTPException(status_code=422, detail="invalid platform")

    plan = get_product(plan_id)
    if plan.platform != "both" and platform != plan.platform:
        raise HTTPException(status_code=422, detail="selected platform is not supported by this plan")

    from server.main import LicenseCreate, create_license

    try:
        created = create_license(
            LicenseCreate(
                product=plan.product,
                platform=platform,
                customer_ref=email,
                account_login=account_login,
                broker_server=broker_server,
                duration_days=plan.duration_days,
            )
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="invalid checkout details") from exc

    key = str(created.get("license_key", ""))
    base = str(request.base_url).rstrip("/")
    return page(
        "License issued",
        f"""
        <div class="form-card">
          <p class="muted"><a href="/shop">← Back to shop</a></p>
          <h1 class="ok">License issued</h1>
          <p class="lead">Save this key now. It is not stored in plaintext and will not be shown again.</p>
          <div class="card">
            <div class="muted">License key</div>
            <div class="keybox">{esc(key)}</div>
            <p class="muted">Product: {esc(created["product"])} · Account: {esc(created["account_login"])} · Server: {esc(created["broker_server"])} · Expires: {esc(created["expires_at"])}</p>
          </div>
          <h2>Configure the EA</h2>
          <ul class="help">
            <li>ApiUrl: <code>{esc(base)}/v1/validate</code></li>
            <li>Product: <code>{esc(created["product"])}</code></li>
            <li>LicenseKey: the key above</li>
            <li>Allow WebRequest for <code>{esc(base)}</code></li>
          </ul>
          <a class="btn secondary" href="/shop">Issue another license</a>
        </div>
        """,
    )
