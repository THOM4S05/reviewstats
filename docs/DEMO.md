# ReviewStats demo

The demo follows an order from mock POS ingestion through scan logging, simulated review submission and attribution. All examples use synthetic data.

## Order link

1. Open `/mock-pos` and create an order with a unique ID.
2. Open the order's QR URL in a browser or scan it with a phone. `/r/{token}` records a scan before redirecting to the local review form.
3. Submit a rating and optional comment. The server records a simulated review with a server-controlled timestamp, then recomputes matching.
4. Inspect `/` for the order/scan/review timeline and confidence, and `/reviews` for expandable metadata.
5. Open `/api/reviews/{review_id}/attribution` to inspect candidate scans and audit history.

The link validates the business and submission context. Attribution still depends on the timing evidence, so the demo does not force an exact match to the order whose link was opened.

## Permanent scanpoint

Create an assigned point at `/scanpoints`. Its `/s/{public_id}` URL can be encoded in both a QR code and an NFC tag; the app does not require NFC-specific hardware APIs.

A visit records the assignment active at that time. Mock POS data resolves the table/order context immediately or reconciles it later. Reassignment preserves the permanent URL and old assignment records. Disabling a point revokes the public scan and mock submission paths, including an already-opened form.

For a phone, set `PUBLIC_BASE_URL` to the computer's reachable LAN address and start Uvicorn with `--host 0.0.0.0`. Keep both devices on the same network. Physical NFC hardware and browser JavaScript remain manual checks; the automated suite exercises the HTTP flow through FastAPI's test client.

## Investigation and control scenarios

The following scenarios show how the app handles incomplete evidence and changing state:

- **Competing candidates:** record several scans close together, then submit a simulated review. Expand the review to inspect confidence, candidate count and runner-up gap. Its attribution API response includes each candidate's rank and whether it was selected.
- **Delayed order data:** visit an assigned permanent scanpoint before a compatible mock POS order is available. The dashboard counts scans awaiting POS data. Ingest an order with the same table context and compatible timestamps, then inspect the resolved scan. If a review already exists, re-run matching to update its attribution.
- **Changing assignments:** reassign a scanpoint to a different table and revisit its unchanged URL. Earlier scan records retain their original assignment context.
- **Revoked access:** open a simulated review form, disable its permanent scanpoint, then try submitting the form or revisiting the public link. Both paths reject the inactive point.
- **Decision history:** use the dashboard's Run matcher control, then inspect `/api/reviews/{review_id}/attribution`. The response separates the current result, ranked candidates and historical snapshots with timestamps and algorithm versions.
- **Dashboard drill-down:** expand an item or worker rating distribution to inspect the eligible review count and observed ratings. Worker summaries also show the adjustment and low-sample context.
- **Request diagnostics:** inspect the `X-Request-ID` response header and find the corresponding request log. `/health/live` checks that the handler responds; `/health/ready` checks a database query. These are basic health checks, not a full monitoring or alerting system.

## Example mock POS request

`POST /api/pos/orders` accepts a canonical order payload:

```json
{
  "provider": "MOCK",
  "external_location_id": "main",
  "external_order_id": "DEMO-001",
  "external_session_id": "DEMO-VISIT-001",
  "order_type": "DINE_IN",
  "table_number": "7",
  "staff_name": "Demo Staff",
  "ordered_at": "2026-10-06T12:00:00Z",
  "paid_at": "2026-10-06T12:30:00Z",
  "source_updated_at": "2026-10-06T12:30:01Z",
  "items": [{"name": "Burger", "quantity": 1, "price": "12.00"}]
}
```

Use current timestamps when trying the matching flow. Repeating a compatible payload exercises idempotent ingestion; an older `source_updated_at` does not replace newer order data. `/docs` provides interactive requests and the full schemas.

## Useful endpoints

| Endpoint | Purpose |
|---|---|
| `POST /api/orders` | Create a mock order; duplicate ID returns 409 |
| `POST /api/pos/orders` | Idempotent mock POS upsert and delayed reconciliation |
| `POST /api/scanpoints` | Create a permanent point |
| `POST /api/scanpoints/{id}/assign` | Change its table assignment with history |
| `POST /api/scanpoints/{id}/disable` | Revoke the point |
| `GET /s/{public_id}` | Record a scan and redirect |
| `POST /api/reviews/mock/customer` | Submit a simulated review and run matching |
| `POST /api/matching/run` | Recompute current attribution |
| `GET /api/reviews/{id}/attribution` | Inspect candidates, explanations and previous decisions |
| `GET /api/dashboard` | Inspect attribution and rating summaries |
| `GET /health/live`, `GET /health/ready` | Check process liveness and a database query |

Invalid input returns 422, unknown resources 404, conflicts or active unassigned points 409, and inactive or expired public links 410. Optional `REQUIRE_TENANT_AUTH=true` protects management JSON endpoints with `X-Tenant-Key`; the browser UI has no owner login.
