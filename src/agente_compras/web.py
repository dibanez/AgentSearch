"""Panel web + planificador de búsquedas periódicas.

Arranque:  uvicorn agente_compras.web:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import base64
import html
import logging
import os
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import agent, db, notify

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("agente")

INTERVALO_COMPROBACION_S = 60  # cada cuánto mira el planificador si hay búsquedas vencidas
_en_ejecucion: set[int] = set()


def _limite_diario() -> int:
    """Máximo de ejecuciones (llamadas a la API) por día. 0 = sin límite."""
    try:
        return int(os.environ.get("MAX_EJECUCIONES_DIA", "24"))
    except ValueError:
        return 24


def _limite_alcanzado() -> bool:
    limite = _limite_diario()
    return limite > 0 and db.ejecuciones_hoy() >= limite


# --- núcleo: ejecutar una búsqueda y generar avisos --------------------------

def ejecutar_busqueda(busqueda_id: int) -> None:
    b = db.obtener_busqueda(busqueda_id)
    if b is None or busqueda_id in _en_ejecucion:
        return
    if _limite_alcanzado():
        log.warning("Límite diario de ejecuciones alcanzado (%s); se omite la búsqueda #%s",
                    _limite_diario(), busqueda_id)
        return
    _en_ejecucion.add(busqueda_id)
    db.registrar_ejecucion(busqueda_id)
    log.info("Ejecutando búsqueda #%s: %s", b["id"], b["consulta"])
    try:
        data = agent.buscar_ofertas(b["consulta"], b["ciudad"], b["pais"])
    except Exception as exc:
        log.exception("Falló la búsqueda #%s", busqueda_id)
        db.marcar_ejecutada(busqueda_id, None, error=str(exc))
        _en_ejecucion.discard(busqueda_id)
        return

    mejor_anterior = db.mejor_precio(busqueda_id)
    nuevas: list[dict] = []
    bajadas: list[tuple[dict, float]] = []
    for o in data["ofertas"]:
        if not o.get("url"):
            continue
        es_nueva, precio_anterior = db.upsert_oferta(busqueda_id, o)
        precio = o.get("precio_eur")
        if es_nueva:
            nuevas.append(o)
        elif precio is not None and precio_anterior is not None and precio < precio_anterior:
            bajadas.append((o, precio_anterior))
    db.marcar_ejecutada(busqueda_id, data["resumen"])
    _en_ejecucion.discard(busqueda_id)

    # Bajadas de precio en anuncios ya conocidos
    for o, antes in bajadas:
        precio = o["precio_eur"]
        extra = (" ¡Y es el nuevo mínimo de esta búsqueda!"
                 if mejor_anterior is not None and precio < mejor_anterior else "")
        _avisar(b, o, f"💶 Bajada de precio: {o['titulo']} — ahora {precio:.0f}€ "
                      f"(antes {antes:.0f}€).{extra}")

    if not nuevas:
        return

    if mejor_anterior is None:
        # Primera ejecución: avisar solo de la mejor oferta encontrada
        con_precio = [o for o in nuevas if o.get("precio_eur") is not None]
        if con_precio:
            mejor = min(con_precio, key=lambda o: o["precio_eur"])
            _avisar(b, mejor, f"🏆 Mejor oferta inicial: {mejor['titulo']} — {mejor['precio_eur']:.0f}€")
        return

    for o in nuevas:
        precio = o.get("precio_eur")
        if precio is not None and precio < mejor_anterior:
            _avisar(b, o, f"📉 ¡Nueva mejor oferta! {o['titulo']} — {precio:.0f}€ "
                          f"(antes el mínimo era {mejor_anterior:.0f}€)")
        elif o.get("es_chollo"):
            texto_precio = f"{precio:.0f}€" if precio is not None else "precio no especificado"
            _avisar(b, o, f"🔥 Posible chollo: {o['titulo']} — {texto_precio}")


def _avisar(busqueda, oferta: dict, mensaje: str) -> None:
    db.crear_aviso(busqueda["id"], mensaje, oferta.get("url"))
    notify.notificar(
        f"{mensaje}\n\n🔎 Búsqueda: {busqueda['consulta']}\n"
        f"📍 {oferta.get('ubicacion') or 'ubicación no especificada'}\n"
        f"💬 {oferta.get('motivo') or ''}\n{oferta.get('url') or ''}"
    )


# --- planificador ------------------------------------------------------------

async def _planificador() -> None:
    while True:
        try:
            for b in db.busquedas_pendientes():
                await asyncio.to_thread(ejecutar_busqueda, b["id"])
        except Exception:
            log.exception("Error en el planificador")
        await asyncio.sleep(INTERVALO_COMPROBACION_S)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    tarea = asyncio.create_task(_planificador())
    log.info("Planificador arrancado (comprueba cada %ss)", INTERVALO_COMPROBACION_S)
    yield
    tarea.cancel()


# --- autenticación opcional (WEB_PASSWORD) -----------------------------------

def _auth(request: Request) -> None:
    password = os.environ.get("WEB_PASSWORD")
    if not password:
        return
    cabecera = request.headers.get("authorization", "")
    if cabecera.startswith("Basic "):
        try:
            usuario_clave = base64.b64decode(cabecera[6:]).decode()
            if usuario_clave.split(":", 1)[-1] == password:
                return
        except Exception:
            pass
    raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Basic realm=agente"})


app = FastAPI(title="Agente de compras", lifespan=lifespan, dependencies=[Depends(_auth)])


# --- HTML --------------------------------------------------------------------

_CSS = """
body{font-family:system-ui,sans-serif;max-width:960px;margin:0 auto;padding:1rem;
     background:#111;color:#eee}
a{color:#7cc0ff} h1,h2{color:#fff} .muted{color:#999;font-size:.85rem}
table{border-collapse:collapse;width:100%;margin:.5rem 0}
td,th{border-bottom:1px solid #333;padding:.4rem .6rem;text-align:left;vertical-align:top}
form.inline{display:inline} input,select{background:#222;color:#eee;border:1px solid #444;
     border-radius:4px;padding:.4rem} button{background:#2563eb;color:#fff;border:0;
     border-radius:4px;padding:.4rem .8rem;cursor:pointer} button.rojo{background:#b91c1c}
button.gris{background:#444} .card{background:#1a1a1a;border:1px solid #333;
     border-radius:8px;padding:1rem;margin:.8rem 0} .chollo{color:#fbbf24}
.aviso{background:#1a2436;border:1px solid #2c3e5d;border-radius:6px;
     padding:.5rem .8rem;margin:.4rem 0}
"""


def _e(valor) -> str:
    return html.escape(str(valor)) if valor is not None else ""


def _pagina(titulo: str, cuerpo: str) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><html lang='es'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{_e(titulo)}</title><style>{_CSS}</style></head>"
        f"<body><h1>🛒 Agente de compras</h1>{cuerpo}</body></html>"
    )


@app.get("/", response_class=HTMLResponse)
def portada():
    filas = []
    for b in db.listar_busquedas():
        estado = "🟢 activa" if b["activa"] else "⏸️ pausada"
        if b["id"] in _en_ejecucion:
            estado = "⏳ buscando…"
        minimo = db.mejor_precio(b["id"])
        minimo_txt = f"{minimo:.0f}€" if minimo is not None else "—"
        error = (f"<div class='muted' style='color:#f87171'>⚠️ {_e(b['ultimo_error'])}</div>"
                 if b["ultimo_error"] else "")
        filas.append(
            f"<tr><td><a href='/busquedas/{b['id']}'>{_e(b['consulta'])}</a>"
            f"<div class='muted'>{_e(b['ciudad'] or '')} {_e(b['pais'])} · "
            f"cada {b['intervalo_horas']:g}h · última: {_e(b['ultima_ejecucion'] or 'nunca')}</div>"
            f"{error}</td>"
            f"<td>{estado}</td><td>{minimo_txt}</td>"
            f"<td>"
            f"<form class='inline' method='post' action='/busquedas/{b['id']}/ejecutar'>"
            f"<button>Buscar ahora</button></form> "
            f"<form class='inline' method='post' action='/busquedas/{b['id']}/alternar'>"
            f"<button class='gris'>{'Pausar' if b['activa'] else 'Reanudar'}</button></form> "
            f"<form class='inline' method='post' action='/busquedas/{b['id']}/borrar'"
            f" onsubmit='return confirm(\"¿Borrar esta búsqueda y sus ofertas?\")'>"
            f"<button class='rojo'>Borrar</button></form>"
            f"</td></tr>"
        )
    tabla = (f"<table><tr><th>Búsqueda</th><th>Estado</th><th>Mejor precio</th><th></th></tr>"
             f"{''.join(filas)}</table>") if filas else "<p class='muted'>Aún no hay búsquedas guardadas.</p>"

    avisos = "".join(
        f"<div class='aviso'>{_e(a['mensaje'])}"
        + (f" — <a href='{_e(a['url'])}' target='_blank'>ver anuncio</a>" if a["url"] else "")
        + f"<div class='muted'>{_e(a['consulta'] or '')} · {_e(a['creado'])}</div></div>"
        for a in db.avisos_recientes()
    ) or "<p class='muted'>Sin avisos todavía.</p>"

    formulario = """
    <div class='card'><h2>Nueva búsqueda vigilada</h2>
    <form method='post' action='/busquedas'>
      <p><input name='consulta' required size='60'
         placeholder='p. ej. caravana 4 plazas con baño, menos de 15.000€, máx. 10 años'></p>
      <p><input name='ciudad' placeholder='Ciudad'>
         <input name='pais' value='ES' size='3' maxlength='2'>
         cada <input name='intervalo_horas' type='number' value='6' min='1' max='168'
         step='0.5' style='width:4.5rem'> horas
         <button>Vigilar</button></p>
    </form></div>"""

    limite = _limite_diario()
    hoy = db.ejecuciones_hoy()
    if limite > 0 and hoy >= limite:
        gasto = (f"<div class='aviso' style='border-color:#7c2d12;background:#2a1a12'>"
                 f"⛔ Límite diario de ejecuciones alcanzado ({hoy}/{limite}). "
                 f"Las búsquedas se reanudarán mañana (00:00 UTC).</div>")
    elif limite > 0:
        gasto = f"<p class='muted'>Ejecuciones hoy: {hoy}/{limite}</p>"
    else:
        gasto = f"<p class='muted'>Ejecuciones hoy: {hoy} (sin límite)</p>"

    return _pagina("Agente de compras",
                   formulario + gasto
                   + f"<h2>Búsquedas</h2>{tabla}<h2>Avisos recientes</h2>{avisos}")


@app.get("/busquedas/{busqueda_id}", response_class=HTMLResponse)
def detalle(busqueda_id: int):
    b = db.obtener_busqueda(busqueda_id)
    if b is None:
        raise HTTPException(404)
    filas_lista = []
    for o in db.ofertas_de(busqueda_id):
        precio_txt = f"{o['precio']:.0f}€" if o["precio"] is not None else "—"
        chollo = " <span class='chollo'>🔥 chollo</span>" if o["es_chollo"] else ""
        historial = db.historial_precios(o["id"])
        if len(historial) > 1:
            cadena = " → ".join(
                f"{h['precio']:.0f}€ <span class='muted'>({h['visto'][:10]})</span>"
                for h in historial
            )
            precio_txt += f"<div class='muted'>Histórico: {cadena}</div>"
        filas_lista.append(
            f"<tr><td><a href='{_e(o['url'])}' target='_blank'>{_e(o['titulo'] or o['url'])}</a>"
            f"{chollo}<div class='muted'>{_e(o['motivo'] or '')}</div></td>"
            f"<td>{precio_txt}</td>"
            f"<td>{_e(o['ubicacion'] or '—')}</td><td>{_e(o['estado'] or '—')}</td>"
            f"<td class='muted'>{_e(o['primera_vez'][:10])}</td></tr>"
        )
    filas = "".join(filas_lista)
    tabla = (f"<table><tr><th>Oferta</th><th>Precio</th><th>Ubicación</th>"
             f"<th>Estado</th><th>Vista</th></tr>{filas}</table>"
             if filas else "<p class='muted'>Todavía no hay ofertas guardadas.</p>")
    resumen = (f"<div class='card'><b>Último resumen:</b><br>{_e(b['ultimo_resumen'])}</div>"
               if b["ultimo_resumen"] else "")
    return _pagina(b["consulta"],
                   f"<p><a href='/'>← volver</a></p><h2>{_e(b['consulta'])}</h2>"
                   f"<p class='muted'>{_e(b['ciudad'] or '')} {_e(b['pais'])} · "
                   f"cada {b['intervalo_horas']:g}h</p>{resumen}{tabla}")


@app.post("/busquedas")
def crear(consulta: str = Form(...), ciudad: str = Form(""),
          pais: str = Form("ES"), intervalo_horas: float = Form(6)):
    db.crear_busqueda(consulta.strip(), ciudad.strip(), pais.strip(), intervalo_horas)
    return RedirectResponse("/", status_code=303)


@app.post("/busquedas/{busqueda_id}/ejecutar")
def ejecutar_ahora(busqueda_id: int, tareas: BackgroundTasks):
    if db.obtener_busqueda(busqueda_id) is None:
        raise HTTPException(404)
    tareas.add_task(ejecutar_busqueda, busqueda_id)
    return RedirectResponse("/", status_code=303)


@app.post("/busquedas/{busqueda_id}/alternar")
def alternar(busqueda_id: int):
    db.alternar_activa(busqueda_id)
    return RedirectResponse("/", status_code=303)


@app.post("/busquedas/{busqueda_id}/borrar")
def borrar(busqueda_id: int):
    db.borrar_busqueda(busqueda_id)
    return RedirectResponse("/", status_code=303)
