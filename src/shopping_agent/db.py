"""SQLite persistence: saved searches, offers found and alerts."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = os.environ.get("DB_PATH", "data/agente.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS busquedas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    consulta TEXT NOT NULL,
    ciudad TEXT,
    radio_km REAL,
    pais TEXT NOT NULL DEFAULT 'ES',
    estado_deseado TEXT,          -- 'nuevo' | 'usado' | NULL = indiferente
    intervalo_horas REAL NOT NULL DEFAULT 6,
    activa INTEGER NOT NULL DEFAULT 1,
    creada TEXT NOT NULL,
    ultima_ejecucion TEXT,
    ultimo_resumen TEXT,
    ultimo_error TEXT
);
CREATE TABLE IF NOT EXISTS ofertas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    busqueda_id INTEGER NOT NULL REFERENCES busquedas(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    titulo TEXT,
    precio REAL,
    ubicacion TEXT,
    distancia_km REAL,
    estado TEXT,                  -- texto libre del anuncio
    condicion TEXT,               -- 'nuevo' | 'usado' | NULL = sin confirmar
    es_chollo INTEGER NOT NULL DEFAULT 0,
    motivo TEXT,
    primera_vez TEXT NOT NULL,
    ultima_vez TEXT NOT NULL,
    UNIQUE (busqueda_id, url)
);
CREATE TABLE IF NOT EXISTS avisos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    busqueda_id INTEGER REFERENCES busquedas(id) ON DELETE CASCADE,
    mensaje TEXT NOT NULL,
    url TEXT,
    creado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS precios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    oferta_id INTEGER NOT NULL REFERENCES ofertas(id) ON DELETE CASCADE,
    precio REAL NOT NULL,
    visto TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ejecuciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    busqueda_id INTEGER REFERENCES busquedas(id) ON DELETE SET NULL,
    creado TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Columns added after the first version. They are applied with ALTER TABLE on
# already existing databases (CREATE TABLE IF NOT EXISTS does not add them).
_MIGRATIONS = [
    ("busquedas", "radio_km", "REAL"),
    ("busquedas", "estado_deseado", "TEXT"),
    ("ofertas", "distancia_km", "REAL"),
    ("ofertas", "condicion", "TEXT"),
]


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, type_ in _MIGRATIONS:
        existing = {f["name"] for f in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {type_}")


def init_db() -> None:
    with connect() as conn:
        conn.executescript(_SCHEMA)
        _migrate(conn)


# --- searches ----------------------------------------------------------------

def create_search(query: str, city: str, country: str, interval_hours: float,
                  radius_km: float | None = None,
                  wanted_condition: str | None = None) -> int:
    """Creates a watched search.

    `radius_km` None = no distance limit; `wanted_condition` None = don't care
    (both new and second-hand are fine).
    """
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO busquedas (consulta, ciudad, radio_km, pais, estado_deseado,"
            " intervalo_horas, creada) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (query, city or None, radius_km, (country or "ES").upper(),
             wanted_condition, interval_hours, _now()),
        )
        return cur.lastrowid


def list_searches() -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute("SELECT * FROM busquedas ORDER BY id DESC").fetchall()


def get_search(search_id: int) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM busquedas WHERE id = ?", (search_id,)
        ).fetchone()


def update_search(search_id: int, query: str, city: str,
                  country: str, interval_hours: float,
                  radius_km: float | None = None,
                  wanted_condition: str | None = None) -> None:
    """Edits a search keeping its history of offers and prices."""
    with connect() as conn:
        conn.execute(
            "UPDATE busquedas SET consulta = ?, ciudad = ?, radio_km = ?, pais = ?,"
            " estado_deseado = ?, intervalo_horas = ? WHERE id = ?",
            (query, city or None, radius_km, (country or "ES").upper(),
             wanted_condition, interval_hours, search_id),
        )


def delete_search(search_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM busquedas WHERE id = ?", (search_id,))


def toggle_active(search_id: int) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE busquedas SET activa = 1 - activa WHERE id = ?", (search_id,)
        )


def due_searches() -> list[sqlite3.Row]:
    """Active searches whose interval has already elapsed."""
    now = datetime.now(timezone.utc)
    due = []
    for b in list_searches():
        if not b["activa"]:
            continue
        if b["ultima_ejecucion"] is None:
            due.append(b)
            continue
        last = datetime.fromisoformat(b["ultima_ejecucion"])
        if (now - last).total_seconds() >= b["intervalo_horas"] * 3600:
            due.append(b)
    return due


def mark_run(search_id: int, summary: str | None, error: str | None = None) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE busquedas SET ultima_ejecucion = ?, ultimo_resumen = ?,"
            " ultimo_error = ? WHERE id = ?",
            (_now(), summary, error, search_id),
        )


# --- offers ------------------------------------------------------------------

def best_price(search_id: int) -> float | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT MIN(precio) AS minimo FROM ofertas"
            " WHERE busqueda_id = ? AND precio IS NOT NULL",
            (search_id,),
        ).fetchone()
        return row["minimo"]


def upsert_offer(search_id: int, offer: dict) -> tuple[bool, float | None]:
    """Stores or updates an offer.

    Returns (is_new, previous_price). The previous price is what lets us detect
    price drops on already known listings. Every price change (and the initial
    price) is stored as a snapshot in the `precios` table.
    """
    now = _now()
    price = offer.get("price_eur")
    with connect() as conn:
        existing = conn.execute(
            "SELECT id, precio FROM ofertas WHERE busqueda_id = ? AND url = ?",
            (search_id, offer["url"]),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE ofertas SET titulo = ?, precio = ?, ubicacion = ?,"
                " distancia_km = COALESCE(?, distancia_km),"
                " estado = ?, condicion = COALESCE(?, condicion),"
                " es_chollo = ?, motivo = ?, ultima_vez = ?"
                " WHERE id = ?",
                (offer.get("title"), price,
                 offer.get("location"), offer.get("distance_km"),
                 offer.get("condition_text"), offer.get("condition"),
                 int(bool(offer.get("is_bargain"))), offer.get("reason"),
                 now, existing["id"]),
            )
            if price is not None and price != existing["precio"]:
                conn.execute(
                    "INSERT INTO precios (oferta_id, precio, visto) VALUES (?, ?, ?)",
                    (existing["id"], price, now),
                )
            return False, existing["precio"]
        cur = conn.execute(
            "INSERT INTO ofertas (busqueda_id, url, titulo, precio, ubicacion,"
            " distancia_km, estado, condicion, es_chollo, motivo,"
            " primera_vez, ultima_vez)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (search_id, offer["url"], offer.get("title"),
             price, offer.get("location"), offer.get("distance_km"),
             offer.get("condition_text"), offer.get("condition"),
             int(bool(offer.get("is_bargain"))),
             offer.get("reason"), now, now),
        )
        if price is not None:
            conn.execute(
                "INSERT INTO precios (oferta_id, precio, visto) VALUES (?, ?, ?)",
                (cur.lastrowid, price, now),
            )
        return True, None


def price_history(offer_id: int) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT precio, visto FROM precios WHERE oferta_id = ? ORDER BY id",
            (offer_id,),
        ).fetchall()


def offers_of(search_id: int) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM ofertas WHERE busqueda_id = ?"
            " ORDER BY (precio IS NULL), precio ASC",
            (search_id,),
        ).fetchall()


# --- alerts ------------------------------------------------------------------

def create_alert(search_id: int, message: str, url: str | None = None) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO avisos (busqueda_id, mensaje, url, creado) VALUES (?, ?, ?, ?)",
            (search_id, message, url, _now()),
        )


# --- runs (daily spend limit) ------------------------------------------------

def record_run(search_id: int) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO ejecuciones (busqueda_id, creado) VALUES (?, ?)",
            (search_id, _now()),
        )


def runs_today() -> int:
    """Number of runs (API calls) since 00:00 UTC."""
    day_start = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00")
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM ejecuciones WHERE creado >= ?",
            (day_start,),
        ).fetchone()
        return row["n"]


def recent_alerts(limit: int = 20) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT a.*, b.consulta FROM avisos a"
            " LEFT JOIN busquedas b ON b.id = a.busqueda_id"
            " ORDER BY a.id DESC LIMIT ?",
            (limit,),
        ).fetchall()
