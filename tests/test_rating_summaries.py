from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.database import SessionLocal
from app.models import (
    Business,
    GoogleReview,
    MatchStatus,
    Order,
    OrderItem,
    OrderType,
    ReviewMatch,
    ReviewToken,
    ScanEvent,
)
from app.services.matching import run_matching
from app.services.rating_summaries import (
    ITEM_PRIOR,
    WORKER_PRIOR,
    _make_worker_rating_row,
    build_rating_summaries,
)


def add_order(db, business, external_id, scanned_at, staff, items):
    order = Order(
        external_order_id=external_id,
        business_id=business.id,
        order_type=OrderType.TAKEAWAY,
        staff_name=staff,
        total=Decimal("10.00"),
        ordered_at=scanned_at,
        items=[
            OrderItem(name=name, quantity=quantity, price=Decimal("1.00"))
            for name, quantity in items
        ],
    )
    order.review_token = ReviewToken(token=f"rating-token-{business.id}-{external_id}-secure-value")
    db.add(order)
    db.flush()
    scan = ScanEvent(
        review_token_id=order.review_token.id,
        order_id=order.id,
        business_id=business.id,
        scanned_at=scanned_at,
        redirected_at=scanned_at,
    )
    db.add(scan)
    db.flush()
    return order, scan


def add_review_with_match(
    db,
    business,
    review_id,
    created_at,
    rating,
    status,
    order=None,
    scan=None,
):
    review = GoogleReview(
        business_id=business.id,
        google_review_id=review_id,
        rating=rating,
        comment="Evidence test",
        google_create_time=created_at,
        google_update_time=created_at,
        retrieved_at=created_at,
    )
    db.add(review)
    db.flush()
    match = ReviewMatch(
        google_review_id=review.id,
        scan_event_id=scan.id if scan else None,
        order_id=order.id if order else None,
        confidence_score=Decimal("0.9000") if status == MatchStatus.HIGH_CONFIDENCE else Decimal("0.5000"),
        time_difference_seconds=int((created_at - scan.scanned_at).total_seconds()) if scan else None,
        candidate_count=2 if status == MatchStatus.AMBIGUOUS else 1,
        match_status=status,
    )
    db.add(match)
    db.flush()
    return review


def by_name(rows):
    return {row.name.casefold(): row for row in rows}


def test_high_confidence_updates_worker_and_each_distinct_item_once(client):
    now = datetime.now(UTC)
    with SessionLocal() as db:
        business = db.query(Business).one()
        order, scan = add_order(
            db,
            business,
            "HIGH",
            now,
            " Emma ",
            [("Double Burger", 3), (" double burger ", 1), ("Fries", 2)],
        )
        add_review_with_match(
            db, business, "high-review", now + timedelta(seconds=60), 4,
            MatchStatus.HIGH_CONFIDENCE, order, scan,
        )
        db.commit()

        result = build_rating_summaries(db, business.id, 60)
        items = by_name(result.items)
        assert set(items) == {"double burger", "fries"}
        assert items["double burger"].eligible_review_count == 1
        assert items["double burger"].average_rating == Decimal("4.00")
        assert items["double burger"].rating_counts == {1: 0, 2: 0, 3: 0, 4: 1, 5: 0}
        assert items["fries"].eligible_review_count == 1
        assert [(row.name, row.average_rating, row.eligible_review_count) for row in result.workers] == [
            ("Emma", Decimal("4.00"), 1)
        ]


def test_single_ambiguous_and_incomplete_groups_are_excluded(client):
    now = datetime.now(UTC)
    with SessionLocal() as db:
        business = db.query(Business).one()
        order_a, scan_a = add_order(db, business, "A", now, "Ava", [("A", 1)])
        add_order(db, business, "B", now + timedelta(seconds=1), "Ben", [("B", 1)])
        add_review_with_match(
            db, business, "single", now + timedelta(seconds=30), 5,
            MatchStatus.AMBIGUOUS, order_a, scan_a,
        )
        db.commit()
        result = build_rating_summaries(db, business.id, 60)
        assert result.items == []
        assert result.workers == []

        order_c, scan_c = add_order(db, business, "C", now + timedelta(seconds=2), "Cam", [("C", 1)])
        add_review_with_match(
            db, business, "incomplete-2", now + timedelta(seconds=40), 5,
            MatchStatus.AMBIGUOUS, order_c, scan_c,
        )
        db.commit()
        # Two reviews connected to three candidate orders cannot provide one-to-one coverage.
        result = build_rating_summaries(db, business.id, 60)
        assert result.items == []
        assert result.workers == []


