# Testing notes — 13 October 2026

These notes record what was tested and what still needs checking. Real notification
delivery and Linux deployment have not been tested.

## Checks completed

- Original comparison/persistence tests were rerun before changes: 15 passed.
- A fresh source copy and fresh Python environment installed `requirements.lock`;
  `npm ci`, type checking, production build and the then-current 45-test suite passed.
  This used the host's installed Chromium cache, not a freshly provisioned operating system.
- Additional retention/migration regression tests were subsequently added. Final full suite: **48 tests passed and 3 subtests passed**, with one non-failing TestClient deprecation warning. Frontend audit: zero known vulnerabilities.
- The actual renderer captured `https://example.com/` through the validating proxy
  with Chromium sandbox enabled: PNG output observed, 81,174 bytes in the smoke run.
- Desktop 1440px and mobile 390px browser flows were exercised. No horizontal overflow
  at 390px; keyboard navigation, picker selection, preview, pause and delete cancellation
  were checked. Real UI screenshots are in `docs/screenshots/`.
- Docker Compose configuration was validated with the official standalone Compose
  binary v5.6.0, whose release SHA-256 was checked. No daemon/container execution occurred.
- The source repository is public. No real email/Discord message was sent, no hosted
  app was deployed, and the recruitment form was not submitted.

## Official requirements

| Requirement | Status | Notes |
|---|---|---|
| URL, name, 15 min–24 h interval | Implemented and tested | Pydantic constraints, API validation test, UI create flow |
| Headless rendering | Implemented and tested | Real Chromium fixture renders, actual public-page smoke capture |
| Scheduler and durable queue | Implemented and tested | Atomic claims, lease/retry/coalescing tests; separate worker and process lock |
| Public pages; no website credentials | Implemented and tested | URL policy, fresh non-persistent contexts, GET/HEAD only, no login features |
| Text + screenshot; changed hashes only | Implemented and tested | PNG decoding, stored text, unchanged checks, reversion and baseline tests |
| Noise filtering and sensitivity | Implemented and tested | Timestamp/ad/counter/token fixture changes, explicit filters, price preservation, cumulative core test. Arbitrary noise classification is not claimed |
| Visual watch/ignore selector picker | Implemented and tested | Real screenshot/DOM geometry; owner browser selects element, previews text, persists selector. Top-level light DOM only |
| Text, highlighted image, arbitrary-version comparison | Implemented and tested | Comparison APIs and browser view switching; real image diff produced; dimensions padded. Pixel shifts are not semantic conclusions |
| Email and Discord alerts | Implemented but not fully verified | Outbox tests, SMTP TLS/recipient adapter test, Discord destination guard; real provider delivery has not been authorized/configured |
| Duplicate alert prevention | Implemented and tested | Unique version/channel events, retry/uncertain handling; exact-once external delivery is not claimed |
| Timeline and status dashboard | Implemented and tested | Connected UI, actual DB records, logs, last checked/changed and pause states |
| Pause/resume/delete/manual checks | Implemented and tested | API/queue paths, browser pause and delete cancellation, DB deletion cascade. Manual checks share rate limits |
| Public deployment | Not implemented | Hosting configuration prepared; no paid account/server/domain provisioned |
| Public GitHub repository | Published | https://github.com/prashanthmanokar2026/trace-website-change-detector |

## Other checks

| Area | Status | Notes |
|---|---|---|
| Shared compatible fetches | Implemented and tested | 200 subscriptions: one browser render and one actual fixture request; individual persistence. Not a 200-user load test |
| CAPTCHA/outage distinction | Partially implemented | Production renderer test handles HTTP 500, known challenge phrase and robots denial. Unknown HTTP-200 outage content remains a heuristic limitation |
| Safe redirects and DNS | Implemented and tested | Mixed DNS rejection, validated numeric-IP connector, production proxy redirect-to-loopback test |
| Deployed browser isolation | Implemented but not fully verified | Sandbox enabled in live Mac capture, internal Docker network + profile prepared. Linux direct-egress gate requires actual host |
| Resource budgets | Implemented but not fully verified | Time, request, proxy byte, geometry/text/storage limits in code; container memory/CPU limits not runtime tested |
| Owner auth and private artifacts | Implemented and tested | Session/CSRF/Host/Origin checks; anonymous capture and comparison reads denied |
| Migrations and durability | Implemented and tested | Numbered transactional outbox migration, idempotence and concurrent initialization tests; restart persistence in original store tests; SQLite WAL application storage |
| Retention and pending links | Implemented and tested | Both comparison versions retained for undelivered notifications; deletion cascade; fixed 512MB payload budget |
| Deployment restore procedure | Implemented but not fully verified | Consistent backup script and documented restore; server recovery drill outstanding |
| Accessibility | Partially implemented | Labelled controls, focus, keyboard picker alternative, native dialog, responsive checks. No comprehensive assistive-technology audit |
| Bonuses | Not implemented | Daily digest, AI, extension, RSS and charts intentionally deferred |

## Remaining limitations

1. **Deployed isolation is unverified.** Compose syntax validation cannot prove Linux
   firewall, namespaces or Chromium sandbox behavior. Run the supplied isolation
   gate on the approved host before public launch. Do not disable the sandbox.
2. **External notification delivery is unverified.** Configure SMTP/Discord privately,
   enable a channel with authorization and observe a controlled event in the recipient.
3. **Compatibility with difficult webpages is limited.** Conservative robots behavior,
   top-level-only selection, 4000px visual coverage, tagged noise presets and heuristic
   challenge detection exclude some pages. Explicit selection and preview mitigate
   noise; they do not solve arbitrary page redesign or bot protection.

## Issues fixed during verification

- Corrected a fixture trailing-slash mismatch and explicit UTF-8 encoding.
- Added explicit accessible naming to the region element selector.
- Updated frontend build dependencies after audit advisories; audit then reported zero.
- Removed disabled-channel head-of-line blocking in notification dispatch.
- Preserved both ends of queued alert comparisons during retention cleanup.
- Serialized schema/WAL initialization with a file lock and transaction to fix the concurrent first-start race exposed by the regression test.

## Local configuration

Set the owner password using the local setup script. Keep SMTP/Discord credentials
in the ignored .env file. Hosting is optional; reviewers can run the application
and example captures using the README.
