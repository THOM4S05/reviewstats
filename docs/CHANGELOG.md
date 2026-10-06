# Changelog

## 6 October 2026

The existing mock POS, persistent QR/NFC, simulated review and owner analytics flows remain the basis of the application. This update adds reliability fixes, diagnostics and reproducible setup.

- Corrected scoring for short matching windows and made review/scan tie-breaking deterministic. Attribution policy version: `v2.1-scanpoint`.
- Added input validation for blank identifiers, payment chronology and monetary limits; enabled SQLite foreign keys.
- Centralised public-link validation so disabling a point also revokes an already-opened review form.
- Corrected ambiguity-group handling when scan evidence has no resolved order.
- Added request IDs, route-template logs, liveness/readiness endpoints and typed scan responses.
- Aligned model enum lengths with the existing migration schema.
- Added pinned dependency constraints, packaged UI assets, a non-root SQLite Docker configuration and a GitHub Actions Python test matrix.
- Expanded regression coverage from 28 to 50 locally passing tests, retaining the original test files. Added coverage includes migration drift, link revocation, isolation, validation, logging and readiness failure.
- Verified a local server flow including QR generation, scan logging, simulated submission, attribution and persistence across restart. Docker execution, hosted CI and physical device checks remain unverified.
- Documented the data model, matching policy, local setup and investigation scenarios.
