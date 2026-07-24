"""Tests for the run and alert logic (web.run_search)."""

from shopping_agent import db, web


def _alerts() -> list[str]:
    return [a["mensaje"] for a in db.recent_alerts()]


def test_first_run_alerts_only_about_the_best(fake_api, make_offer):
    fake_api({"summary": "r", "offers": [
        make_offer("https://x/a", "A", 14000),
        make_offer("https://x/b", "B", 12500),
        make_offer("https://x/c", "C", None),
    ]})
    bid = db.create_search("caravana", "Madrid", "ES", 6)
    web.run_search(bid)

    alerts = _alerts()
    assert len(alerts) == 1
    assert "inicial" in alerts[0] and "B" in alerts[0] and "12500" in alerts[0]


def test_new_best_offer_and_bargain(fake_api, make_offer):
    fake_api(
        {"summary": "r1", "offers": [make_offer("https://x/a", "A", 14000)]},
        {"summary": "r2", "offers": [
            make_offer("https://x/a", "A", 14000),
            make_offer("https://x/b", "B", 12000),                # new best
            make_offer("https://x/c", "C", 15000, bargain=True),  # bargain
            make_offer("https://x/d", "D", 14500),                # new but normal → no alert
        ]},
    )
    bid = db.create_search("caravana", "", "ES", 6)
    web.run_search(bid)
    web.run_search(bid)

    alerts = _alerts()
    assert len(alerts) == 3  # initial + new best + bargain
    assert any(m.startswith("📉") and "12000" in m for m in alerts)
    assert any(m.startswith("🔥") and "C" in m for m in alerts)
    assert not any("D" in m for m in alerts)


def test_price_drop_on_a_known_offer(fake_api, make_offer):
    fake_api(
        {"summary": "r1", "offers": [
            make_offer("https://x/a", "A", 14000),
            make_offer("https://x/b", "B", 12500),
        ]},
        {"summary": "r2", "offers": [
            make_offer("https://x/a", "A", 13500),  # drops, but not a low
            make_offer("https://x/b", "B", 11000),  # drops and hits a new low
        ]},
    )
    bid = db.create_search("caravana", "", "ES", 6)
    web.run_search(bid)
    web.run_search(bid)

    alerts = _alerts()
    drops = [m for m in alerts if m.startswith("💶")]
    assert len(drops) == 2
    alert_a = next(m for m in drops if "A" in m)
    alert_b = next(m for m in drops if "B" in m)
    assert "13500" in alert_a and "nuevo mínimo" not in alert_a
    assert "11000" in alert_b and "nuevo mínimo" in alert_b


def test_price_rise_does_not_alert(fake_api, make_offer):
    fake_api(
        {"summary": "r1", "offers": [make_offer("https://x/a", "A", 14000)]},
        {"summary": "r2", "offers": [make_offer("https://x/a", "A", 15000)]},
    )
    bid = db.create_search("caravana", "", "ES", 6)
    web.run_search(bid)
    web.run_search(bid)
    assert not any(m.startswith("💶") for m in _alerts())


def test_api_error_is_recorded_and_does_not_blow_up(monkeypatch):
    from shopping_agent import agent

    def boom(*a, **k):
        raise RuntimeError("API caída")

    monkeypatch.setattr(agent, "search_offers", boom)
    bid = db.create_search("caravana", "", "ES", 6)
    web.run_search(bid)  # must not raise

    b = db.get_search(bid)
    assert "API caída" in b["ultimo_error"]
    assert bid not in web._running  # it does not stay locked


def test_daily_limit_blocks_runs(monkeypatch, fake_api, make_offer):
    monkeypatch.setenv("MAX_RUNS_PER_DAY", "2")
    fake_api(
        {"summary": "r1", "offers": [make_offer("https://x/a", "A", 14000)]},
        {"summary": "r2", "offers": [make_offer("https://x/a", "A", 13000)]},
    )
    bid = db.create_search("caravana", "", "ES", 6)
    web.run_search(bid)
    web.run_search(bid)
    assert db.runs_today() == 2

    # Third run: the limit (2) is already reached → the API is not called
    # (fake_api would raise AssertionError if queried with no results left)
    web.run_search(bid)
    assert db.runs_today() == 2


def test_zero_limit_means_unlimited(monkeypatch):
    monkeypatch.setenv("MAX_RUNS_PER_DAY", "0")
    assert not web._limit_reached()
