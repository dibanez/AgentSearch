import pytest

from shopping_agent import db, web


@pytest.fixture(autouse=True)
def temp_database(tmp_path, monkeypatch):
    """Every test uses a clean, isolated SQLite database."""
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
    web._running.clear()
    yield


@pytest.fixture(autouse=True)
def no_telegram(monkeypatch):
    """Tests never send real notifications."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)


@pytest.fixture(autouse=True)
def no_daily_limit_by_default(monkeypatch):
    """By default tests run with no daily limit (each test enables it)."""
    monkeypatch.setenv("MAX_RUNS_PER_DAY", "0")


def offer(url: str, title: str, price: float | None, bargain: bool = False,
          distance: float | None = None, condition: str | None = None) -> dict:
    return {
        "title": title,
        "price_eur": price,
        "location": "Madrid",
        "distance_km": distance,
        "condition_text": "usado",
        "condition": condition,
        "url": url,
        "is_bargain": bargain,
        "reason": "prueba",
    }


@pytest.fixture
def make_offer():
    return offer


@pytest.fixture
def fake_api(monkeypatch):
    """Replaces agent.search_offers with a queue of predefined results."""
    from shopping_agent import agent

    results: list[dict] = []

    def enqueue(*datas: dict) -> None:
        results.extend(datas)

    def fake_search(*args, **kwargs) -> dict:
        if not results:
            raise AssertionError("fake_api: no queued results left")
        return results.pop(0)

    monkeypatch.setattr(agent, "search_offers", fake_search)
    return enqueue
