# Trace — current status (13 October 2026)

## Delivered locally

- Working React/TypeScript interface, FastAPI API and separate queue/notification workers.
- Public read-only demo with six genuine Chromium captures across three controlled pages.
- Owner authentication, monitor CRUD, manual checks, pause/resume and private artifact access.
- Guarded public-page renderer, shared compatible fetches, filters, CSS region picker,
  text/visual comparisons, durable versions/checks and notification outbox.
- Schema version 2 with transactional, serialized startup migrations and retention
  protection for both ends of undelivered alert comparisons.
- README, environment example, dependency locks, tests, screenshots, interview/demo
  guide, backups, deployment configuration and requirement audit.

## Verified

- **48 tests passed, 3 subtests passed** in the final full run (19.49s).
- One non-failing Starlette/httpx TestClient deprecation warning remains.
- Frontend TypeScript check and Vite production build passed.
- npm audit: **0 known vulnerabilities** at verification time.
- Fresh source copy + fresh Python environment: locked install, npm ci, build and
  then-current 45-test suite passed. Three later migration/retention tests also pass
  in the final 48-test suite; dependency locks did not change afterward.
- Production renderer: sandbox-enabled capture of example.com through validating proxy.
- Production renderer/proxy against controlled HTTP server: robots, HTTP500,
  CAPTCHA-like content and private redirect rejection passed.
- Browser owner flow, real CSS picker, comparisons, pause and cancellation at desktop
  and mobile sizes passed. Refreshed screenshots visually inspected.
- Compose v5.6.0 configuration validation passed; binary release checksum verified.
- Online backup integrity, schema version 2 and six captures verified.
- Source package excludes environments, secrets, databases, dependency directories,
  development tools and caches. Pattern scan found no credential material in source.

## Submission and optional setup

- The user authorized public GitHub publication. Account access is being verified.
- Submission is source-only. Hosting is not required; no paid services will be used.
- For owner use, set a password locally with `scripts/set_password.py` and restart.
- A future public deployment must pass Docker/Linux isolation and HTTPS checks.
  No Docker daemon is present here; configuration validation is not runtime proof.
- SMTP/Discord credentials and an authorized controlled alert are needed to verify
  actual provider delivery. No external messages were sent.

## Review locally

Use http://127.0.0.1:8000 while the runner is active. Restart from the project root:

```sh
.venv/bin/python scripts/run.py
```

Read AUDIT.md for requirement classifications and honest compatibility limitations.