def test_two_swappable_reviews_with_same_rating_are_included_once_per_order(client):
    now = datetime.now(UTC)
    with SessionLocal() as db:
        business = db.query(Business).one()
        order_a, scan_a = add_order(db, business, "A", now, "Alice", [("Burger", 1)])
        order_b, scan_b = add_order(db, business, "B", now + timedelta(seconds=5), "Bob", [("Fries", 1)])
        add_review_with_match(db, business, "r1", now + timedelta(seconds=30), 4, MatchStatus.AMBIGUOUS, order_a, scan_a)
        add_review_with_match(db, business, "r2", now + timedelta(seconds=40), 4, MatchStatus.AMBIGUOUS, order_b, scan_b)
        db.commit()

        result = build_rating_summaries(db, business.id, 60)
        assert [(row.name, row.average_rating, row.eligible_review_count) for row in result.items] == [
            ("Burger", Decimal("4.00"), 1),
            ("Fries", Decimal("4.00"), 1),
        ]
        assert all(row.rating_counts == {1: 0, 2: 0, 3: 0, 4: 1, 5: 0} for row in result.items)
        assert sum(row.eligible_review_count for row in result.workers) == 2
        assert all(row.rebalanced_rating == Decimal("4.00") for row in result.workers)


def test_swappable_reviews_with_different_ratings_are_excluded(client):
    now = datetime.now(UTC)
    with SessionLocal() as db:
        business = db.query(Business).one()
        order_a, scan_a = add_order(db, business, "A", now, "Alice", [("Burger", 1)])
        order_b, scan_b = add_order(db, business, "B", now + timedelta(seconds=5), "Bob", [("Fries", 1)])
        add_review_with_match(db, business, "r1", now + timedelta(seconds=30), 5, MatchStatus.AMBIGUOUS, order_a, scan_a)
        add_review_with_match(db, business, "r2", now + timedelta(seconds=40), 3, MatchStatus.AMBIGUOUS, order_b, scan_b)
        db.commit()
        result = build_rating_summaries(db, business.id, 60)
        assert result.items == []
        assert result.workers == []


def _add_three_review_chain(db, business, now, ratings):
    order_a, scan_a = add_order(db, business, "A", now, "Alice", [("A item", 1)])
    order_b, scan_b = add_order(db, business, "B", now + timedelta(seconds=60), "Bob", [("B item", 1)])
    order_c, scan_c = add_order(db, business, "C", now + timedelta(seconds=120), "Cam", [("C item", 1)])
    # With a two-minute window: r1/r2 see A+B, while r3 sees B+C.
    add_review_with_match(db, business, "r1", now + timedelta(seconds=90), ratings[0], MatchStatus.AMBIGUOUS, order_a, scan_a)
    add_review_with_match(db, business, "r2", now + timedelta(seconds=100), ratings[1], MatchStatus.AMBIGUOUS, order_b, scan_b)
    add_review_with_match(db, business, "r3", now + timedelta(seconds=150), ratings[2], MatchStatus.AMBIGUOUS, order_c, scan_c)


def test_complete_three_review_chain_requires_every_rating_to_match(client):
    now = datetime.now(UTC)
    with SessionLocal() as db:
        business = db.query(Business).one()
        _add_three_review_chain(db, business, now, [5, 5, 5])
        db.commit()
        result = build_rating_summaries(db, business.id, 2)
        assert len(result.items) == 3
        assert sum(row.eligible_review_count for row in result.items) == 3

    # The fixture is reset per test; changing one rating makes the whole component unsafe.


def test_three_review_chain_with_one_different_rating_is_excluded(client):
    now = datetime.now(UTC)
    with SessionLocal() as db:
        business = db.query(Business).one()
        _add_three_review_chain(db, business, now, [5, 5, 4])
        db.commit()
        result = build_rating_summaries(db, business.id, 2)
        assert result.items == []
        assert result.workers == []


