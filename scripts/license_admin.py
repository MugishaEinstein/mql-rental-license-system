#!/usr/bin/env python3
"""Small administrator CLI for the MQL License API."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def call(method: str, url: str, admin_key: str, payload: dict | None = None) -> None:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Admin-Key": admin_key,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            print(json.dumps(json.load(response), indent=2))
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8", errors="replace"), file=sys.stderr)
        raise SystemExit(exc.code)


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage MQL rental licenses")
    parser.add_argument("--url", default=os.getenv("LICENSE_API_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--admin-key", default=os.getenv("LICENSE_ADMIN_API_KEY"), required=False)
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create")
    create.add_argument("--product", default="my-ea")
    create.add_argument("--platform", choices=["mt4", "mt5", "both"], default="both")
    create.add_argument("--customer-ref", required=True)
    create.add_argument("--account-login", required=True)
    create.add_argument("--broker-server", required=True)
    create.add_argument("--duration-days", type=int, required=True)
    create.add_argument("--machine-id")
    create.add_argument("--bind-machine-on-first-validation", action="store_true")
    create.add_argument("--grace-seconds", type=int, default=21600)

    renew = sub.add_parser("renew")
    renew.add_argument("license_id")
    renew.add_argument("--duration-days", type=int, required=True)

    revoke = sub.add_parser("revoke")
    revoke.add_argument("license_id")

    sub.add_parser("list")

    args = parser.parse_args()
    if not args.admin_key:
        parser.error("set --admin-key or LICENSE_ADMIN_API_KEY")
    base = args.url.rstrip("/")

    if args.command == "create":
        payload = {
            "product": args.product,
            "platform": args.platform,
            "customer_ref": args.customer_ref,
            "account_login": args.account_login,
            "broker_server": args.broker_server,
            "duration_days": args.duration_days,
            "machine_id": args.machine_id,
            "bind_machine_on_first_validation": args.bind_machine_on_first_validation,
            "grace_seconds": args.grace_seconds,
        }
        call("POST", f"{base}/v1/admin/licenses", args.admin_key, payload)
    elif args.command == "renew":
        call("POST", f"{base}/v1/admin/licenses/{args.license_id}/renew", args.admin_key, {"duration_days": args.duration_days})
    elif args.command == "revoke":
        call("POST", f"{base}/v1/admin/licenses/{args.license_id}/revoke", args.admin_key)
    else:
        call("GET", f"{base}/v1/admin/licenses", args.admin_key)


if __name__ == "__main__":
    main()
