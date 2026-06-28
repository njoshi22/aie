import os

# Unit tests run against revmem_client stubs; force stub mode before any test module
# imports it, so a live REVMEM_BASE_URL in .env doesn't turn them into real HTTP calls.
os.environ.setdefault("REVMEM_STUB_MODE", "1")

import pytest  # noqa: E402

from core import database  # noqa: E402


@pytest.fixture()
def conn(tmp_path):
    c = database.get_connection(tmp_path / "test.db")
    database.init_db(c)
    yield c
    c.close()
