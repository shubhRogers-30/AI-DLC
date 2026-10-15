import pytest

from app.core.config import settings

settings.mock_mode = True


@pytest.fixture(autouse=True)
def isolate_api_token(monkeypatch):
    monkeypatch.setattr(settings, "api_token", "")