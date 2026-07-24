"""Tests unitarios de la capa de persistencia (db.py)."""

from datetime import datetime, timedelta, timezone

from agente_compras import db


def test_crear_y_listar_busquedas():
    bid = db.crear_busqueda("caravana 4 plazas", "Madrid", "es", 6)
    b = db.obtener_busqueda(bid)
    assert b["consulta"] == "caravana 4 plazas"
    assert b["pais"] == "ES"  # se normaliza a mayúsculas
    assert b["activa"] == 1
    assert len(db.listar_busquedas()) == 1


def test_borrar_busqueda_borra_en_cascada(hacer_oferta):
    bid = db.crear_busqueda("moto", "", "ES", 6)
    db.upsert_oferta(bid, hacer_oferta("https://x/a", "Moto A", 3000))
    db.crear_aviso(bid, "aviso de prueba")
    db.borrar_busqueda(bid)
    assert db.obtener_busqueda(bid) is None
    assert db.ofertas_de(bid) == []
    assert db.avisos_recientes() == []


def test_alternar_activa():
    bid = db.crear_busqueda("bici", "", "ES", 6)
    db.alternar_activa(bid)
    assert db.obtener_busqueda(bid)["activa"] == 0
    db.alternar_activa(bid)
    assert db.obtener_busqueda(bid)["activa"] == 1


def test_busquedas_pendientes():
    bid = db.crear_busqueda("patinete", "", "ES", intervalo_horas=1)
    # Nunca ejecutada → pendiente
    assert [b["id"] for b in db.busquedas_pendientes()] == [bid]

    # Recién ejecutada → ya no está pendiente
    db.marcar_ejecutada(bid, "resumen")
    assert db.busquedas_pendientes() == []

    # Simular que la última ejecución fue hace 2 horas → vuelve a estar pendiente
    hace_2h = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(timespec="seconds")
    with db.conectar() as conn:
        conn.execute("UPDATE busquedas SET ultima_ejecucion = ? WHERE id = ?", (hace_2h, bid))
    assert [b["id"] for b in db.busquedas_pendientes()] == [bid]

    # Pausada → no pendiente aunque haya vencido
    db.alternar_activa(bid)
    assert db.busquedas_pendientes() == []


def test_upsert_dedupe_y_precio_anterior(hacer_oferta):
    bid = db.crear_busqueda("caravana", "", "ES", 6)
    es_nueva, anterior = db.upsert_oferta(bid, hacer_oferta("https://x/a", "A", 14000))
    assert es_nueva and anterior is None

    es_nueva, anterior = db.upsert_oferta(bid, hacer_oferta("https://x/a", "A", 13500))
    assert not es_nueva
    assert anterior == 14000
    assert len(db.ofertas_de(bid)) == 1  # misma URL → no se duplica


def test_mejor_precio_ignora_nulls(hacer_oferta):
    bid = db.crear_busqueda("caravana", "", "ES", 6)
    assert db.mejor_precio(bid) is None
    db.upsert_oferta(bid, hacer_oferta("https://x/a", "A", 14000))
    db.upsert_oferta(bid, hacer_oferta("https://x/b", "B", None))
    db.upsert_oferta(bid, hacer_oferta("https://x/c", "C", 12000))
    assert db.mejor_precio(bid) == 12000


def test_historial_de_precios(hacer_oferta):
    bid = db.crear_busqueda("caravana", "", "ES", 6)
    db.upsert_oferta(bid, hacer_oferta("https://x/a", "A", 14000))
    db.upsert_oferta(bid, hacer_oferta("https://x/a", "A", 14000))  # sin cambio → no snapshot
    db.upsert_oferta(bid, hacer_oferta("https://x/a", "A", 13500))
    db.upsert_oferta(bid, hacer_oferta("https://x/a", "A", 12900))

    oferta_id = db.ofertas_de(bid)[0]["id"]
    precios = [h["precio"] for h in db.historial_precios(oferta_id)]
    assert precios == [14000, 13500, 12900]


def test_historial_sin_precio_no_crea_snapshot(hacer_oferta):
    bid = db.crear_busqueda("caravana", "", "ES", 6)
    db.upsert_oferta(bid, hacer_oferta("https://x/a", "A", None))
    oferta_id = db.ofertas_de(bid)[0]["id"]
    assert db.historial_precios(oferta_id) == []


def test_contador_de_ejecuciones():
    bid = db.crear_busqueda("caravana", "", "ES", 6)
    assert db.ejecuciones_hoy() == 0
    db.registrar_ejecucion(bid)
    db.registrar_ejecucion(bid)
    assert db.ejecuciones_hoy() == 2

    # Las ejecuciones de ayer no cuentan
    ayer = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    with db.conectar() as conn:
        conn.execute("UPDATE ejecuciones SET creado = ?", (ayer,))
    assert db.ejecuciones_hoy() == 0
