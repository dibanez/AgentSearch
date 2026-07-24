import pytest

from agente_compras import db, web


@pytest.fixture(autouse=True)
def base_datos_temporal(tmp_path, monkeypatch):
    """Cada test usa una base de datos SQLite limpia y aislada."""
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
    web._en_ejecucion.clear()
    yield


@pytest.fixture(autouse=True)
def sin_telegram(monkeypatch):
    """Los tests nunca envían notificaciones reales."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)


@pytest.fixture(autouse=True)
def sin_limite_por_defecto(monkeypatch):
    """Por defecto los tests corren sin límite diario (se activa por test)."""
    monkeypatch.setenv("MAX_EJECUCIONES_DIA", "0")


def oferta(url: str, titulo: str, precio: float | None, chollo: bool = False) -> dict:
    return {
        "titulo": titulo,
        "precio_eur": precio,
        "ubicacion": "Madrid",
        "estado": "usado",
        "url": url,
        "es_chollo": chollo,
        "motivo": "prueba",
    }


@pytest.fixture
def hacer_oferta():
    return oferta


@pytest.fixture
def api_simulada(monkeypatch):
    """Sustituye agent.buscar_ofertas por una cola de resultados predefinidos."""
    from agente_compras import agent

    resultados: list[dict] = []

    def encolar(*datas: dict) -> None:
        resultados.extend(datas)

    def falso_buscar(*args, **kwargs) -> dict:
        if not resultados:
            raise AssertionError("api_simulada: no quedan resultados encolados")
        return resultados.pop(0)

    monkeypatch.setattr(agent, "buscar_ofertas", falso_buscar)
    return encolar
