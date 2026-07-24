"""Tests for the search radius in km (distance filter)."""

from shopping_agent import agent, db, web


# --- parsing the form field --------------------------------------------------

def test_an_empty_or_invalid_radius_means_no_limit():
    for value in ("", "   ", "abc", "0", "-50"):
        assert web._radius_from_form(value) is None


def test_radius_accepts_integers_and_comma_decimals():
    assert web._radius_from_form("100") == 100
    assert web._radius_from_form(" 75,5 ") == 75.5


# --- server-side filter ------------------------------------------------------

def test_without_a_radius_nothing_is_discarded(make_offer):
    offers = [
        make_offer("https://x/a", "A", 1000, distance=10),
        make_offer("https://x/b", "B", 900, distance=800),
    ]
    kept, dropped = web._filter_by_radius(offers, None)
    assert len(kept) == 2 and dropped == 0


def test_discards_offers_beyond_the_radius_and_keeps_the_unknown_ones(make_offer):
    offers = [
        make_offer("https://x/a", "A", 1000, distance=40),    # inside
        make_offer("https://x/b", "B", 900, distance=100),    # right on the limit
        make_offer("https://x/c", "C", 800, distance=250),    # outside
        make_offer("https://x/d", "D", 700, distance=None),   # unconfirmed
    ]
    kept, dropped = web._filter_by_radius(offers, 100)
    assert [o["title"] for o in kept] == ["A", "B", "D"]
    assert dropped == 1


def test_a_non_numeric_distance_is_treated_as_unknown(make_offer):
    o = make_offer("https://x/a", "A", 1000)
    o["distance_km"] = "unos 300 km"
    kept, dropped = web._filter_by_radius([o], 50)
    assert len(kept) == 1 and dropped == 0


# --- integration: full run ---------------------------------------------------

def test_run_does_not_store_offers_outside_the_radius(fake_api, make_offer):
    fake_api({"summary": "r", "offers": [
        make_offer("https://x/cerca", "Cerca", 14000, distance=30),
        make_offer("https://x/lejos", "Lejos", 9000, distance=400),   # cheaper but outside
        make_offer("https://x/duda", "Sin confirmar", 15000, distance=None),
    ]})
    bid = db.create_search("caravana", "Madrid", "ES", 6, radius_km=100)
    web.run_search(bid)

    titles = [o["titulo"] for o in db.offers_of(bid)]
    assert "Lejos" not in titles
    assert set(titles) == {"Cerca", "Sin confirmar"}
    # A discarded offer must not set the lowest price nor raise alerts either
    assert db.best_price(bid) == 14000
    assert not any("Lejos" in a["mensaje"] for a in db.recent_alerts())
    # The summary records what was discarded
    assert "descartadas" in db.get_search(bid)["ultimo_resumen"]


def test_distance_is_stored_and_kept_when_it_stops_being_reported(fake_api, make_offer):
    fake_api(
        {"summary": "r1", "offers": [make_offer("https://x/a", "A", 14000, distance=45)]},
        {"summary": "r2", "offers": [make_offer("https://x/a", "A", 13000, distance=None)]},
    )
    bid = db.create_search("caravana", "Madrid", "ES", 6, radius_km=100)
    web.run_search(bid)
    assert db.offers_of(bid)[0]["distancia_km"] == 45

    web.run_search(bid)
    o = db.offers_of(bid)[0]
    assert o["precio"] == 13000
    assert o["distancia_km"] == 45  # the already known distance is not lost


def test_editing_the_radius_keeps_the_history(fake_api, make_offer):
    fake_api({"summary": "r", "offers": [
        make_offer("https://x/a", "A", 14000, distance=45),
    ]})
    bid = db.create_search("caravana", "Madrid", "ES", 6, radius_km=50)
    web.run_search(bid)

    db.update_search(bid, "caravana", "Madrid", "ES", 6, radius_km=200)
    b = db.get_search(bid)
    assert b["radio_km"] == 200
    assert len(db.offers_of(bid)) == 1
    assert len(db.price_history(db.offers_of(bid)[0]["id"])) == 1


def test_removing_the_radius_leaves_it_unlimited():
    bid = db.create_search("caravana", "Madrid", "ES", 6, radius_km=50)
    db.update_search(bid, "caravana", "Madrid", "ES", 6, radius_km=None)
    assert db.get_search(bid)["radio_km"] is None


# --- instructions sent to the model ------------------------------------------

def test_instructions_enforce_the_radius_when_there_is_one():
    text = agent._instructions("Madrid", 100)
    assert "100 km o menos de Madrid" in text
    assert "NO amplíes el radio" in text


def test_instructions_without_a_radius_do_not_limit_the_distance():
    text = agent._instructions("Madrid", None)
    assert "sin límite de distancia" in text
