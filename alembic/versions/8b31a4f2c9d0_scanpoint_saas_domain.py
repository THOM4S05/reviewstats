"""persistent scanpoints and production domain

Revision ID: 8b31a4f2c9d0
Revises: 33cc92df89e6
Create Date: 2026-08-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8b31a4f2c9d0"
down_revision: Union[str, None] = "33cc92df89e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"], unique=True)
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("display_name", sa.String(200)),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_table(
        "memberships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "user_id"),
    )
    op.create_index("ix_memberships_organization_id", "memberships", ["organization_id"])
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])
    with op.batch_alter_table("businesses") as batch:
        batch.add_column(sa.Column("organization_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("api_key_hash", sa.String(128), nullable=True))
        batch.create_foreign_key("fk_business_organization", "organizations", ["organization_id"], ["id"])
        batch.create_index("ix_businesses_organization_id", ["organization_id"])

    op.create_table(
        "business_locations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("external_ref", sa.String(100), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("google_review_url", sa.String(1000)),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("business_id", "external_ref"),
    )
    op.create_index("ix_business_locations_business_id", "business_locations", ["business_id"])
    op.create_table(
        "service_areas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
        sa.Column("location_id", sa.Integer(), sa.ForeignKey("business_locations.id"), nullable=False),
        sa.Column("external_ref", sa.String(100), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("location_id", "external_ref"),
    )
    op.create_index("ix_service_areas_business_id", "service_areas", ["business_id"])
    op.create_index("ix_service_areas_location_id", "service_areas", ["location_id"])
    op.create_table(
        "scanpoints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(128), nullable=False, unique=True),
        sa.Column("serial_number", sa.String(100), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
        sa.Column("location_id", sa.Integer(), sa.ForeignKey("business_locations.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("business_id", "serial_number"),
    )
    op.create_index("ix_scanpoints_public_id", "scanpoints", ["public_id"], unique=True)
    op.create_index("ix_scanpoints_business_id", "scanpoints", ["business_id"])
    op.create_index("ix_scanpoints_location_id", "scanpoints", ["location_id"])
    op.create_table(
        "scanpoint_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scanpoint_id", sa.Integer(), sa.ForeignKey("scanpoints.id"), nullable=False),
        sa.Column("service_area_id", sa.Integer(), sa.ForeignKey("service_areas.id"), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_scanpoint_assignments_scanpoint_id", "scanpoint_assignments", ["scanpoint_id"])
    op.create_index("ix_scanpoint_assignments_service_area_id", "scanpoint_assignments", ["service_area_id"])
    op.create_index("ix_assignment_scanpoint_time", "scanpoint_assignments", ["scanpoint_id", "starts_at", "ends_at"])
    op.create_table(
        "table_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
        sa.Column("location_id", sa.Integer(), sa.ForeignKey("business_locations.id"), nullable=False),
        sa.Column("service_area_id", sa.Integer(), sa.ForeignKey("service_areas.id"), nullable=False),
        sa.Column("external_session_id", sa.String(150)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_table_sessions_business_id", "table_sessions", ["business_id"])
    op.create_index("ix_table_sessions_location_id", "table_sessions", ["location_id"])
    op.create_index("ix_table_sessions_service_area_id", "table_sessions", ["service_area_id"])
    op.create_index("ix_table_session_area_time", "table_sessions", ["service_area_id", "opened_at", "closed_at"])
    op.create_table(
        "pos_connections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id"), nullable=False),
        sa.Column("location_id", sa.Integer(), sa.ForeignKey("business_locations.id"), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("external_location_id", sa.String(150), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("business_id", "provider", "external_location_id"),
    )
    op.create_index("ix_pos_connections_business_id", "pos_connections", ["business_id"])
    op.create_index("ix_pos_connections_location_id", "pos_connections", ["location_id"])

    with op.batch_alter_table("orders") as batch:
        batch.add_column(sa.Column("location_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("service_area_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("table_session_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("pos_connection_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("status", sa.String(30), server_default="COMPLETED", nullable=False))
        batch.add_column(sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key("fk_order_location", "business_locations", ["location_id"], ["id"])
        batch.create_foreign_key("fk_order_service_area", "service_areas", ["service_area_id"], ["id"])
        batch.create_foreign_key("fk_order_table_session", "table_sessions", ["table_session_id"], ["id"])
        batch.create_foreign_key("fk_order_pos_connection", "pos_connections", ["pos_connection_id"], ["id"])
        batch.create_index("ix_orders_location_id", ["location_id"])
        batch.create_index("ix_orders_service_area_id", ["service_area_id"])
        batch.create_index("ix_orders_table_session_id", ["table_session_id"])
        batch.create_index("ix_orders_pos_connection_id", ["pos_connection_id"])

    with op.batch_alter_table("scan_events") as batch:
        batch.alter_column("review_token_id", existing_type=sa.Integer(), nullable=True)
        batch.alter_column("order_id", existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column("scanpoint_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("assignment_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("table_session_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("resolution_reason", sa.String(255), nullable=True))
        batch.create_foreign_key("fk_scan_scanpoint", "scanpoints", ["scanpoint_id"], ["id"])
        batch.create_foreign_key("fk_scan_assignment", "scanpoint_assignments", ["assignment_id"], ["id"])
        batch.create_foreign_key("fk_scan_table_session", "table_sessions", ["table_session_id"], ["id"])
        batch.create_index("ix_scan_events_scanpoint_id", ["scanpoint_id"])
        batch.create_index("ix_scan_events_assignment_id", ["assignment_id"])
        batch.create_index("ix_scan_events_table_session_id", ["table_session_id"])

    with op.batch_alter_table("review_matches") as batch:
        batch.add_column(sa.Column("algorithm_version", sa.String(30), server_default="v1", nullable=False))
        batch.add_column(sa.Column("explanation", sa.Text(), nullable=True))

    op.create_table(
        "attribution_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("google_review_id", sa.Integer(), sa.ForeignKey("google_reviews.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scan_event_id", sa.Integer(), sa.ForeignKey("scan_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id")),
        sa.Column("score", sa.Numeric(5, 4), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("google_review_id", "scan_event_id"),
    )
    op.create_index("ix_attribution_candidates_google_review_id", "attribution_candidates", ["google_review_id"])
    op.create_index("ix_attribution_candidates_scan_event_id", "attribution_candidates", ["scan_event_id"])
    op.create_index("ix_attribution_candidates_order_id", "attribution_candidates", ["order_id"])
    op.create_table(
        "attribution_audits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("google_review_id", sa.Integer(), sa.ForeignKey("google_reviews.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scan_event_id", sa.Integer(), sa.ForeignKey("scan_events.id")),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id")),
        sa.Column("match_status", sa.String(20), nullable=False),
        sa.Column("confidence_score", sa.Numeric(5, 4), nullable=False),
        sa.Column("algorithm_version", sa.String(30), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_attribution_audits_google_review_id", "attribution_audits", ["google_review_id"])
    op.create_index("ix_attribution_audits_scan_event_id", "attribution_audits", ["scan_event_id"])
    op.create_index("ix_attribution_audits_order_id", "attribution_audits", ["order_id"])


def downgrade() -> None:
    op.drop_table("attribution_audits")
    op.drop_table("attribution_candidates")
    with op.batch_alter_table("review_matches") as batch:
        batch.drop_column("explanation")
        batch.drop_column("algorithm_version")
    with op.batch_alter_table("scan_events") as batch:
        batch.drop_index("ix_scan_events_table_session_id")
        batch.drop_index("ix_scan_events_assignment_id")
        batch.drop_index("ix_scan_events_scanpoint_id")
        batch.drop_column("resolution_reason")
        batch.drop_column("table_session_id")
        batch.drop_column("assignment_id")
        batch.drop_column("scanpoint_id")
        batch.alter_column("order_id", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("review_token_id", existing_type=sa.Integer(), nullable=False)
    with op.batch_alter_table("orders") as batch:
        for index in ("ix_orders_pos_connection_id", "ix_orders_table_session_id", "ix_orders_service_area_id", "ix_orders_location_id"):
            batch.drop_index(index)
        for column in ("source_updated_at", "status", "pos_connection_id", "table_session_id", "service_area_id", "location_id"):
            batch.drop_column(column)
    op.drop_table("pos_connections")
    op.drop_table("table_sessions")
    op.drop_table("scanpoint_assignments")
    op.drop_table("scanpoints")
    op.drop_table("service_areas")
    op.drop_table("business_locations")
    with op.batch_alter_table("businesses") as batch:
        batch.drop_index("ix_businesses_organization_id")
        batch.drop_column("api_key_hash")
        batch.drop_column("organization_id")
    op.drop_table("memberships")
    op.drop_table("users")
    op.drop_table("organizations")
