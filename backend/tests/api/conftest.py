from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FINALLY_DB_PATH", str(tmp_path / "finally.db"))
    monkeypatch.setenv("SIMULATOR_SEED", "1")
    monkeypatch.setenv("LLM_MOCK", "true")
    monkeypatch.setenv("MASSIVE_API_KEY", "")
    return tmp_path


@pytest.fixture
def client(env):
    from app.main import create_app

    app = create_app(static_dir=env / "no-static")
    with TestClient(app) as c:
        yield c
