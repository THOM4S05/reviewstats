from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import GoogleReview, MatchStatus, Order, ScanEvent
from app.timeutils import as_utc

ITEM_PRIOR = Decimal("5")
WORKER_PRIOR = Decimal("5")


@dataclass(frozen=True)
class RatingSummaryRow:
    name: str
    average_rating: Decimal
    eligible_review_count: int
    rating_counts: dict[int, int]


@dataclass(frozen=True)
class WorkerRatingSummaryRow:
    name: str
    average_rating: Decimal
    rebalanced_rating: Decimal
    rating_adjustment: Decimal
    eligible_review_count: int
    reliability: Decimal
    rating_counts: dict[int, int]


@dataclass(frozen=True)
class EligibleContribution:
    review: GoogleReview
    order: Order
    item_names: tuple[str, ...]
    worker_name: str | None


@dataclass(frozen=True)
class ReviewEvidence:
    review: GoogleReview
    candidate_order_ids: frozenset[int]
    has_unresolved_scan: bool = False


@dataclass(frozen=True)
class RatingSummaries:
    items: list[RatingSummaryRow]
    workers: list[WorkerRatingSummaryRow]


def _clean_name(value: str) -> str:
    return " ".join(value.strip().split())


def _make_contribution(review: GoogleReview, order: Order) -> EligibleContribution:
    distinct_items: dict[str, str] = {}
    for item in order.items:
        clean_name = _clean_name(item.name)
        if clean_name:
            distinct_items.setdefault(clean_name.casefold(), clean_name)
    worker_name = _clean_name(order.staff_name) if order.staff_name else None
    return EligibleContribution(
        review=review,
        order=order,
        item_names=tuple(distinct_items.values()),
        worker_name=worker_name or None,
    )


def _candidate_evidence(
    reviews: list[GoogleReview], scans: list[ScanEvent], max_delay_minutes: int
) -> dict[int, ReviewEvidence]:
    """Build the complete timing-window candidate set for every review.

    A candidate order is any same-business order having at least one scan in the
    inclusive interval [review create time - matching window, review create time].
    Multiple scans for one order collapse to one candidate order. Unlike the greedy
    matcher, this evidence graph does not remove scans selected for earlier reviews.
    """
    window = timedelta(minutes=max_delay_minutes)
    evidence: dict[int, ReviewEvidence] = {}
    for review in reviews:
        review_time = as_utc(review.google_create_time)
        candidates = [scan for scan in scans if review_time - window <= as_utc(scan.scanned_at) <= review_time]
        candidate_orders = frozenset(scan.order_id for scan in candidates if scan.order_id is not None)
        evidence[review.id] = ReviewEvidence(
            review, candidate_orders, any(scan.order_id is None for scan in candidates)
        )
    return evidence


def _connected_components(
    evidence: dict[int, ReviewEvidence],
) -> list[tuple[set[int], set[int]]]:
    """Return complete connected components of the review↔candidate-order graph."""
    order_to_reviews: dict[int, set[int]] = defaultdict(set)
    for review_id, item in evidence.items():
        for order_id in item.candidate_order_ids:
            order_to_reviews[order_id].add(review_id)

    components: list[tuple[set[int], set[int]]] = []
    unseen = {review_id for review_id, item in evidence.items() if item.candidate_order_ids}
    while unseen:
        root = min(unseen)
        review_ids: set[int] = set()
        order_ids: set[int] = set()
        queue: deque[tuple[str, int]] = deque([("review", root)])
        while queue:
            kind, node_id = queue.popleft()
            if kind == "review":
                if node_id in review_ids:
                    continue
                review_ids.add(node_id)
                unseen.discard(node_id)
                queue.extend(("order", oid) for oid in evidence[node_id].candidate_order_ids)
            else:
                if node_id in order_ids:
                    continue
                order_ids.add(node_id)
                queue.extend(("review", rid) for rid in order_to_reviews[node_id])
        components.append((review_ids, order_ids))
    return components


def _perfect_assignment(
    review_ids: set[int],
    evidence: dict[int, ReviewEvidence],
    forbidden_edge: tuple[int, int] | None = None,
) -> dict[int, int] | None:
    """Find one deterministic review→order perfect matching, if it exists."""
    order_to_review: dict[int, int] = {}

    def assign(review_id: int, visited_orders: set[int]) -> bool:
        for order_id in sorted(evidence[review_id].candidate_order_ids):
            if forbidden_edge == (review_id, order_id) or order_id in visited_orders:
                continue
            visited_orders.add(order_id)
            current = order_to_review.get(order_id)
            if current is None or assign(current, visited_orders):
                order_to_review[order_id] = review_id
                return True
        return False

    for review_id in sorted(review_ids):
        if not assign(review_id, set()):
            return None
    return {review_id: order_id for order_id, review_id in order_to_review.items()}


