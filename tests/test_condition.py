"""Tests for the product condition filter (new / used)."""

from shopping_agent import agent, db, web


# --- parsing the form selector ------------------------------------------------

def test_empty_or_unknown_condition_means_any():
    for value in ("", "   ", "cualquiera", "seminuevo"):
        assert web._condition_from_form(value) is None


def test_condition_accepts_new_and_used_normalising_them():
    assert web._condition_from_form("nuevo") == "nuevo"
    assert web._condition_from_form(" USADO ") == "usado"


# --- normalising the condition returned by the model -------------------------

def test_condition_only_accepts_canonical_values():
    assert web._condition({"condition": "Nuevo"}) == "nuevo"
    assert web._condition({"condition": "usado "}) == "usado"
    assert web._condition({"condition": "reacondicionado"}) is None
    assert web._condition({"condition": None}) is None
    assert web._condition({}) is None


# --- server-side filter -------------------------------------------------------

def test_any_condition_discards_nothing(make_offer):
    offers = [
        make_offer("https://x/a", "A", 1000, condition="nuevo"),
        make_offer("https://x/b", "B", 900, condition="usado"),
    ]
    kept, dropped = web._filter_by_condition(offers, None)
    assert len(kept) == 2 and dropped == 0


def test_discards_the_opposite_condition_and_keeps_the_unknown_ones(make_offer):
    offers = [
        make_offer("https://x/a", "A", 1000, condition="usado"),
        make_offer("https://x/b", "B", 900, condition="nuevo"),   # discarded
        make_offer("https://x/c", "C", 800, condition=None),      # unconfirmed
    ]
    kept, dropped = web._filter_by_condition(offers, "usado")
    assert [o["title"] for o in kept] == ["A", "C"]
    assert dropped == 1


# --- integration: full run ----------------------------------------------------

def test_run_does_not_store_offers_of_the_opposite_condition(fake_api, make_offer):
    fake_api({"summary": "r", "offers": [
        make_offer("https://x/usada", "Usada", 14000, condition="usado"),
        make_offer("https://x/nueva", "Nueva", 9000, condition="nuevo"),  # cheaper, but out
        make_offer("https://x/duda", "Sin confirmar", 15000, condition=None),
    ]})
    bid = db.create_search("caravana", "Madrid", "ES", 6, wanted_condition="usado")
    web.run_search(bid)

    titles = [o["titulo"] for o in db.offers_of(bid)]
    assert set(titles) == {"Usada", "Sin confirmar"}
    assert db.best_price(bid) == 14000
    assert not any("Nueva" in a["mensaje"] for a in db.recent_alerts())
    assert "no ser producto usado" in db.get_search(bid)["ultimo_resumen"]


def test_non_canonical_condition_is_stored_as_unknown(fake_api, make_offer):
    fake_api({"summary": "r", "offers": [
        make_offer("https://x/a", "A", 14000, condition="reacondicionado"),
    ]})
    bid = db.create_search("bici", "Madrid", "ES", 6)
    web.run_search(bid)
    assert db.offers_of(bid)[0]["condicion"] is None


def test_condition_is_kept_when_it_stops_being_reported(fake_api, make_offer):
    fake_api(
        {"summary": "r1", "offers": [make_offer("https://x/a", "A", 14000, condition="usado")]},
        {"summary": "r2", "offers": [make_offer("https://x/a", "A", 13000, condition=None)]},
    )
    bid = db.create_search("caravana", "Madrid", "ES", 6)
    web.run_search(bid)
    web.run_search(bid)

    o = db.offers_of(bid)[0]
    assert o["precio"] == 13000 and o["condicion"] == "usado"


def test_radius_and_condition_are_combined(fake_api, make_offer):
    fake_api({"summary": "r", "offers": [
        make_offer("https://x/ok", "Vale", 14000, distance=30, condition="usado"),
        make_offer("https://x/lejos", "Lejos", 12000, distance=400, condition="usado"),
        make_offer("https://x/nueva", "Nueva", 11000, distance=20, condition="nuevo"),
    ]})
    bid = db.create_search("caravana", "Madrid", "ES", 6, radius_km=100, wanted_condition="usado")
    web.run_search(bid)

    assert [o["titulo"] for o in db.offers_of(bid)] == ["Vale"]
    summary = db.get_search(bid)["ultimo_resumen"]
    assert "más de 100 km" in summary and "no ser producto usado" in summary


def test_editing_the_condition_keeps_the_history(fake_api, make_offer):
    fake_api({"summary": "r", "offers": [
        make_offer("https://x/a", "A", 14000, condition="usado"),
    ]})
    bid = db.create_search("caravana", "Madrid", "ES", 6, wanted_condition="usado")
    web.run_search(bid)

    db.update_search(bid, "caravana", "Madrid", "ES", 6, wanted_condition=None)
    b = db.get_search(bid)
    assert b["estado_deseado"] is None
    assert len(db.offers_of(bid)) == 1
    assert len(db.price_history(db.offers_of(bid)[0]["id"])) == 1


# --- instructions sent to the model -------------------------------------------

def test_instructions_demand_new_products_only():
    text = agent._instructions("Madrid", None, "nuevo")
    assert "SOLO producto nuevo" in text
    assert "reacondicionado" in text.lower()


def test_instructions_demand_second_hand_products_only():
    text = agent._instructions("Madrid", None, "usado")
    assert "SOLO producto de segunda mano" in text


def test_instructions_do_not_restrict_when_any_condition_goes():
    text = agent._instructions("Madrid", None, None)
    assert "indiferente" in text
