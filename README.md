# MQL4/MT5 Rental Licensing System

This project provides a small licensing service and client wrapper for commercial MT4 and MT5 Expert Advisors. It binds a rental license to a product, platform, customer account login, and broker server. An optional machine identifier can be bound at creation or at first successful validation.

The service uses SQLite for the initial Ubuntu test deployment and also accepts PostgreSQL through `LICENSE_DATABASE_URL`. The API is intentionally isolated behind a small persistence boundary so the same MQL client contract works with either database. The administrator API key is read from the environment and plaintext license keys are never stored in the database; only their SHA-256 hashes and an eight-character hint are retained.

> **Important security boundary:** An EX4/EX5 file is compiled and distributed without the original MQL source, but no client-side binary can provide perfect protection against reverse engineering. The licensing design therefore treats the server as the authority, uses HTTPS, binds licenses to account metadata, revalidates periodically, and supports revocation. The included EA wrapper does not contain a trading strategy; place the strategy in `OnTick()` or integrate the wrapper into the existing EA.

## Repository layout

| Path | Purpose |
| --- | --- |
| `server/main.py` | FastAPI service, SQLite schema, validation logic, and admin endpoints |
| `mt4/LicenseClient.mqh` | MT4 WebRequest client |
| `mt4/LicensedEA.mq4` | MT4 sample EA wrapper |
| `mt5/LicenseClient.mqh` | MT5 WebRequest client |
| `mt5/LicensedEA.mq5` | MT5 sample EA wrapper |
| `scripts/license_admin.py` | CLI for license creation, renewal, revocation, and listing |
| `scripts/build_mql.sh` | Optional MetaEditor-through-Wine build helper |
| `deploy/mql-license-api.service` | systemd service template |
| `deploy/Caddyfile.example` | HTTPS reverse-proxy template |
| `tests/test_api.py` | Automated API lifecycle tests |

## Local Ubuntu test

Use Python 3.10 or newer. From the project directory, create a virtual environment and install the dependencies:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export LICENSE_DB_PATH="$PWD/data/licenses.sqlite3"
export LICENSE_ADMIN_API_KEY="replace-this-with-a-long-random-secret"
uvicorn server.main:app --host 127.0.0.1 --port 8000
```

In another shell, check that the service is alive:

```bash
curl http://127.0.0.1:8000/healthz
```

Create a thirty-day MT4/MT5 license. The returned `license_key` is shown only at creation time, so deliver it to the customer through a secure channel:

```bash
export LICENSE_API_URL=http://127.0.0.1:8000
export LICENSE_ADMIN_API_KEY="replace-this-with-a-long-random-secret"
python3 scripts/license_admin.py create \
  --product my-ea \
  --platform both \
  --customer-ref customer-001 \
  --account-login 123456 \
  --broker-server DemoBroker-Live \
  --duration-days 30
```

Validate a license directly:

```bash
curl -sS -X POST http://127.0.0.1:8000/v1/validate \
  -H 'Content-Type: application/json' \
  -d '{
    "license_key": "MQL-PASTE_THE_RETURNED_KEY",
    "product": "my-ea",
    "platform": "mt4",
    "account_login": "123456",
    "broker_server": "DemoBroker-Live"
  }'
```

The response contains `valid`, `state`, `reason`, `server_time`, `starts_at`, and `expires_at`. A license is accepted when it is active. If the current time is after expiry but inside the configured grace period, it is returned as `valid: true` with `state: grace`. Revoked, mismatched, not-started, and expired licenses are rejected.

Run the test suite with:

```bash
pip install -r requirements-dev.txt
python3 -m pytest -q
```

## Ubuntu service deployment

For a persistent deployment, copy the project to `/opt/mql-license-system`, create a dedicated user, and give it a writable data directory:

```bash
sudo useradd --system --home /opt/mql-license-system --shell /usr/sbin/nologin licenseapi || true
sudo mkdir -p /opt/mql-license-system /var/lib/mql-license-api /etc/mql-license-api
sudo cp -a . /opt/mql-license-system/
sudo chown -R licenseapi:licenseapi /opt/mql-license-system /var/lib/mql-license-api
sudo -u licenseapi python3 -m venv /opt/mql-license-system/.venv
sudo -u licenseapi /opt/mql-license-system/.venv/bin/pip install -r /opt/mql-license-system/requirements.txt
```

Create `/etc/mql-license-api/.env` with a high-entropy administrator key. For the initial single-server test, use SQLite:

```dotenv
LICENSE_DATABASE_URL=
LICENSE_DB_PATH=/var/lib/mql-license-api/licenses.sqlite3
LICENSE_ADMIN_API_KEY=replace-with-a-long-random-secret
LICENSE_DEFAULT_GRACE_SECONDS=21600
```

For PostgreSQL, install PostgreSQL separately, create the database and service user, and replace the database settings with a connection URL:

```dotenv
LICENSE_DATABASE_URL=postgresql://licenseapi:change-me@127.0.0.1:5432/mql_license
LICENSE_DB_PATH=/var/lib/mql-license-api/licenses.sqlite3
LICENSE_ADMIN_API_KEY=replace-with-a-long-random-secret
LICENSE_DEFAULT_GRACE_SECONDS=21600
```

When `LICENSE_DATABASE_URL` starts with `postgresql://` or `postgres://`, the service initializes and uses PostgreSQL; otherwise it uses SQLite.

