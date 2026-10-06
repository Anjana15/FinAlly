from __future__ import annotations

import pytest

from app import db


@pytest.fixture
def conn(tmp_path):
    db.init_db(str(tmp_path / "finally.db"))
    return db.get_conn()