def test_normalization_blank_workers_rounding_and_sorting(client):
    now = datetime.now(UTC)
    with SessionLocal() as db:
        business = db.query(Business).one()
        specs = [
            ("N1", " Emma ", 5, [(" Fries ", 1), (" Burger ", 1), ("zebra", 1), ("Apple", 1)]),
            ("N2", "emma", 5, [("fries", 1), ("burger", 1)]),
            ("N3", "EMMA", 4, [("BURGER", 1)]),
            ("N4", "   ", 5, [("Blank worker item", 1)]),
        ]
        for index, (external_id, staff, rating, items) in enumerate(specs):
            scan_time = now + timedelta(hours=index * 2)
            order, scan = add_order(db, business, external_id, scan_time, staff, items)
            add_review_with_match(
                db, business, f"review-{index}", scan_time + timedelta(seconds=30), rating,
                MatchStatus.HIGH_CONFIDENCE, order, scan,
            )
        db.commit()

        result = build_rating_summaries(db, business.id, 60)
        assert [(row.name, row.average_rating, row.eligible_review_count) for row in result.items] == [
            ("Fries", Decimal("5.00"), 2),
            ("Apple", Decimal("5.00"), 1),
            ("Blank worker item", Decimal("5.00"), 1),
            ("zebra", Decimal("5.00"), 1),
            ("Burger", Decimal("4.67"), 3),
        ]
        assert [(row.name, row.average_rating, row.eligible_review_count) for row in result.workers] == [
            ("Emma", Decimal("4.67"), 3)
        ]
        assert by_name(result.items)["burger"].rating_counts == {1: 0, 2: 0, 3: 0, 4: 1, 5: 2}
        assert result.workers[0].rating_counts == {1: 0, 2: 0, 3: 0, 4: 1, 5: 2}
        assert sum(result.workers[0].rating_counts.values()) == result.workers[0].eligible_review_count


def test_results_are_isolated_by_business(client):
    now = datetime.now(UTC)
    with SessionLocal() as db:
        first = db.query(Business).one()
        second = Business(name="Other", google_review_url="https://example.com/other")
        db.add(second)
        db.flush()
        order, scan = add_order(db, second, "OTHER", now, "Other Worker", [("Other Item", 1)])
        add_review_with_match(
            db, second, "other-review", now + timedelta(seconds=20), 5,
            MatchStatus.HIGH_CONFIDENCE, order, scan,
        )
        db.commit()
        first_result = build_rating_summaries(db, first.id, 60)
        second_result = build_rating_summaries(db, second.id, 60)
        assert first_result.items == []
        assert [row.name for row in second_result.items] == ["Other Item"]
        assert second_result.items[0].rating_counts == {1: 0, 2: 0, 3: 0, 4: 0, 5: 1}


def test_rerunning_matching_does_not_duplicate_contributions(client):
    now = datetime.now(UTC)
    with SessionLocal() as db:
        business = db.query(Business).one()
        add_order(db, business, "RERUN", now, "Riley", [("Soup", 2)])
        review = GoogleReview(
            business_id=business.id,
            google_review_id="rerun-review",
            rating=5,
            google_create_time=now + timedelta(seconds=30),
            google_update_time=now + timedelta(seconds=30),
            retrieved_at=now + timedelta(seconds=30),
        )
        db.add(review)
        db.commit()

        run_matching(db, business.id, 60)
        first = build_rating_summaries(db, business.id, 60)
        run_matching(db, business.id, 60)
        second = build_rating_summaries(db, business.id, 60)
        assert first == second
        assert [(row.name, row.eligible_review_count) for row in second.items] == [("Soup", 1)]


def test_five_bin_distribution_uses_the_same_grouped_ratings(client):
    now = datetime.now(UTC)
    with SessionLocal() as db:
        business = db.query(Business).one()
        for index, rating in enumerate([5, 5, 4, 3]):
            scan_time = now + timedelta(hours=index * 2)
            items = [(" Burger ", index + 1), ("burger", 3)]
            if index == 0:
                items.append(("Side", 5))
            order, scan = add_order(db, business, f"DIST-{index}", scan_time, " Emma ", items)
            add_review_with_match(
                db,
                business,
                f"dist-review-{index}",
                scan_time + timedelta(seconds=30),
                rating,
                MatchStatus.HIGH_CONFIDENCE,
                order,
                scan,
            )
        db.commit()

        result = build_rating_summaries(db, business.id, 60)
        burger = by_name(result.items)["burger"]
        emma = by_name(result.workers)["emma"]
        side = by_name(result.items)["side"]
        expected = {1: 0, 2: 0, 3: 1, 4: 1, 5: 2}
        assert burger.average_rating == Decimal("4.25")
        assert burger.eligible_review_count == 4
        assert burger.rating_counts == expected
        assert emma.rating_counts == expected
        assert emma.average_rating == Decimal("4.25")
        assert side.rating_counts == {1: 0, 2: 0, 3: 0, 4: 0, 5: 1}
        assert sum(burger.rating_counts.values()) == burger.eligible_review_count


