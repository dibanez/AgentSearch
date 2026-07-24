"""Tests de la lógica de ejecución y avisos (web.ejecutar_busqueda)."""

from agente_compras import db, web


def _avisos() -> list[str]:
    return [a["mensaje"] for a in db.avisos_recientes()]


def test_primera_ejecucion_avisa_solo_de_la_mejor(api_simulada, hacer_oferta):
    api_simulada({"resumen": "r", "ofertas": [
        hacer_oferta("https://x/a", "A", 14000),
        hacer_oferta("https://x/b", "B", 12500),
        hacer_oferta("https://x/c", "C", None),
    ]})
    bid = db.crear_busqueda("caravana", "Madrid", "ES", 6)
    web.ejecutar_busqueda(bid)

    avisos = _avisos()
    assert len(avisos) == 1
    assert "inicial" in avisos[0] and "B" in avisos[0] and "12500" in avisos[0]


def test_nueva_mejor_oferta_y_chollo(api_simulada, hacer_oferta):
    api_simulada(
        {"resumen": "r1", "ofertas": [hacer_oferta("https://x/a", "A", 14000)]},
        {"resumen": "r2", "ofertas": [
            hacer_oferta("https://x/a", "A", 14000),
            hacer_oferta("https://x/b", "B", 12000),              # nueva mejor
            hacer_oferta("https://x/c", "C", 15000, chollo=True),  # chollo
            hacer_oferta("https://x/d", "D", 14500),               # nueva normal → sin aviso
        ]},
    )
    bid = db.crear_busqueda("caravana", "", "ES", 6)
    web.ejecutar_busqueda(bid)
    web.ejecutar_busqueda(bid)

    avisos = _avisos()
    assert len(avisos) == 3  # inicial + nueva mejor + chollo
    assert any(m.startswith("📉") and "12000" in m for m in avisos)
    assert any(m.startswith("🔥") and "C" in m for m in avisos)
    assert not any("D" in m for m in avisos)


def test_bajada_de_precio_en_oferta_conocida(api_simulada, hacer_oferta):
    api_simulada(
        {"resumen": "r1", "ofertas": [
            hacer_oferta("https://x/a", "A", 14000),
            hacer_oferta("https://x/b", "B", 12500),
        ]},
        {"resumen": "r2", "ofertas": [
            hacer_oferta("https://x/a", "A", 13500),  # baja, sin ser mínimo
            hacer_oferta("https://x/b", "B", 11000),  # baja y nuevo mínimo
        ]},
    )
    bid = db.crear_busqueda("caravana", "", "ES", 6)
    web.ejecutar_busqueda(bid)
    web.ejecutar_busqueda(bid)

    avisos = _avisos()
    bajadas = [m for m in avisos if m.startswith("💶")]
    assert len(bajadas) == 2
    aviso_a = next(m for m in bajadas if "A" in m)
    aviso_b = next(m for m in bajadas if "B" in m)
    assert "13500" in aviso_a and "nuevo mínimo" not in aviso_a
    assert "11000" in aviso_b and "nuevo mínimo" in aviso_b


def test_subida_de_precio_no_avisa(api_simulada, hacer_oferta):
    api_simulada(
        {"resumen": "r1", "ofertas": [hacer_oferta("https://x/a", "A", 14000)]},
        {"resumen": "r2", "ofertas": [hacer_oferta("https://x/a", "A", 15000)]},
    )
    bid = db.crear_busqueda("caravana", "", "ES", 6)
    web.ejecutar_busqueda(bid)
    web.ejecutar_busqueda(bid)
    assert not any(m.startswith("💶") for m in _avisos())


def test_error_de_api_se_registra_y_no_revienta(monkeypatch):
    from agente_compras import agent

    def explota(*a, **k):
        raise RuntimeError("API caída")

    monkeypatch.setattr(agent, "buscar_ofertas", explota)
    bid = db.crear_busqueda("caravana", "", "ES", 6)
    web.ejecutar_busqueda(bid)  # no debe lanzar

    b = db.obtener_busqueda(bid)
    assert "API caída" in b["ultimo_error"]
    assert bid not in web._en_ejecucion  # no se queda bloqueada


def test_limite_diario_bloquea_ejecuciones(monkeypatch, api_simulada, hacer_oferta):
    monkeypatch.setenv("MAX_EJECUCIONES_DIA", "2")
    api_simulada(
        {"resumen": "r1", "ofertas": [hacer_oferta("https://x/a", "A", 14000)]},
        {"resumen": "r2", "ofertas": [hacer_oferta("https://x/a", "A", 13000)]},
    )
    bid = db.crear_busqueda("caravana", "", "ES", 6)
    web.ejecutar_busqueda(bid)
    web.ejecutar_busqueda(bid)
    assert db.ejecuciones_hoy() == 2

    # Tercera ejecución: el límite (2) ya está alcanzado → no llama a la API
    # (la api_simulada lanzaría AssertionError si se consultara sin resultados)
    web.ejecutar_busqueda(bid)
    assert db.ejecuciones_hoy() == 2


def test_limite_cero_es_ilimitado(monkeypatch):
    monkeypatch.setenv("MAX_EJECUCIONES_DIA", "0")
    assert not web._limite_alcanzado()
