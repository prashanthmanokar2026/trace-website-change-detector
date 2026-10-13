# Five-minute demonstration

## Before the interview

Start Trace using the README. Generate the three fixture monitors with `scripts/demo.py`.
They contain real browser captures of explicit examples. Keep the full test result
and this source tree available. Configure a private owner password locally.

## 0:00–0:45 — Show the purpose

Open the dashboard. “Trace watches public webpages and preserves evidence of text
changes. The public demo is read-only; these examples are controlled pages rendered
by Chromium, not live scholarship announcements.”

## 0:45–1:45 — Explain a change

Open Meridian scholarship. Show the text diff: eligibility and grant amount change.
Switch to side-by-side screenshots, then visual highlights. Explain that coral
shows changed pixels and can also show layout shifts. Select the baseline in history.

## 1:45–2:45 — Show filtering and selection

Sign in. Add a permitted public page such as `https://example.com/`. Wait for its
first successful capture, open Regions & settings and choose a real DOM element.
Use the keyboard element list or click the screenshot. Add a watched region, preview
text and match counts, then save. Explain that changing filters resets the baseline.
Network/robots restrictions can block arbitrary sites; use the prepared examples
and browser integration tests if connectivity is unavailable during the interview.

## 2:45–3:30 — Prove reliability

Show Check log and pause/resume. Explain separate check, version and alert records.
Run `tests/test_transport.py` and show that a 500, CAPTCHA-like page and forbidden
redirect do not become normal successful captures. Show `test_200_subscriptions_share_one_real_render`:
200 compatible subscriptions, one actual fixture page request.

## 3:30–4:15 — Notifications and honesty

Open Notifications. Show configured/enabled state and delivery history. If provider
credentials are not configured, say so. A local adapter test does not prove inbox
delivery. Explain “uncertain”: a provider might have accepted a message before its
acknowledgement was lost, so automatic replay risks a duplicate.

## 4:15–5:00 — Explain the design and limitations

React renders the UI. FastAPI validates requests. SQLite stores state and jobs.
A separate worker performs browser work, and a restricted proxy controls network
connections. The public deployment additionally requires verified container egress
isolation. State the limitations: text triggers, 4000px screenshot cap, top-level DOM
picker, heuristic challenge detection and single-host scale.

# Short answers to the four reviewer questions

**Is a CAPTCHA or outage a change?**
HTTP failures and known challenge signals are check failures. The last successful
baseline remains. A generic HTTP-200 outage without detectable signals is a known
classification limitation, not something we claim to solve universally.

**If 200 users watch a URL, is it fetched 200 times?**
The worker groups concurrently due compatible URL/render profiles. One capture feeds
multiple subscriptions; filters run separately. Different schedules can require new
fetches. The application currently has one owner; the test proves shared fetching,
not authentication or capacity for 200 production users.

**How do you stop endless alerts?**
Normalize whitespace, remove selected noise, compare hashes, then evaluate sensitivity
against the last significant state. Save small changes without alerting. Outbox keys
prevent duplicate event/channel records. Events are spaced ten minutes apart and kept;
unstable pages prompt the user to narrow the selection. No universal noise classifier.

**How do you avoid hammering websites?**
Minimum 15-minute intervals, one browser worker, shared fetches, domain spacing,
bounded requests/bytes/time, robots policy, backoff and Retry-After. Manual checks
use the same queue. Access blocks are not aggressively retried.

# Concepts to understand

- **Hash:** a deterministic fingerprint; it detects equality, not importance.
- **Transaction:** a group of writes that commit together or roll back together.
- **Lease:** a temporary claim on a job; another attempt can recover after expiry.
- **Outbox:** pending messages stored with the event, so a crash cannot lose the
  event-to-message handoff.
- **SSRF:** a submitted URL tricks the server into reaching an internal destination.
  Validate the address actually connected to; checking a hostname once is insufficient.
- **CSS selector:** an address for a DOM element. It can break when a page is redesigned.
