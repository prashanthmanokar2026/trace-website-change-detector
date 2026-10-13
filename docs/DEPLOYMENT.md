# One-host deployment and security gate

## Status

**Prepared, not deployed or Linux-runtime verified.** Docker is not installed in the
implementation environment. Do not describe this configuration as production tested.
The native API, worker, browser capture, proxy and UI have been run on macOS.

## Optional future deployment

The current submission requires only a public GitHub repository. Hosting is outside
the submission scope; no paid resource, account or domain has been provisioned.
The application runs locally without a hosting subscription.

These files describe an optional future Linux deployment on a persistent host with
Docker Engine and Compose. They are not a promise of free hosting or a tested hosted
installation. Validate resources and all isolation gates before exposing the app.

## Why the containers are justified

One codebase and one database run on one host. Separate processes/containers exist
to enforce boundaries, not to simulate a distributed architecture:

- `worker` has only the internal `browser` network and no notification/owner secrets.
- `proxy` has browser + outbound networks, validates DNS answers and opens sockets
  to the validated numeric IP. It is not published on a host port.
- `api` has only the internal frontend network and the shared database volume.
- `notifier` has outbound access and server-only provider credentials.
- `caddy` alone publishes ports 80/443 and obtains HTTPS certificates.

The API/worker/notifier share SQLite through the same local named volume. This is
not valid for separate machines or network filesystems. All containers have memory
limits; worker has CPU/PID limits, non-root execution and Chromium sandbox enabled.
The supplied Playwright seccomp profile permits required namespace operations.

The internal network prevents ordinary direct browser egress; the proxy validates
redirects when new connections are made. The Chromium route guard is an additional
layer, not the sole SSRF boundary. Never publish port 8899 or disable the sandbox
because a host rejects user namespaces. Resolve host compatibility or do not deploy.

References:
- https://docs.docker.com/reference/compose-file/networks/#internal
- https://playwright.dev/python/docs/docker

## Deployment sequence, after authorization

1. Create the server, install Docker/Compose using official Ubuntu instructions,
   and restrict inbound access to SSH from the owner's address plus HTTP/HTTPS.
   Point an owned domain's A record at the server.
2. Copy the reviewed source. Exclude `.venv`, `.env`, `data`, node_modules and private
   screenshots. Create `.env` from `.env.example` directly on the host.
3. Set `TRACE_DOMAIN` to the real hostname and `TRACE_BASE_URL` to its HTTPS origin.
   Generate `TRACE_OWNER_HASH` locally with `scripts/set_password.py`, or on the
   server using the container (do not expose the resulting hash in chat).
4. Supply SMTP/Discord secrets directly if authorized. Keep `.env` permissions 600.
5. Build and start:

```sh
docker compose config --quiet
docker compose build
docker compose up -d
```

Generate the owner hash on a trusted Python 3.12 machine with the password script
before copying the reviewed `.env` to the server. The Compose configuration refuses
to start with an empty owner hash. This avoids temporarily exposing an unconfigured
owner service or putting a plaintext password in command arguments.

6. Run the required isolation check:

```sh
docker compose exec worker python deploy/verify_isolation.py
```

It must prove direct connections fail, private proxy destinations fail, and a public
sandboxed browser capture succeeds. A failure blocks public use. Also test private
redirects and subresources on the deployed host; inspect firewall/network rules.
7. Generate the public example captures explicitly:

```sh
docker compose exec worker python scripts/demo.py
```

Do this before adding owner monitors. The fixture generator launches its own test
browser and intercepts fixture requests; it is not an API-accessible mode.
8. Open HTTPS, verify anonymous demo access and denied private artifacts, sign in,
   create a permitted public monitor, observe scheduled capture and restart recovery.
9. Enable configured notification channels only after authorization; produce a
   controlled change and verify both external delivery and the HTTPS comparison link.
10. Record the deployed URL, observed commands/results and remaining issues in AUDIT.

## Operations

```sh
docker compose ps
docker compose logs --tail=100 worker
docker compose restart worker
```

The API exposes `/api/health` with API and recent worker-heartbeat status. Container
restart policies restart exited processes; unhealthy status itself does not cause
Docker to restart a hung process. Investigate an unhealthy worker and restart it.
Capture-level timeouts and leases provide normal recovery.

Use SQLite's backup API via `scripts/backup.py` to a private mounted destination;
copy backups off-host through an authorized secure channel. Retain the named
`trace_data` volume across deploys. **Never use `docker compose down -v` on a live
instance unless intentionally deleting all persisted data.**

Restore with all app containers stopped: archive the current volume, restore a
consistent backup as `trace.sqlite`, remove stale WAL files only from the fresh
restore destination, invalidate sessions, then start and verify.

## Explicit remaining gate

The deployment has not been provisioned. Compose build, Linux namespace/sandbox
behavior, direct-egress denial, HTTPS and public-host recovery need verification on
the chosen server. This is a deployment blocker, not a passing test.
