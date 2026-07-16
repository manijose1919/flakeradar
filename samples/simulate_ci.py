"""Replay a realistic CI history into a running FlakeRadar instance.

Usage:  python samples/simulate_ci.py [base_url] [token]
Defaults: http://localhost:8000  /  changeme

Simulates 14 CI runs containing:
- test_checkout_total_rounding   -> genuinely flaky (random failures + one
                                    same-SHA retry that flips fail->pass)
- test_payment_gateway_timeout   -> mildly flaky (occasional failure)
- test_schema_migration_v42      -> broken: fails EVERY run (should score low)
- 5 stable tests                 -> always pass
"""
import random
import sys

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
TOKEN = sys.argv[2] if len(sys.argv) > 2 else "changeme"

rng = random.Random(42)

STABLE = [
    "test_login_with_valid_credentials",
    "test_signup_sends_welcome_email",
    "test_cart_add_and_remove",
    "test_product_search_pagination",
    "test_invoice_pdf_render",
]


def case_xml(name: str, status: str, classname: str = "tests.e2e.test_shop") -> str:
    body = ""
    if status == "failed":
        body = (
            '<failure message="AssertionError: expected 104.85, got 104.84">'
            "tests/e2e/test_shop.py:88: AssertionError</failure>"
        )
    return f'<testcase classname="{classname}" name="{name}" time="{rng.uniform(0.1, 2.5):.2f}">{body}</testcase>'


def report(cases: list[tuple[str, str]]) -> bytes:
    inner = "".join(case_xml(n, s) for n, s in cases)
    return (
        f'<testsuites><testsuite name="e2e" tests="{len(cases)}">{inner}</testsuite></testsuites>'
    ).encode()


def post(client: httpx.Client, sha: str, run_id: str, cases: list[tuple[str, str]]):
    resp = client.post(
        f"{BASE}/api/ingest",
        params={"commit_sha": sha, "branch": "main", "ci_run_id": run_id},
        content=report(cases),
        headers={"X-API-Key": TOKEN, "Content-Type": "application/xml"},
    )
    resp.raise_for_status()
    print(f"run {run_id} @ {sha[:8]}: {resp.json()['counts']}")


def main():
    with httpx.Client(timeout=10) as client:
        for i in range(14):
            sha = f"{rng.getrandbits(160):040x}"
            cases = [(n, "passed") for n in STABLE]
            checkout = "failed" if rng.random() < 0.35 else "passed"
            if i == 6:
                checkout = "failed"  # guarantee the same-SHA retry demo below
            gateway = "failed" if rng.random() < 0.15 else "passed"
            cases.append(("test_checkout_total_rounding", checkout))
            cases.append(("test_payment_gateway_timeout", gateway))
            cases.append(("test_schema_migration_v42", "failed"))
            post(client, sha, f"run-{i}", cases)

            # The habit FlakeRadar exploits: a failed run gets re-run on the
            # same commit. Replay run 6's failure as a same-SHA retry that passes.
            if i == 6 and checkout == "failed":
                retry = [(n, "passed") for n in STABLE]
                retry.append(("test_checkout_total_rounding", "passed"))
                retry.append(("test_payment_gateway_timeout", gateway))
                retry.append(("test_schema_migration_v42", "failed"))
                post(client, sha, f"run-{i}-retry", retry)
    print("done.")


if __name__ == "__main__":
    main()
