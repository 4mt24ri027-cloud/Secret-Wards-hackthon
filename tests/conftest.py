import pytest


@pytest.fixture(autouse=True)
def test_secret(monkeypatch):
    """Every test runs with a throwaway secret; the real one is never needed."""
    monkeypatch.setenv("RAKSHA_SECRET", "unit-test-secret")
