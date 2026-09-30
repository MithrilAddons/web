import pytest


@pytest.fixture(autouse=True)
def offline_pet_market(monkeypatch):
    # Continuous price collection must never send real requests in app tests.
    def unavailable(_path):
        raise ValueError("No synthetic market feed configured")

    monkeypatch.setattr("mithril_web.slayer_market.fetch_json", unavailable)
