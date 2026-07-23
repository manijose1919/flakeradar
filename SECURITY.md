# Security Policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately via GitHub Security Advisories
(the "Report a vulnerability" button on the Security tab) rather than a public
issue. We aim to acknowledge reports within a few days.

## Trust model

FlakeRadar's security posture is deliberate and documented:

- **Write path is token-gated.** `POST /api/ingest` and `GET /api/quarantine`
  require the `X-API-Key` header, compared in constant time. These are the
  endpoints external CI calls.
- **Read/dashboard APIs are open by design.** They are expected to sit on a
  private network or behind an authenticating reverse proxy. Do not expose the
  dashboard directly to the public internet.
- **Secrets** (`FLAKERADAR_API_TOKEN`, `FLAKERADAR_GITHUB_TOKEN`) live only in
  `.env`, which is git-ignored. Never commit them. Rotate the API token if it
  is ever exposed.