def _swap_safe_assignment(
    review_ids: set[int],
    order_ids: set[int],
    evidence: dict[int, ReviewEvidence],
) -> dict[int, int] | None:
    """Prove that one complete connected component is safely interchangeable.

    Safety requires at least two reviews and two orders, equal cardinality, a current
    ReviewMatch for every review, at least one non-high-confidence review, identical
    ratings, and at least two distinct perfect assignments. The last condition proves
    genuine swap uncertainty rather than admitting an incomplete or uniquely forced
    low-confidence result.
    """
    if len(review_ids) < 2 or len(order_ids) < 2 or len(review_ids) != len(order_ids):
        return None
    reviews = [evidence[review_id].review for review_id in review_ids]
    if any(evidence[review_id].has_unresolved_scan for review_id in review_ids):
        # Missing POS data cannot prove a complete review/order ambiguity group.
        return None
    if any(review.match is None for review in reviews):
        return None
    if all(review.match.match_status == MatchStatus.HIGH_CONFIDENCE for review in reviews):
        return None
    if len({review.rating for review in reviews}) != 1:
        return None
    if any(
        review.match.order_id is not None
        and review.match.order_id not in evidence[review.id].candidate_order_ids
        for review in reviews
    ):
        return None

    assignment = _perfect_assignment(review_ids, evidence)
    if assignment is None or set(assignment.values()) != order_ids:
        return None
    has_alternative = any(
        _perfect_assignment(review_ids, evidence, (review_id, order_id)) is not None
        for review_id, order_id in assignment.items()
    )
    return assignment if has_alternative else None


def _eligible_contributions(
    evidence: dict[int, ReviewEvidence], orders: dict[int, Order]
) -> list[EligibleContribution]:
    safe_assignments: dict[int, int] = {}
    for review_ids, order_ids in _connected_components(evidence):
        assignment = _swap_safe_assignment(review_ids, order_ids, evidence)
        if assignment is not None:
            safe_assignments.update(assignment)

    contributions: list[EligibleContribution] = []
    used_review_ids: set[int] = set()
    for review_id, order_id in sorted(safe_assignments.items()):
        if order_id in orders and review_id not in used_review_ids:
            contributions.append(_make_contribution(evidence[review_id].review, orders[order_id]))
            used_review_ids.add(review_id)

    for review_id in sorted(evidence):
        if review_id in used_review_ids:
            continue
        item = evidence[review_id]
        match = item.review.match
        if (
            match is not None
            and match.match_status == MatchStatus.HIGH_CONFIDENCE
            and match.order_id in item.candidate_order_ids
            and match.order_id in orders
        ):
            contributions.append(_make_contribution(item.review, orders[match.order_id]))
            used_review_ids.add(review_id)
    return contributions


def _make_rating_row(name: str, ratings: list[int]) -> RatingSummaryRow:
    if any(rating not in range(1, 6) for rating in ratings):
        raise ValueError("Eligible ratings must be integers from 1 through 5")
    rating_counts = {rating: ratings.count(rating) for rating in range(1, 6)}
    assert sum(rating_counts.values()) == len(ratings)
    average = (Decimal(sum(ratings)) / Decimal(len(ratings))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return RatingSummaryRow(
        name=name,
        average_rating=average,
        eligible_review_count=len(ratings),
        rating_counts=rating_counts,
    )


def _aggregate(values: list[tuple[str, int]]) -> list[RatingSummaryRow]:
    grouped: dict[str, dict[str, object]] = {}
    for raw_name, rating in values:
        clean_name = _clean_name(raw_name)
        if not clean_name:
            continue
        key = clean_name.casefold()
        group = grouped.setdefault(key, {"name": clean_name, "ratings": []})
        ratings = group["ratings"]
        assert isinstance(ratings, list)
        ratings.append(rating)

    rows = []
    for group in grouped.values():
        ratings = group["ratings"]
        assert isinstance(ratings, list)
        rows.append(_make_rating_row(str(group["name"]), ratings))
    return sorted(
        rows,
        key=lambda row: (-row.average_rating, -row.eligible_review_count, row.name.casefold()),
    )


def _clamp_rating(value: Decimal) -> Decimal:
    return max(Decimal("1"), min(Decimal("5"), value))


def _make_worker_rating_row(
    name: str,
    raw_ratings: list[int],
    residuals: list[Decimal],
    global_mean: Decimal,
) -> WorkerRatingSummaryRow:
    raw_row = _make_rating_row(name, raw_ratings)
    count = Decimal(raw_row.eligible_review_count)
    reliability_full = count / (count + WORKER_PRIOR)
    mean_residual = sum(residuals, Decimal("0")) / count
    rebalanced = _clamp_rating(global_mean + reliability_full * mean_residual).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    adjustment = (rebalanced - raw_row.average_rating).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return WorkerRatingSummaryRow(
        name=raw_row.name,
        average_rating=raw_row.average_rating,
        rebalanced_rating=rebalanced,
        rating_adjustment=adjustment,
        eligible_review_count=raw_row.eligible_review_count,
        reliability=reliability_full.quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        ),
        rating_counts=raw_row.rating_counts,
    )