Install and start the service:

```bash
sudo cp deploy/mql-license-api.service /etc/systemd/system/mql-license-api.service
sudo systemctl daemon-reload
sudo systemctl enable --now mql-license-api
sudo systemctl status mql-license-api
```

The API listens on `127.0.0.1:8000`, so it is not directly exposed to the public network. Put it behind a domain and TLS reverse proxy. The included Caddy example can be used after installing Caddy and replacing `license.example.com` with a DNS name pointing to the server:

```bash
sudo cp deploy/Caddyfile.example /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Use the resulting HTTPS URL as the EA `ApiUrl`, for example `https://license.example.com/v1/validate`. Do not use plain HTTP for customer terminals except for isolated local testing.

## MT4/MT5 integration

Copy the appropriate `LicenseClient.mqh` into the same source directory as the EA, include it, and call the platform-specific function in `OnInit()`:

```mql
#include "LicenseClient.mqh"

bool licensed = CheckLicenseMT4(ApiUrl, LicenseKey, Product, 5000, MachineId);
if(!licensed)
   return(INIT_FAILED);
```

The sample wrappers perform the first check during initialization and repeat it on a timer. If a later check fails, they remove the EA from the chart. Integrate the same pattern into the real trading EA rather than distributing the placeholder wrapper as a finished strategy.

In the terminal, add the base URL, not the full endpoint path, to the WebRequest allow-list: `Tools -> Options -> Expert Advisors -> Allow WebRequest for listed URL`. The official MQL4 and MQL5 references require this allow-list entry, describe the custom-header overload used here, and note that WebRequest is synchronous and is unavailable from indicators and the Strategy Tester [1] [2].

## EX4/EX5 compilation

The Ubuntu server can host the licensing API, but it does not itself provide the MetaEditor compiler. MetaEditor is the component that converts MQ4/MQ5 source to EX4/EX5 executable files. The official MetaEditor documentation states that executable files are produced by compiling the main MQ4/MQ5 file or project, and that compiled files can be distributed without the original source [3].

There are three supported build paths:

| Build path | When to use it | Result |
| --- | --- | --- |
| MetaEditor on Windows | Recommended release build | Native `.ex4` or `.ex5` |
| MetaEditor installed under Wine on Ubuntu | Suitable for a controlled Ubuntu build server if the terminal/compiler package works correctly | `.ex4` or `.ex5` through `scripts/build_mql.sh` |
| A Windows CI runner or release workstation | Suitable for repeatable commercial builds | Versioned release artifacts |

The helper expects a real `metaeditor.exe` path and a valid Wine installation:

```bash
chmod +x scripts/build_mql.sh
./scripts/build_mql.sh \
  --metaeditor "$HOME/.wine/drive_c/Program Files/MetaTrader 5/metaeditor64.exe" \
  --source "$PWD/mt5/LicensedEA.mq5"
```

If MetaEditor is not available, compile the source on a Windows MetaTrader installation and deploy only the resulting EX4/EX5 plus the customer-specific input values. The sandbox used to prepare this package does not contain MetaEditor or Wine, so it is not possible to honestly claim that EX4/EX5 binaries were generated here.

## API contract

The public validation endpoint is `POST /v1/validate` and does not require the administrator key. Its request includes `license_key`, `product`, `platform`, `account_login`, and `broker_server`, with optional `machine_id` and `ea_version`. It returns HTTP 200 with a JSON decision so the EA can distinguish network/HTTP failures from a normal license rejection in its log.

The administrator endpoints use `X-Admin-Key` and are:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/v1/admin/licenses` | Create a license and return its plaintext key once |
| `GET` | `/v1/admin/licenses` | List licenses without plaintext keys |
| `GET` | `/v1/admin/licenses/{id}` | Retrieve one license |
| `POST` | `/v1/admin/licenses/{id}/renew` | Extend expiry and reactivate |
| `POST` | `/v1/admin/licenses/{id}/revoke` | Revoke immediately |

For production, protect the administrator key, restrict administrative access at the network layer or through a separate management VPN, back up the SQLite file when SQLite is selected, and use PostgreSQL when concurrent administration or multi-node operation requires it. The service remains a single API process; PostgreSQL provides the durable shared database when multiple API instances are later introduced.

## References

[1]: https://docs.mql4.com/common/webrequest "MQL4 Reference: WebRequest"

[2]: https://www.mql5.com/en/docs/network/webrequest "MQL5 Reference: WebRequest"

[3]: https://www.metatrader5.com/en/metaeditor/help/development/compile "MetaEditor Help: Compilation"
