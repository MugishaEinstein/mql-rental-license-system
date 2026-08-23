import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from server import main


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_client(tmp_path: Path) -> TestClient:
    main.DB_PATH = tmp_path / "licenses.sqlite3"
    main.ADMIN_API_KEY = "test-admin-key"
    return TestClient(main.app)


def test_license_lifecycle_and_bindings(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        headers = {"X-Admin-Key": "test-admin-key"}
        created = client.post(
            "/v1/admin/licenses",
            headers=headers,
            json={
                "product": "demo-ea",
                "platform": "both",
                "customer_ref": "customer-001",
                "account_login": "123456",
                "broker_server": "DemoBroker-Live",
                "duration_days": 30,
            },
        )
        assert created.status_code == 200, created.text
        license_data = created.json()
        assert license_data["license_key"].startswith("MQL-")
        license_id = license_data["id"]

        valid = client.post(
            "/v1/validate",
            json={
                "license_key": license_data["license_key"],
                "product": "demo-ea",
                "platform": "mt4",
                "account_login": "123456",
                "broker_server": "demobroker-live",
            },
        )
        assert valid.status_code == 200
        assert valid.json()["valid"] is True
        assert valid.json()["state"] == "active"

        wrong_account = client.post(
            "/v1/validate",
            json={
                "license_key": license_data["license_key"],
                "product": "demo-ea",
                "platform": "mt5",
                "account_login": "999999",
                "broker_server": "DemoBroker-Live",
            },
        )
        assert wrong_account.json() == {
            "valid": False,
            "state": "invalid",
            "reason": "account_mismatch",
            "server_time": wrong_account.json()["server_time"],
            "license_id": license_id,
            "product": "demo-ea",
            "platform": "both",
            "starts_at": license_data["starts_at"],
            "expires_at": license_data["expires_at"],
            "grace_seconds": 21600,
        }

        revoked = client.post(f"/v1/admin/licenses/{license_id}/revoke", headers=headers)
        assert revoked.status_code == 200
        after_revoke = client.post(
            "/v1/validate",
            json={
                "license_key": license_data["license_key"],
                "product": "demo-ea",
                "platform": "mt5",
                "account_login": "123456",
                "broker_server": "DemoBroker-Live",
            },
        )
        assert after_revoke.json()["reason"] == "license_revoked"


def test_expiry_and_renewal(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        headers = {"X-Admin-Key": "test-admin-key"}
        now = datetime.now(timezone.utc).replace(microsecond=0)
        created = client.post(
            "/v1/admin/licenses",
            headers=headers,
            json={
                "product": "expired-ea",
                "platform": "mt5",
                "customer_ref": "customer-002",
                "account_login": "777",
                "broker_server": "Broker",
                "starts_at": iso(now - timedelta(days=3)),
                "expires_at": iso(now - timedelta(days=2)),
                "grace_seconds": 0,
            },
        )
        assert created.status_code == 200, created.text
        data = created.json()
        expired = client.post(
            "/v1/validate",
            json={
                "license_key": data["license_key"],
                "product": "expired-ea",
                "platform": "mt5",
                "account_login": "777",
                "broker_server": "Broker",
            },
        )
        assert expired.json()["reason"] == "license_expired"

        renewed = client.post(
            f"/v1/admin/licenses/{data['id']}/renew",
            headers=headers,
            json={"duration_days": 10},
        )
        assert renewed.status_code == 200
        valid_after_renewal = client.post(
            "/v1/validate",
            json={
                "license_key": data["license_key"],
                "product": "expired-ea",
                "platform": "mt5",
                "account_login": "777",
                "broker_server": "Broker",
            },
        )
        assert valid_after_renewal.json()["valid"] is True


def test_first_machine_binding(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        headers = {"X-Admin-Key": "test-admin-key"}
        created = client.post(
            "/v1/admin/licenses",
            headers=headers,
            json={
                "product": "machine-ea",
                "platform": "mt4",
                "customer_ref": "customer-003",
                "account_login": "888",
                "broker_server": "Broker",
                "duration_days": 10,
                "bind_machine_on_first_validation": True,
            },
        )
        data = created.json()
        missing_machine = client.post(
            "/v1/validate",
            json={
                "license_key": data["license_key"],
                "product": "machine-ea",
                "platform": "mt4",
                "account_login": "888",
                "broker_server": "Broker",
            },
        )
        assert missing_machine.json()["reason"] == "machine_id_required_for_first_binding"

        first = client.post(
            "/v1/validate",
            json={
                "license_key": data["license_key"],
                "product": "machine-ea",
                "platform": "mt4",
                "account_login": "888",
                "broker_server": "Broker",
                "machine_id": "server-a",
            },
        )
        assert first.json()["valid"] is True

        second_machine = client.post(
            "/v1/validate",
            json={
                "license_key": data["license_key"],
                "product": "machine-ea",
                "platform": "mt4",
                "account_login": "888",
                "broker_server": "Broker",
                "machine_id": "server-b",
            },
        )
        assert second_machine.json()["reason"] == "machine_mismatch"


def test_shop_test_checkout_issues_real_license(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        home = client.get("/shop")
        assert home.status_code == 200
        assert "EA Rental Shop" in home.text
        assert "TEST MODE" in home.text
        assert "/shop/buy/my-ea-30" in home.text

        checkout_page = client.get("/shop/buy/my-ea-30")
        assert checkout_page.status_code == 200
        assert "Issue rental license" in checkout_page.text

        issued = client.post(
            "/shop/checkout",
            data={
                "plan_id": "my-ea-30",
                "email": "shop-customer@example.com",
                "account_login": "456789",
                "broker_server": "ShopBroker-Live",
                "platform": "mt5",
            },
        )
        assert issued.status_code == 200, issued.text
        assert "License issued" in issued.text
        assert "MQL-" in issued.text

        listed = client.get("/v1/admin/licenses", headers={"X-Admin-Key": "test-admin-key"})
        assert listed.status_code == 200
        records = listed.json()
        record = next(item for item in records if item["customer_ref"] == "shop-customer@example.com")
        assert "license_key" not in record

        # Extract the one-time key from the response page for a full integration check.
        key = issued.text.split("<div class=\"keybox\">")[1].split("</div>")[0]
        validated = client.post(
            "/v1/validate",
            json={
                "license_key": key,
                "product": "my-ea",
                "platform": "mt5",
                "account_login": "456789",
                "broker_server": "ShopBroker-Live",
            },
        )
        assert validated.status_code == 200
        assert validated.json()["valid"] is True
