"""Unit tests for the persistence layer (db.py)."""

from datetime import datetime, timedelta, timezone

from shopping_agent import db


def test_create_and_list_searches():
    bid = db.create_search("caravana 4 plazas", "Madrid", "es", 6)
    b = db.get_search(bid)
    assert b["consulta"] == "caravana 4 plazas"
    assert b["pais"] == "ES"  # normalised to uppercase
    assert b["activa"] == 1
    assert len(db.list_searches()) == 1


def test_deleting_a_search_cascades(make_offer):
    bid = db.create_search("moto", "", "ES", 6)
    db.upsert_offer(bid, make_offer("https://x/a", "Moto A", 3000))
    db.create_alert(bid, "aviso de prueba")
    db.delete_search(bid)
    assert db.get_search(bid) is None
    assert db.offers_of(bid) == []
    assert db.recent_alerts() == []


def test_toggle_active():
    bid = db.create_search("bici", "", "ES", 6)
    db.toggle_active(bid)
    assert db.get_search(bid)["activa"] == 0
    db.toggle_active(bid)
    assert db.get_search(bid)["activa"] == 1


def test_due_searches():
    bid = db.create_search("patinete", "", "ES", interval_hours=1)
    # Never run → due
    assert [b["id"] for b in db.due_searches()] == [bid]

    # Just run → no longer due
    db.mark_run(bid, "resumen")
    assert db.due_searches() == []

    # Pretend the last run was 2 hours ago → due again
    two_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(timespec="seconds")
    with db.connect() as conn:
        conn.execute("UPDATE busquedas SET ultima_ejecucion = ? WHERE id = ?", (two_hours_ago, bid))
    assert [b["id"] for b in db.due_searches()] == [bid]

    # Paused → not due even if overdue
    db.toggle_active(bid)
    assert db.due_searches() == []


def test_upsert_dedupes_and_returns_the_previous_price(make_offer):
    bid = db.create_search("caravana", "", "ES", 6)
    is_new, previous = db.upsert_offer(bid, make_offer("https://x/a", "A", 14000))
    assert is_new and previous is None

    is_new, previous = db.upsert_offer(bid, make_offer("https://x/a", "A", 13500))
    assert not is_new
    assert previous == 14000
    assert len(db.offers_of(bid)) == 1  # same URL → not duplicated


def test_best_price_ignores_nulls(make_offer):
    bid = db.create_search("caravana", "", "ES", 6)
    assert db.best_price(bid) is None
    db.upsert_offer(bid, make_offer("https://x/a", "A", 14000))
    db.upsert_offer(bid, make_offer("https://x/b", "B", None))
    db.upsert_offer(bid, make_offer("https://x/c", "C", 12000))
    assert db.best_price(bid) == 12000


def test_price_history(make_offer):
    bid = db.create_search("caravana", "", "ES", 6)
    db.upsert_offer(bid, make_offer("https://x/a", "A", 14000))
    db.upsert_offer(bid, make_offer("https://x/a", "A", 14000))  # unchanged → no snapshot
    db.upsert_offer(bid, make_offer("https://x/a", "A", 13500))
    db.upsert_offer(bid, make_offer("https://x/a", "A", 12900))

    offer_id = db.offers_of(bid)[0]["id"]
    prices = [h["precio"] for h in db.price_history(offer_id)]
    assert prices == [14000, 13500, 12900]


def test_an_offer_without_price_creates_no_snapshot(make_offer):
    bid = db.create_search("caravana", "", "ES", 6)
    db.upsert_offer(bid, make_offer("https://x/a", "A", None))
    offer_id = db.offers_of(bid)[0]["id"]
    assert db.price_history(offer_id) == []


def test_run_counter():
    bid = db.create_search("caravana", "", "ES", 6)
    assert db.runs_today() == 0
    db.record_run(bid)
    db.record_run(bid)
    assert db.runs_today() == 2

    # Yesterday's runs do not count
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    with db.connect() as conn:
        conn.execute("UPDATE ejecuciones SET creado = ?", (yesterday,))
    assert db.runs_today() == 0


def test_updating_a_search_keeps_the_history(make_offer):
    bid = db.create_search("caravana 4 plazas", "Madrid", "ES", 6)
    db.upsert_offer(bid, make_offer("https://x/a", "A", 14000))
    db.upsert_offer(bid, make_offer("https://x/a", "A", 13000))

    db.update_search(bid, "caravana 4 plazas con calefacción", "Valencia", "es", 12)

    b = db.get_search(bid)
    assert b["consulta"] == "caravana 4 plazas con calefacción"
    assert b["ciudad"] == "Valencia"
    assert b["pais"] == "ES"
    assert b["intervalo_horas"] == 12
    # The offer and price history is preserved
    offers = db.offers_of(bid)
    assert len(offers) == 1
    assert [h["precio"] for h in db.price_history(offers[0]["id"])] == [14000, 13000]
