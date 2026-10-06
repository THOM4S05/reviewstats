import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    AttributionAudit,
    AttributionCandidate,
    GoogleReview,
    MatchStatus,
    ReviewMatch,
    ScanEvent,
)
from app.timeutils import as_utc

logger = logging.getLogger("reviewstats.matching")


@dataclass(frozen=True)
class Candidate:
    scan: ScanEvent
    delay_seconds: int


def _time_score(seconds: int, max_seconds: int) -> float:
    """Interpolate heuristic confidence; the configured window ends at 0.30.

    Keep only anchors strictly inside the window so short windows cannot create
    duplicate or decreasing x coordinates. These are policy scores, not calibrated
    probabilities. See docs/MATCHING.md for the complete scoring contract.
    """
    if max_seconds <= 0:
        raise ValueError("The matching window must be positive")
    if seconds < 0 or seconds > max_seconds:
        return 0.0
    anchors = [(0, 0.99), (120, 0.96), (300, 0.88), (600, 0.76), (1800, 0.55)]
    points = [point for point in anchors if point[0] < max_seconds] + [(max_seconds, 0.30)]
    for (left_s, left_score), (right_s, right_score) in zip(points, points[1:]):
        if seconds <= right_s:
            span = max(right_s - left_s, 1)
            return left_score + (right_score - left_score) * ((seconds - left_s) / span)
    return 0.0


def score_candidates(candidates: list[Candidate], max_seconds: int) -> tuple[float, MatchStatus, int | None]:
    """Score candidates sorted by increasing delay, then stable scan ID."""
    if not candidates:
        return 0.0, MatchStatus.UNMATCHED, None
    best = candidates[0]
    score = _time_score(best.delay_seconds, max_seconds)
    score -= min(0.12 * (len(candidates) - 1), 0.36)

    gap = None
    if len(candidates) > 1:
        gap = candidates[1].delay_seconds - best.delay_seconds
        if gap <= 30:
            score *= 0.70
        elif gap <= 120:
            score *= 0.82
        elif gap <= 300:
            score *= 0.92

    score = max(0.0, min(score, 0.99))
    if score >= 0.85:
        status = MatchStatus.HIGH_CONFIDENCE
    elif score >= 0.70:
        status = MatchStatus.PROBABLE
    else:
        status = MatchStatus.AMBIGUOUS
    return score, status, gap


def run_matching(db: Session, business_id: int, max_delay_minutes: int) -> list[ReviewMatch]:
    """Recompute timing attribution deterministically for all reviews of one business."""
    if max_delay_minutes <= 0:
        raise ValueError("The matching window must be positive")
    reviews = db.scalars(
        select(GoogleReview)
        .where(GoogleReview.business_id == business_id)
        .order_by(GoogleReview.google_create_time, GoogleReview.id)
    ).all()
    review_ids = [review.id for review in reviews]
    if reviews:
        db.execute(delete(AttributionCandidate).where(AttributionCandidate.google_review_id.in_(review_ids)))
        db.execute(delete(ReviewMatch).where(ReviewMatch.google_review_id.in_(review_ids)))
    db.flush()

    assigned_scan_ids: set[int] = set()
    results: list[ReviewMatch] = []
    window = timedelta(minutes=max_delay_minutes)
    max_seconds = int(window.total_seconds())
    scans = db.scalars(
        select(ScanEvent)
        .where(ScanEvent.business_id == business_id)
        .order_by(ScanEvent.scanned_at, ScanEvent.id)
    ).all()
    algorithm_version = get_settings().attribution_algorithm_version

    for review in reviews:
        review_time = as_utc(review.google_create_time)
        candidates = [
            Candidate(scan=scan, delay_seconds=int((review_time - as_utc(scan.scanned_at)).total_seconds()))
            for scan in scans
            if scan.id not in assigned_scan_ids
            and review_time - window <= as_utc(scan.scanned_at) <= review_time
        ]
        candidates.sort(key=lambda item: (item.delay_seconds, item.scan.id))
        confidence, status, gap = score_candidates(candidates, max_seconds)
        best = candidates[0] if candidates else None
        if best and best.scan.order_id is None:
            confidence = max(confidence - 0.15, 0.0)
            status = MatchStatus.PROBABLE if confidence >= 0.70 else MatchStatus.AMBIGUOUS
        explanation_data = {
            "algorithm": algorithm_version,
            "basis": "same business and scan occurred before review within configured window",
            "review_delay_seconds": best.delay_seconds if best else None,
            "candidate_count": len(candidates),
            "runner_up_gap_seconds": gap,
            "scanpoint_id": best.scan.scanpoint_id if best else None,
            "table_session_id": best.scan.table_session_id if best else None,
            "order_linked": bool(best and best.scan.order_id),
            "limitations": "Google does not provide a scanpoint or order identifier; this is probabilistic.",
        }
        explanation = json.dumps(explanation_data, sort_keys=True)
        for rank, candidate in enumerate(candidates, start=1):
            individual_score = _time_score(candidate.delay_seconds, max_seconds)
            db.add(
                AttributionCandidate(
                    google_review_id=review.id,
                    scan_event_id=candidate.scan.id,
                    order_id=candidate.scan.order_id,
                    score=Decimal(str(round(individual_score, 4))),
                    rank=rank,
                    selected=bool(best and candidate.scan.id == best.scan.id),
                    evidence=json.dumps(
                        {
                            "delay_seconds": candidate.delay_seconds,
                            "scanpoint_id": candidate.scan.scanpoint_id,
                            "assignment_id": candidate.scan.assignment_id,
                            "table_session_id": candidate.scan.table_session_id,
                            "order_id": candidate.scan.order_id,
                        },
                        sort_keys=True,
                    ),
                )
            )
        match = ReviewMatch(
            google_review_id=review.id,
            scan_event_id=best.scan.id if best else None,
            order_id=best.scan.order_id if best else None,
            confidence_score=Decimal(str(round(confidence, 4))),
            time_difference_seconds=best.delay_seconds if best else None,
            candidate_count=len(candidates),
            second_best_gap_seconds=gap,
            match_status=status,
            algorithm_version=algorithm_version,
            explanation=explanation,
        )
        if best:
            assigned_scan_ids.add(best.scan.id)
        db.add(match)
        db.add(
            AttributionAudit(
                google_review_id=review.id,
                scan_event_id=best.scan.id if best else None,
                order_id=best.scan.order_id if best else None,
                confidence_score=Decimal(str(round(confidence, 4))),
                match_status=status,
                algorithm_version=algorithm_version,
                explanation=explanation,
            )
        )
        results.append(match)

    db.commit()
    logger.info("matching_completed business_id=%s reviews=%s window_minutes=%s algorithm=%s",
                business_id, len(results), max_delay_minutes, algorithm_version)
    return results
