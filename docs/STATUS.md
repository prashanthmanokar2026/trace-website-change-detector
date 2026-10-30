# Project status

Updated 13 October 2026.

The source is published at [prashanthmanokar2026/trace-website-change-detector](https://github.com/prashanthmanokar2026/trace-website-change-detector).
The submission runs locally. There is no hosted service or paid infrastructure.

The interface, owner login, monitoring worker, region selection, version comparisons
and notification queue are implemented. The included examples contain six browser
captures across three fictional pages.

## Checked locally

- 48 tests and 3 subtests passed.
- TypeScript check and production frontend build passed.
- npm audit reported no known vulnerabilities at the time of the check.
- A public page was captured through the proxy with Chromium's sandbox enabled.
- Desktop and mobile interface flows were tested.
- SQLite backup integrity and schema version 2 were checked.

## Still untested

- Delivery to a real email inbox or Discord channel.
- Docker networking and browser isolation on a Linux host.
- A full server restore exercise and a comprehensive accessibility review.

These limits are described in the [testing notes](AUDIT.md). Follow the README to
set up an owner password and run the app locally.
