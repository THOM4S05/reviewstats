import os
import tempfile
from pathlib import Path

import pytest

_db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_db_file.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_db_file.name}"
os.environ["DEFAULT_GOOGLE_REVIEW_URL"] = "https://example.com/write-review"
os.environ["PUBLIC_BASE_URL"] = "http://testserver"
os.environ["REVIEW_DESTINATION"] = "mock"

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app, seed_business  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app, follow_redirects=False) as test_client:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        seed_business()
        yield test_client


def pytest_sessionfinish(session, exitstatus):
    Path(_db_file.name).unlink(missing_ok=True)