def _build_worker_summaries(
    contributions: list[EligibleContribution], global_mean: Decimal
) -> list[WorkerRatingSummaryRow]:
    """Calculate raw and item-mix-rebalanced worker ratings from one evidence set."""
    item_histories: dict[str, list[tuple[int, Decimal]]] = defaultdict(list)
    for contribution in contributions:
        rating = Decimal(contribution.review.rating)
        for item_name in contribution.item_names:
            item_histories[item_name.casefold()].append((contribution.review.id, rating))

    grouped: dict[str, dict[str, object]] = {}
    for contribution in contributions:
        if not contribution.worker_name:
            continue
        rating = Decimal(contribution.review.rating)
        baselines: list[Decimal] = []
        for item_name in contribution.item_names:
            other_ratings = [
                item_rating
                for review_id, item_rating in item_histories[item_name.casefold()]
                if review_id != contribution.review.id
            ]
            baseline = (
                sum(other_ratings, Decimal("0")) + ITEM_PRIOR * global_mean
            ) / (Decimal(len(other_ratings)) + ITEM_PRIOR)
            baselines.append(_clamp_rating(baseline))
        expected_rating = (
            sum(baselines, Decimal("0")) / Decimal(len(baselines))
            if baselines
            else global_mean
        )
        residual = rating - expected_rating

        key = contribution.worker_name.casefold()
        group = grouped.setdefault(
            key,
            {"name": contribution.worker_name, "ratings": [], "residuals": []},
        )
        raw_ratings = group["ratings"]
        residuals = group["residuals"]
        assert isinstance(raw_ratings, list) and isinstance(residuals, list)
        raw_ratings.append(contribution.review.rating)
        residuals.append(residual)

    rows: list[WorkerRatingSummaryRow] = []
    for group in grouped.values():
        raw_ratings = group["ratings"]
        residuals = group["residuals"]
        assert isinstance(raw_ratings, list) and isinstance(residuals, list)
        rows.append(
            _make_worker_rating_row(
                str(group["name"]), raw_ratings, residuals, global_mean
            )
        )
    return sorted(
        rows,
        key=lambda row: (-row.average_rating, -row.eligible_review_count, row.name.casefold()),
    )


def build_rating_summaries(
    db: Session, business_id: int, max_delay_minutes: int
) -> RatingSummaries:
    """Recompute evidence-aware item and worker ratings without persisted aggregates."""
    reviews = list(
        db.scalars(
            select(GoogleReview)
            .options(joinedload(GoogleReview.match))
            .where(GoogleReview.business_id == business_id)
            .order_by(GoogleReview.google_create_time, GoogleReview.id)
        ).unique()
    )
    orders = list(
        db.scalars(
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.business_id == business_id)
            .order_by(Order.id)
        )
    )
    scans = list(
        db.scalars(
            select(ScanEvent)
            .where(ScanEvent.business_id == business_id)
            .order_by(ScanEvent.scanned_at, ScanEvent.id)
        )
    )
    order_by_id = {order.id: order for order in orders}
    evidence = _candidate_evidence(reviews, scans, max_delay_minutes)
    contributions = _eligible_contributions(evidence, order_by_id)

    if not contributions:
        return RatingSummaries(items=[], workers=[])

    global_mean = sum(
        (Decimal(contribution.review.rating) for contribution in contributions), Decimal("0")
    ) / Decimal(len(contributions))
    item_values = [
        (item_name, contribution.review.rating)
        for contribution in contributions
        for item_name in contribution.item_names
    ]
    return RatingSummaries(
        items=_aggregate(item_values),
        workers=_build_worker_summaries(contributions, global_mean),
    )
