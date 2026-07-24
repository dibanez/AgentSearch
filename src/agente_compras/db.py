"""Persistencia en SQLite: búsquedas guardadas, ofertas encontradas y avisos."""

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
    pais TEXT NOT NULL DEFAULT 'ES',
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
    estado TEXT,
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


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def conectar() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with conectar() as conn:
        conn.executescript(_SCHEMA)


# --- búsquedas ---------------------------------------------------------------

def crear_busqueda(consulta: str, ciudad: str, pais: str, intervalo_horas: float) -> int:
    with conectar() as conn:
        cur = conn.execute(
            "INSERT INTO busquedas (consulta, ciudad, pais, intervalo_horas, creada)"
            " VALUES (?, ?, ?, ?, ?)",
            (consulta, ciudad or None, (pais or "ES").upper(), intervalo_horas, _ahora()),
        )
        return cur.lastrowid


def listar_busquedas() -> list[sqlite3.Row]:
    with conectar() as conn:
        return conn.execute("SELECT * FROM busquedas ORDER BY id DESC").fetchall()


def obtener_busqueda(busqueda_id: int) -> sqlite3.Row | None:
    with conectar() as conn:
        return conn.execute(
            "SELECT * FROM busquedas WHERE id = ?", (busqueda_id,)
        ).fetchone()


def borrar_busqueda(busqueda_id: int) -> None:
    with conectar() as conn:
        conn.execute("DELETE FROM busquedas WHERE id = ?", (busqueda_id,))


def alternar_activa(busqueda_id: int) -> None:
    with conectar() as conn:
        conn.execute(
            "UPDATE busquedas SET activa = 1 - activa WHERE id = ?", (busqueda_id,)
        )


def busquedas_pendientes() -> list[sqlite3.Row]:
    """Búsquedas activas cuyo intervalo ya ha vencido."""
    ahora = datetime.now(timezone.utc)
    pendientes = []
    for b in listar_busquedas():
        if not b["activa"]:
            continue
        if b["ultima_ejecucion"] is None:
            pendientes.append(b)
            continue
        ultima = datetime.fromisoformat(b["ultima_ejecucion"])
        if (ahora - ultima).total_seconds() >= b["intervalo_horas"] * 3600:
            pendientes.append(b)
    return pendientes


def marcar_ejecutada(busqueda_id: int, resumen: str | None, error: str | None = None) -> None:
    with conectar() as conn:
        conn.execute(
            "UPDATE busquedas SET ultima_ejecucion = ?, ultimo_resumen = ?,"
            " ultimo_error = ? WHERE id = ?",
            (_ahora(), resumen, error, busqueda_id),
        )


# --- ofertas -----------------------------------------------------------------

def mejor_precio(busqueda_id: int) -> float | None:
    with conectar() as conn:
        fila = conn.execute(
            "SELECT MIN(precio) AS minimo FROM ofertas"
            " WHERE busqueda_id = ? AND precio IS NOT NULL",
            (busqueda_id,),
        ).fetchone()
        return fila["minimo"]


def upsert_oferta(busqueda_id: int, oferta: dict) -> tuple[bool, float | None]:
    """Guarda o actualiza una oferta.

    Devuelve (es_nueva, precio_anterior). El precio anterior permite detectar
    bajadas de precio en anuncios ya conocidos. Cada cambio de precio (y el
    precio inicial) se guarda como snapshot en la tabla `precios`.
    """
    ahora = _ahora()
    precio = oferta.get("precio_eur")
    with conectar() as conn:
        existente = conn.execute(
            "SELECT id, precio FROM ofertas WHERE busqueda_id = ? AND url = ?",
            (busqueda_id, oferta["url"]),
        ).fetchone()
        if existente:
            conn.execute(
                "UPDATE ofertas SET titulo = ?, precio = ?, ubicacion = ?,"
                " estado = ?, es_chollo = ?, motivo = ?, ultima_vez = ?"
                " WHERE id = ?",
                (oferta.get("titulo"), precio,
                 oferta.get("ubicacion"), oferta.get("estado"),
                 int(bool(oferta.get("es_chollo"))), oferta.get("motivo"),
                 ahora, existente["id"]),
            )
            if precio is not None and precio != existente["precio"]:
                conn.execute(
                    "INSERT INTO precios (oferta_id, precio, visto) VALUES (?, ?, ?)",
                    (existente["id"], precio, ahora),
                )
            return False, existente["precio"]
        cur = conn.execute(
            "INSERT INTO ofertas (busqueda_id, url, titulo, precio, ubicacion,"
            " estado, es_chollo, motivo, primera_vez, ultima_vez)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (busqueda_id, oferta["url"], oferta.get("titulo"),
             precio, oferta.get("ubicacion"),
             oferta.get("estado"), int(bool(oferta.get("es_chollo"))),
             oferta.get("motivo"), ahora, ahora),
        )
        if precio is not None:
            conn.execute(
                "INSERT INTO precios (oferta_id, precio, visto) VALUES (?, ?, ?)",
                (cur.lastrowid, precio, ahora),
            )
        return True, None


def historial_precios(oferta_id: int) -> list[sqlite3.Row]:
    with conectar() as conn:
        return conn.execute(
            "SELECT precio, visto FROM precios WHERE oferta_id = ? ORDER BY id",
            (oferta_id,),
        ).fetchall()


def ofertas_de(busqueda_id: int) -> list[sqlite3.Row]:
    with conectar() as conn:
        return conn.execute(
            "SELECT * FROM ofertas WHERE busqueda_id = ?"
            " ORDER BY (precio IS NULL), precio ASC",
            (busqueda_id,),
        ).fetchall()


# --- avisos ------------------------------------------------------------------

def crear_aviso(busqueda_id: int, mensaje: str, url: str | None = None) -> None:
    with conectar() as conn:
        conn.execute(
            "INSERT INTO avisos (busqueda_id, mensaje, url, creado) VALUES (?, ?, ?, ?)",
            (busqueda_id, mensaje, url, _ahora()),
        )


# --- ejecuciones (límite de gasto diario) ------------------------------------

def registrar_ejecucion(busqueda_id: int) -> None:
    with conectar() as conn:
        conn.execute(
            "INSERT INTO ejecuciones (busqueda_id, creado) VALUES (?, ?)",
            (busqueda_id, _ahora()),
        )


def ejecuciones_hoy() -> int:
    """Número de ejecuciones (llamadas a la API) desde las 00:00 UTC."""
    inicio_dia = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00")
    with conectar() as conn:
        fila = conn.execute(
            "SELECT COUNT(*) AS n FROM ejecuciones WHERE creado >= ?",
            (inicio_dia,),
        ).fetchone()
        return fila["n"]


def avisos_recientes(limite: int = 20) -> list[sqlite3.Row]:
    with conectar() as conn:
        return conn.execute(
            "SELECT a.*, b.consulta FROM avisos a"
            " LEFT JOIN busquedas b ON b.id = a.busqueda_id"
            " ORDER BY a.id DESC LIMIT ?",
            (limite,),
        ).fetchall()
