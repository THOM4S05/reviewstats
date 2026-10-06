# Explainable time-based attribution

## Inputs and candidate generation

Inputs are the business ID, configured window, review creation timestamps, scan timestamps, already-selected scan IDs, and whether each scan has a linked mock order. All times are compared in UTC; naive datetimes are interpreted as UTC for compatibility. Business scope is mandatory. Review text, rating and identity are not scoring inputs.

Reviews are processed by `(creation_time, internal_id)`. Candidate scans satisfy the inclusive time window, belong to the business, and have not been selected earlier in the run. The policy greedily ranks by integer delay in seconds, then scan ID. Subsecond delays can therefore tie. Once selected, a scan is reserved even if its result is ambiguous.

## Formula

Let `d` be the scan-to-review delay in seconds, `W` the configured window in seconds, and `n` the number of candidates. The time score `T(d)` is piecewise linear between these anchors:

| Delay | Score |
|---|---|
| 0 seconds | 0.99 |
| 120 seconds | 0.96 |
| 300 seconds | 0.88 |
| 600 seconds | 0.76 |
| 1800 seconds | 0.55 |
| W | 0.30 |

Only fixed anchors strictly below `W` are retained. The endpoint at `W` is always 0.30; for a one-minute window the curve runs directly from `(0, 0.99)` to `(60, 0.30)`. Scores outside the window are zero. This endpoint handling was corrected during portfolio preparation; default 60-minute scores retain the original values.

Competition penalty: `P = min(0.12 * (n - 1), 0.36)`.

For a runner-up, let `g = second_delay - best_delay`. The multiplier `M` is 0.70 if `g <= 30`, 0.82 if `g <= 120`, 0.92 if `g <= 300`, otherwise 1.00. A lone candidate also uses 1.00.

`C = clamp((T(best_delay) - P) * M, 0, 0.99)`.

With a linked order: HIGH_CONFIDENCE if `C >= 0.85`, PROBABLE if `C >= 0.70`, otherwise AMBIGUOUS. Without a linked order, subtract 0.15 (floor zero); HIGH_CONFIDENCE is disallowed. No eligible scans gives UNMATCHED with score zero and no selected scan.

Example: one linked scan 110 seconds before a review gives about 0.9625 and HIGH_CONFIDENCE. Two scans at delays 110 and 130 seconds give `(0.9625 - 0.12) * 0.70 = 0.58975`, an AMBIGUOUS result. These numbers describe the rule, not demonstrated correctness rates.

## Ranked evidence versus final confidence

Each stored candidate's `score` is its base time score. Candidate rank follows time proximity; `selected` identifies the top candidate. The current match's confidence additionally includes competition, gap and missing-order penalties. These two scores are intentionally different and should not be presented as equivalent probabilities.

Every matching run deletes/recreates current candidate and match rows for that business and appends one audit snapshot per review. Audits preserve historical policy output, not ground truth. The application exposes no audit update endpoint, but the SQLite schema does not enforce append-only storage against direct SQL modifications. Rows carry an algorithm version and a JSON explanation.

## QR/NFC and delayed data

A permanent scanpoint's active assignment maps it to a table/service area at scan time. Compatible mock orders must have opened by the scan, and the scan must fall no later than the payment/order anchor plus the configured grace period. The nearest anchor wins, with order ID as tie-breaker. A scan can remain unresolved until mock POS data arrives; reconciliation preserves its original scan time and assignment.

Delayed reconciliation changes the scan's linked order. Existing matches need recomputation to reflect that change. Customer simulated-review submission automatically runs matching; ordinary POS ingestion and provider import do not automatically recompute every match.

## Assumptions and limits

- Time proximity is suggestive evidence, not reviewer identification.
- Scores and thresholds are hand-selected policy values and have not been empirically calibrated.
- Greedy chronological allocation can differ from an optimal global assignment.
- Repeated scans create competing evidence; one scan per review does not guarantee one review per order.
- Cross-location candidate filtering is not implemented; candidates share a business, which may contain several locations.
- An absent scan, delayed/out-of-window review, or missing order can leave attribution weak or unmatched.
- The algorithm scans in-memory collections: roughly O(reviews * scans), plus sorting and database writes. It targets prototype volumes.
- No production throughput or physical NFC reliability measurement has been demonstrated.

## Analytics eligibility

`rating_summaries.py` constructs a separate complete review-to-candidate-order graph without removing scans chosen by the greedy matcher. It includes high-confidence contributions within the current window. It also admits a complete connected ambiguity group when there are equal numbers of reviews/orders, every review has a current match, ratings are identical, multiple perfect assignments exist, and no candidate scan remains unresolved. Otherwise the group is excluded.

Each eligible review contributes once to its worker and once to each distinct normalized item name; quantity does not increase weight. Worker adjustment uses item leave-one-out baselines and shrinkage with fixed priors of five. These are descriptive analytics; they do not establish staff causality or matching accuracy.
