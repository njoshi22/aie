import pytest

from core import database


@pytest.fixture()
def conn(tmp_path):
    c = database.get_connection(tmp_path / "test.db")
    database.init_db(c)
    yield c
    c.close()
