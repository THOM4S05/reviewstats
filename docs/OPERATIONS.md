# Running and diagnosing the prototype

Use the README commands from the repository root. `requirements-lock.txt` pins the verified dependency versions, while `pyproject.toml` defines package requirements and includes templates/static assets in built wheels. Updating versions requires rerunning the complete suite and the migration test.

## Checks

- `/health/live`: confirms the handler can respond.
- `/health/ready`: checks that the database can query the businesses table; returns 503 on failure. It does not prove migration revision, every table's health, provider availability or attribution correctness.
- `/docs`: OpenAPI contracts and request validation.
- `/api/reviews/{id}/attribution`: current score, ranked candidate base scores and prior snapshots.
- `python -m alembic current` and `python -m alembic check`: migration revision and model/schema drift.

Launch with `--no-access-log --log-level info`. The request logger emits route templates such as `/s/{public_id}`, generated request ID, method, status and elapsed milliseconds. It deliberately avoids raw paths, bodies, query strings, credentials and customer text. `X-Request-ID` lets you correlate a response with its log. The application enables INFO for its own reviewstats logger while keeping third-party logs at their existing levels. It supplies a basic console handler only if the host has not configured logging.

SQLite/model conflicts produce a generic 409 without exposing SQL parameters. Readiness failures log exception type. Matching completion logs business ID, review count, window and version. Provider HTTP failures return bounded 502 messages. Unexpected exceptions use the server's normal error reporting; exception traces may contain details, so keep local debugging logs private.

## Common issues

| Symptom | Investigation |
|---|---|
| Phone cannot open QR | Check LAN reachability, `PUBLIC_BASE_URL`, local firewall and `--host 0.0.0.0`; localhost on a phone refers to that phone |
| Blank dashboard | Create a mock order, visit its URL and submit a simulated review; a fresh DB contains no sample orders |
| 410 from a public link | Point is inactive or per-order token expired |
| 409 from an active point | It has no assignment at the current time |
| Scan awaiting POS | Ingest a compatible mock table order whose times encompass the scan/grace interval |
| Review has no match | Check business, review/scan ordering, window and whether scans were already selected for earlier reviews |
| Missing tables/columns | Stop the app, confirm DATABASE_URL and run `python -m alembic upgrade head` |
| 401 from JSON tools | Optional tenant API-key protection is enabled; supply `X-Tenant-Key`. Browser UI does not manage keys |
| Database locked | Stop competing writers and check transactions; the busy timeout is not a concurrency guarantee |

The verified environment emits one Starlette deprecation warning for the existing httpx TestClient transport. It does not fail tests. Adopting the alternative transport should be a deliberate dependency change, followed by full verification.

## Publication versus deployment

The source package can be published after reviewing the file list. Running it publicly requires further work: owner authentication, tenant-scoped HTML routes, rate limits, secure secret storage, retention/backups and concurrency handling. Optional API keys protect JSON routes only. The Docker binding defaults to localhost.

Docker configuration was inspected but could not be executed during preparation. Manually run `docker compose up --build`, check `docker compose ps`, complete the mock flow, then stop/restart to verify persisted data. GitHub Actions has not run until this repository is pushed; review both Python matrix results before displaying a passing CI badge.