def test_low_and_high_item_mix_adjust_workers_in_opposite_directions(client):
    now = datetime.now(UTC)
    with SessionLocal() as db:
        business = db.query(Business).one()
        specs = [
            ("LOW-1", "Low baseline", 1, "Low item"),
            ("LOW-2", "Low baseline", 1, "Low item"),
            ("HIGH-1", "High baseline", 5, "High item"),
            ("HIGH-2", "High baseline", 5, "High item"),
            ("TARGET-LOW", "Target low", 3, "Low item"),
            ("TARGET-HIGH", "Target high", 3, "High item"),
        ]
        for index, (external_id, worker, rating, item) in enumerate(specs):
            scan_time = now + timedelta(hours=index * 2)
            order, scan = add_order(db, business, external_id, scan_time, worker, [(item, 1)])
            add_review_with_match(
                db, business, f"mix-{index}", scan_time + timedelta(seconds=30), rating,
                MatchStatus.HIGH_CONFIDENCE, order, scan,
            )
        db.commit()

        workers = by_name(build_rating_summaries(db, business.id, 60).workers)
        target_low = workers["target low"]
        target_high = workers["target high"]
        # μ is exactly 3. The current contribution is excluded, giving baselines
        # (1+1+5×3)/7 and (5+5+5×3)/7 respectively.
        assert ITEM_PRIOR == Decimal("5")
        assert target_low.average_rating == Decimal("3.00")
        assert target_low.rebalanced_rating == Decimal("3.10")
        assert target_low.rating_adjustment == Decimal("0.10")
        assert target_high.rebalanced_rating == Decimal("2.90")
        assert target_high.rating_adjustment == Decimal("-0.10")
        assert target_low.reliability == Decimal("0.1667")


def test_unseen_and_multiple_items_fall_back_and_weight_distinct_names_once(client):
    now = datetime.now(UTC)
    with SessionLocal() as db:
        business = db.query(Business).one()
        order, scan = add_order(
            db,
            business,
            "UNSEEN",
            now,
            "Solo",
            [(" New item ", 20), ("new item", 1)],
        )
        add_review_with_match(
            db, business, "unseen-review", now + timedelta(seconds=30), 4,
            MatchStatus.HIGH_CONFIDENCE, order, scan,
        )
        db.commit()
        result = build_rating_summaries(db, business.id, 60)
        assert result.workers[0].average_rating == Decimal("4.00")
        assert result.workers[0].rebalanced_rating == Decimal("4.00")
        assert result.workers[0].rating_adjustment == Decimal("0.00")
        assert result.items[0].eligible_review_count == 1


def test_multiple_items_use_mean_leave_one_out_baseline(client):
    now = datetime.now(UTC)
    with SessionLocal() as db:
        business = db.query(Business).one()
        specs = [
            ("LOW-1", "Base low", 1, [("Low", 1)]),
            ("LOW-2", "Base low", 1, [("Low", 1)]),
            ("HIGH-1", "Base high", 5, [("High", 1)]),
            ("HIGH-2", "Base high", 5, [("High", 1)]),
            ("MIX", "Mixed worker", 3, [("Low", 10), (" low ", 1), ("High", 99)]),
        ]
        for index, (external_id, worker, rating, items) in enumerate(specs):
            scan_time = now + timedelta(hours=index * 2)
            order, scan = add_order(db, business, external_id, scan_time, worker, items)
            add_review_with_match(
                db, business, f"multiple-{index}", scan_time + timedelta(seconds=30), rating,
                MatchStatus.HIGH_CONFIDENCE, order, scan,
            )
        db.commit()
        mixed = by_name(build_rating_summaries(db, business.id, 60).workers)["mixed worker"]
        # Symmetric low/high item baselines average to μ=3, so there is no effect.
        assert mixed.rebalanced_rating == Decimal("3.00")
        assert mixed.rating_adjustment == Decimal("0.00")


def test_worker_reliability_shrinkage_clamping_and_decimal_rounding():
    assert WORKER_PRIOR == Decimal("5")
    sparse = _make_worker_rating_row(
        "Sparse", [3], [Decimal("0.63")], Decimal("3")
    )
    substantial = _make_worker_rating_row(
        "Substantial", [3] * 10, [Decimal("0.63")] * 10, Decimal("3")
    )
    assert sparse.reliability == Decimal("0.1667")
    assert substantial.reliability == Decimal("0.6667")
    assert sparse.rebalanced_rating == Decimal("3.11")
    assert substantial.rebalanced_rating == Decimal("3.42")
    assert abs(sparse.rebalanced_rating - Decimal("3")) < abs(
        substantial.rebalanced_rating - Decimal("3")
    )

    upper = _make_worker_rating_row(
        "Upper", [5] * 10, [Decimal("4")] * 10, Decimal("4.5")
    )
    lower = _make_worker_rating_row(
        "Lower", [1] * 10, [Decimal("-4")] * 10, Decimal("1.5")
    )
    assert upper.rebalanced_rating == Decimal("5.00")
    assert lower.rebalanced_rating == Decimal("1.00")
