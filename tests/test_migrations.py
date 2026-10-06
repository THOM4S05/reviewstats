"""Exercise the documented fresh-database migration path in a separate process."""

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from app.database import Base


def test_alembic_upgrades_empty_database_and_matches_current_models(tmp_path):
    project = Path(__file__).resolve().parents[1]
    database_url = f"sqlite:///{tmp_path / 'migrated.db'}"
    environment = {**os.environ, "DATABASE_URL": database_url}
    for command in (["upgrade", "head"], ["check"]):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *command],
            cwd=project, env=environment, capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    migrated = create_engine(database_url)
    try:
        assert set(Base.metadata.tables) <= set(inspect(migrated).get_table_names())
        with migrated.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "a91e62d7f410"
    finally:
        migrated.dispose()
