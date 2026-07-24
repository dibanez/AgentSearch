"""Web panel + scheduler for periodic searches.

Start with:  uvicorn shopping_agent.web:app --host 0.0.0.0 --port 8000
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
log = logging.getLogger("agent")

CHECK_INTERVAL_S = 60  # how often the scheduler looks for searches that are due
_running: set[int] = set()


def _daily_limit() -> int:
    """Maximum number of runs (API calls) per day. 0 = unlimited."""
    # MAX_EJECUCIONES_DIA is the old variable name, still read for compatibility
    # with existing deployments.
    raw = os.environ.get("MAX_RUNS_PER_DAY") or os.environ.get("MAX_EJECUCIONES_DIA", "24")
    try:
        return int(raw)
    except ValueError:
        return 24


def _limit_reached() -> bool:
    limit = _daily_limit()
    return limit > 0 and db.runs_today() >= limit


# --- search radius -----------------------------------------------------------

def _query_from_form(value: str) -> str:
    """Normalise the multiline form text (Windows line breaks)."""
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def _radius_from_form(value: str) -> float | None:
    """Parse the "km" form field. Empty or invalid = no limit."""
    value = (value or "").strip().replace(",", ".")
    if not value:
        return None
    try:
        km = float(value)
    except ValueError:
        return None
    return km if km > 0 else None


def _distance(offer: dict) -> float | None:
    value = offer.get("distance_km")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _filter_by_radius(offers: list[dict], radius_km: float | None) -> tuple[list[dict], int]:
    """Drop the offers whose known distance is beyond the radius.

    The model is not guaranteed to respect the radius, so we filter here too.
    Offers with no deducible distance are kept (the panel marks them as "sin
    confirmar") so that good but badly located listings are not lost.
    """
    if not radius_km:
        return list(offers), 0
    kept, dropped = [], 0
    for o in offers:
        distance = _distance(o)
        if distance is not None and distance > radius_km:
            dropped += 1
            continue
        kept.append(o)
    return kept, dropped


# --- product condition (nuevo / usado) ---------------------------------------

CONDITIONS = ("nuevo", "usado")


def _condition_from_form(value: str) -> str | None:
    """Parse the condition selector. Empty or unknown = don't care."""
    value = (value or "").strip().lower()
    return value if value in CONDITIONS else None


def _condition(offer: dict) -> str | None:
    """Normalised condition of the offer: "nuevo", "usado" or None."""
    value = offer.get("condition")
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value if value in CONDITIONS else None


def _filter_by_condition(offers: list[dict], wanted_condition: str | None) -> tuple[list[dict], int]:
    """Drop the offers whose known condition is not the requested one.

    Same criterion as with the radius: what is unknown is not dropped (the
    panel marks it as "sin confirmar"), because many listings do not say
    whether the product is new or second-hand.
    """
    if not wanted_condition:
        return list(offers), 0
    kept, dropped = [], 0
    for o in offers:
        condition = _condition(o)
        if condition is not None and condition != wanted_condition:
            dropped += 1
            continue
        kept.append(o)
    return kept, dropped


def _readable_error(exc: Exception) -> str:
    """Short message for the panel, without the whole API dump."""
    if isinstance(exc, agent.APIStatusError):
        if exc.status_code >= 500:
            return (f"Error temporal de OpenAI ({exc.status_code}): su servidor falló al "
                    f"procesar la petición. Se reintentó sin éxito; se volverá a "
                    f"intentar en la siguiente ejecución.")
        if exc.status_code == 429:
            return ("Límite de peticiones o saldo de OpenAI agotado (429). Revisa el "
                    "crédito de tu cuenta de OpenAI.")
        if exc.status_code == 401:
            return "OPENAI_API_KEY no válida (401)."
        return f"La API de OpenAI respondió {exc.status_code}: {exc}"
    if isinstance(exc, (agent.APIConnectionError, agent.APITimeoutError)):
        return f"No se pudo contactar con la API de OpenAI: {exc}"
    return str(exc)


# --- core: run one search and generate alerts --------------------------------

def run_search(search_id: int) -> None:
    b = db.get_search(search_id)
    if b is None or search_id in _running:
        return
    if _limit_reached():
        log.warning("Daily run limit reached (%s); skipping search #%s",
                    _daily_limit(), search_id)
        return
    _running.add(search_id)
    log.info("Running search #%s: %s", b["id"], b["consulta"])
    try:
        data = agent.search_offers(b["consulta"], b["ciudad"], b["pais"],
                                   b["radio_km"], b["estado_deseado"])
    except Exception as exc:
        # A failed call does not consume quota: the daily counter only counts
        # the searches the API actually served.
        log.exception("Search #%s failed", search_id)
        db.mark_run(search_id, None, error=_readable_error(exc))
        _running.discard(search_id)
        return
    db.record_run(search_id)

    offers, out_of_radius = _filter_by_radius(data["offers"], b["radio_km"])
    offers, wrong_condition = _filter_by_condition(offers, b["estado_deseado"])
    discarded = []
    if out_of_radius:
        discarded.append(f"{out_of_radius} por estar a más de {b['radio_km']:g} km de "
                         f"{b['ciudad'] or 'tu ubicación'}")
    if wrong_condition:
        discarded.append(f"{wrong_condition} por no ser producto {b['estado_deseado']}")
    summary = data["summary"]
    if discarded:
        summary = f"{summary} · Ofertas descartadas: {'; '.join(discarded)}."
        log.info("Search #%s: discarded %s", search_id, "; ".join(discarded))

    previous_best = db.best_price(search_id)
    new_offers: list[dict] = []
    price_drops: list[tuple[dict, float]] = []
    for o in offers:
        if not o.get("url"):
            continue
        o["condition"] = _condition(o)  # only canonical values are stored
        is_new, previous_price = db.upsert_offer(search_id, o)
        price = o.get("price_eur")
        if is_new:
            new_offers.append(o)
        elif price is not None and previous_price is not None and price < previous_price:
            price_drops.append((o, previous_price))
    db.mark_run(search_id, summary)
    _running.discard(search_id)

    # Price drops on listings we already knew about
    for o, before in price_drops:
        price = o["price_eur"]
        extra = (" ¡Y es el nuevo mínimo de esta búsqueda!"
                 if previous_best is not None and price < previous_best else "")
        _alert(b, o, f"💶 Bajada de precio: {o['title']} — ahora {price:.0f}€ "
                     f"(antes {before:.0f}€).{extra}")

    if not new_offers:
        return

    if previous_best is None:
        # First run: only alert about the best offer found
        with_price = [o for o in new_offers if o.get("price_eur") is not None]
        if with_price:
            best = min(with_price, key=lambda o: o["price_eur"])
            _alert(b, best, f"🏆 Mejor oferta inicial: {best['title']} — {best['price_eur']:.0f}€")
        return

    for o in new_offers:
        price = o.get("price_eur")
        if price is not None and price < previous_best:
            _alert(b, o, f"📉 ¡Nueva mejor oferta! {o['title']} — {price:.0f}€ "
                         f"(antes el mínimo era {previous_best:.0f}€)")
        elif o.get("is_bargain"):
            price_text = f"{price:.0f}€" if price is not None else "precio no especificado"
            _alert(b, o, f"🔥 Posible chollo: {o['title']} — {price_text}")


def _alert(search, offer: dict, message: str) -> None:
    db.create_alert(search["id"], message, offer.get("url"))
    distance = _distance(offer)
    place = offer.get("location") or "ubicación no especificada"
    if distance is not None:
        place += f" (a {distance:.0f} km)"
    notify.send(
        f"{message}\n\n🔎 Búsqueda: {search['consulta']}\n"
        f"📍 {place}\n"
        f"💬 {offer.get('reason') or ''}\n{offer.get('url') or ''}"
    )


# --- scheduler ---------------------------------------------------------------

async def _scheduler() -> None:
    while True:
        try:
            for b in db.due_searches():
                await asyncio.to_thread(run_search, b["id"])
        except Exception:
            log.exception("Scheduler error")
        await asyncio.sleep(CHECK_INTERVAL_S)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    task = asyncio.create_task(_scheduler())
    log.info("Scheduler started (checks every %ss)", CHECK_INTERVAL_S)
    yield
    task.cancel()


# --- optional authentication (WEB_PASSWORD) ----------------------------------

def _auth(request: Request) -> None:
    password = os.environ.get("WEB_PASSWORD")
    if not password:
        return
    header = request.headers.get("authorization", "")
    if header.startswith("Basic "):
        try:
            user_pass = base64.b64decode(header[6:]).decode()
            if user_pass.split(":", 1)[-1] == password:
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
form.inline{display:inline} input,select,textarea{background:#222;color:#eee;
     border:1px solid #444;border-radius:4px;padding:.4rem;font:inherit}
textarea{width:100%;max-width:100%;box-sizing:border-box;resize:vertical}
button{background:#2563eb;color:#fff;border:0;
     border-radius:4px;padding:.4rem .8rem;cursor:pointer} button.red{background:#b91c1c}
button.grey{background:#444} .card{background:#1a1a1a;border:1px solid #333;
     border-radius:8px;padding:1rem;margin:.8rem 0} .bargain{color:#fbbf24}
.alert{background:#1a2436;border:1px solid #2c3e5d;border-radius:6px;
     padding:.5rem .8rem;margin:.4rem 0}
"""


def _e(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _search_filters(search) -> str:
    """Search filters: city, country, radius and product condition."""
    parts = [p for p in (search["ciudad"], search["pais"]) if p]
    area = " ".join(_e(p) for p in parts)
    km = f"≤ {search['radio_km']:g} km" if search["radio_km"] else "sin límite de km"
    condition = (f"solo {_e(search['estado_deseado'])}" if search["estado_deseado"]
                 else "nuevo o usado")
    return f"{area} · {km} · {condition}"


def _condition_options(selected: str | None) -> str:
    options = [("", "Estado: indiferente"), ("nuevo", "Solo nuevo"), ("usado", "Solo usado")]
    return "".join(
        f"<option value='{value}'{' selected' if value == (selected or '') else ''}>"
        f"{label}</option>"
        for value, label in options
    )


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><html lang='es'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{_e(title)}</title><style>{_CSS}</style></head>"
        f"<body><h1>🛒 Agente de compras</h1>{body}</body></html>"
    )


@app.get("/", response_class=HTMLResponse)
def index():
    rows = []
    for b in db.list_searches():
        status = "🟢 activa" if b["activa"] else "⏸️ pausada"
        if b["id"] in _running:
            status = "⏳ buscando…"
        lowest = db.best_price(b["id"])
        lowest_text = f"{lowest:.0f}€" if lowest is not None else "—"
        error = (f"<div class='muted' style='color:#f87171'>⚠️ {_e(b['ultimo_error'])}</div>"
                 if b["ultimo_error"] else "")
        rows.append(
            f"<tr><td><a href='/searches/{b['id']}'>{_e(b['consulta'])}</a>"
            f"<div class='muted'>{_search_filters(b)} · "
            f"cada {b['intervalo_horas']:g}h · última: {_e(b['ultima_ejecucion'] or 'nunca')}</div>"
            f"{error}</td>"
            f"<td>{status}</td><td>{lowest_text}</td>"
            f"<td>"
            f"<form class='inline' method='post' action='/searches/{b['id']}/run'>"
            f"<button>Buscar ahora</button></form> "
            f"<form class='inline' method='post' action='/searches/{b['id']}/toggle'>"
            f"<button class='grey'>{'Pausar' if b['activa'] else 'Reanudar'}</button></form> "
            f"<form class='inline' method='post' action='/searches/{b['id']}/delete'"
            f" onsubmit='return confirm(\"¿Borrar esta búsqueda y sus ofertas?\")'>"
            f"<button class='red'>Borrar</button></form>"
            f"</td></tr>"
        )
    table = (f"<table><tr><th>Búsqueda</th><th>Estado</th><th>Mejor precio</th><th></th></tr>"
             f"{''.join(rows)}</table>") if rows else "<p class='muted'>Aún no hay búsquedas guardadas.</p>"

    alerts = "".join(
        f"<div class='alert'>{_e(a['mensaje'])}"
        + (f" — <a href='{_e(a['url'])}' target='_blank'>ver anuncio</a>" if a["url"] else "")
        + f"<div class='muted'>{_e(a['consulta'] or '')} · {_e(a['creado'])}</div></div>"
        for a in db.recent_alerts()
    ) or "<p class='muted'>Sin avisos todavía.</p>"

    form_html = f"""
    <div class='card'><h2>Nueva búsqueda vigilada</h2>
    <form method='post' action='/searches'>
      <p><textarea name='query' required rows='4'
         placeholder='p. ej. caravana 4 plazas con baño, menos de 15.000€, máx. 10 años,&#10;con calefacción y toldo, preferible Knaus o Hobby'></textarea></p>
      <p><input name='city' placeholder='Ciudad'>
         <input name='radius_km' type='number' min='1' step='any'
         placeholder='km' style='width:5.5rem'
         title='Radio de búsqueda en km. Vacío = sin límite de distancia'>
         <input name='country' value='ES' size='3' maxlength='2'>
         <select name='wanted_condition'>{_condition_options(None)}</select>
         cada <input name='interval_hours' type='number' value='6' min='1' max='168'
         step='0.5' style='width:4.5rem'> horas
         <button>Vigilar</button></p>
      <p class='muted'>Los <b>km</b> limitan la búsqueda a ese radio alrededor de la
      ciudad. Si lo dejas vacío, busca sin límite de distancia priorizando lo más
      cercano. El <b>estado</b> filtra por producto nuevo o de segunda mano
      (reacondicionado y de exposición cuentan como usado).</p>
    </form></div>"""

    limit = _daily_limit()
    today = db.runs_today()
    if limit > 0 and today >= limit:
        usage = (f"<div class='alert' style='border-color:#7c2d12;background:#2a1a12'>"
                 f"⛔ Límite diario de ejecuciones alcanzado ({today}/{limit}). "
                 f"Las búsquedas se reanudarán mañana (00:00 UTC).</div>")
    elif limit > 0:
        usage = f"<p class='muted'>Ejecuciones hoy: {today}/{limit}</p>"
    else:
        usage = f"<p class='muted'>Ejecuciones hoy: {today} (sin límite)</p>"

    telegram = ""
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        telegram = ("<form class='inline' method='post' action='/telegram/test'>"
                    "<button class='grey'>Probar Telegram</button></form>")

    return _page("Agente de compras",
                 form_html + usage + telegram
                 + f"<h2>Búsquedas</h2>{table}<h2>Avisos recientes</h2>{alerts}")


@app.get("/searches/{search_id}", response_class=HTMLResponse)
def detail(search_id: int):
    b = db.get_search(search_id)
    if b is None:
        raise HTTPException(404)
    row_list = []
    for o in db.offers_of(search_id):
        price_text = f"{o['precio']:.0f}€" if o["precio"] is not None else "—"
        bargain = " <span class='bargain'>🔥 chollo</span>" if o["es_chollo"] else ""
        history = db.price_history(o["id"])
        if len(history) > 1:
            chain = " → ".join(
                f"{h['precio']:.0f}€ <span class='muted'>({h['visto'][:10]})</span>"
                for h in history
            )
            price_text += f"<div class='muted'>Histórico: {chain}</div>"
        if o["distancia_km"] is not None:
            distance_text = f"{o['distancia_km']:.0f} km"
        elif b["radio_km"]:
            distance_text = "<span class='muted'>sin confirmar</span>"
        else:
            distance_text = "—"
        condition_text = _e(o["estado"] or "—")
        if o["condicion"]:
            condition_text += f"<div class='muted'>{_e(o['condicion'])}</div>"
        elif b["estado_deseado"]:
            condition_text += "<div class='muted'>sin confirmar</div>"
        row_list.append(
            f"<tr><td><a href='{_e(o['url'])}' target='_blank'>{_e(o['titulo'] or o['url'])}</a>"
            f"{bargain}<div class='muted'>{_e(o['motivo'] or '')}</div></td>"
            f"<td>{price_text}</td>"
            f"<td>{_e(o['ubicacion'] or '—')}</td><td>{distance_text}</td>"
            f"<td>{condition_text}</td>"
            f"<td class='muted'>{_e(o['primera_vez'][:10])}</td></tr>"
        )
    rows = "".join(row_list)
    table = (f"<table><tr><th>Oferta</th><th>Precio</th><th>Ubicación</th>"
             f"<th>Distancia</th><th>Estado</th><th>Vista</th></tr>{rows}</table>"
             if rows else "<p class='muted'>Todavía no hay ofertas guardadas.</p>")
    summary = (f"<div class='card'><b>Último resumen:</b><br>{_e(b['ultimo_resumen'])}</div>"
               if b["ultimo_resumen"] else "")
    radius_value = f"{b['radio_km']:g}" if b["radio_km"] else ""
    edit_form = f"""
    <details class='card'><summary>✏️ Editar búsqueda</summary>
    <form method='post' action='/searches/{b['id']}/edit'>
      <p><textarea name='query' required rows='4'>{_e(b['consulta'])}</textarea></p>
      <p><input name='city' placeholder='Ciudad' value='{_e(b['ciudad'] or '')}'>
         <input name='radius_km' type='number' min='1' step='any'
         placeholder='km' style='width:5.5rem'
         value='{radius_value}'
         title='Radio de búsqueda en km. Vacío = sin límite de distancia'>
         <input name='country' value='{_e(b['pais'])}' size='3' maxlength='2'>
         <select name='wanted_condition'>{_condition_options(b['estado_deseado'])}</select>
         cada <input name='interval_hours' type='number' value='{b['intervalo_horas']:g}'
         min='1' max='168' step='0.5' style='width:4.5rem'> horas
         <button>Guardar cambios</button></p>
      <p class='muted'>Deja los <b>km</b> vacíos para buscar sin límite de distancia.
      Se conservan el histórico de ofertas y precios. Si cambias mucho la consulta,
      valora crear una búsqueda nueva para no mezclar resultados.</p>
    </form></details>"""
    return _page(b["consulta"],
                 f"<p><a href='/'>← volver</a></p>"
                 f"<h2 style='white-space:pre-line'>{_e(b['consulta'])}</h2>"
                 f"<p class='muted'>{_search_filters(b)} · "
                 f"cada {b['intervalo_horas']:g}h</p>{edit_form}{summary}{table}")


@app.post("/searches")
def create(query: str = Form(...), city: str = Form(""), radius_km: str = Form(""),
           country: str = Form("ES"), wanted_condition: str = Form(""),
           interval_hours: float = Form(6)):
    db.create_search(_query_from_form(query), city.strip(),
                     country.strip(), interval_hours,
                     _radius_from_form(radius_km),
                     _condition_from_form(wanted_condition))
    return RedirectResponse("/", status_code=303)


@app.post("/searches/{search_id}/run")
def run_now(search_id: int, tasks: BackgroundTasks):
    if db.get_search(search_id) is None:
        raise HTTPException(404)
    tasks.add_task(run_search, search_id)
    return RedirectResponse("/", status_code=303)


@app.post("/searches/{search_id}/edit")
def edit(search_id: int, query: str = Form(...), city: str = Form(""),
         radius_km: str = Form(""), country: str = Form("ES"),
         wanted_condition: str = Form(""), interval_hours: float = Form(6)):
    if db.get_search(search_id) is None:
        raise HTTPException(404)
    db.update_search(search_id, _query_from_form(query), city.strip(),
                     country.strip(), interval_hours,
                     _radius_from_form(radius_km),
                     _condition_from_form(wanted_condition))
    return RedirectResponse(f"/searches/{search_id}", status_code=303)


@app.post("/telegram/test", response_class=HTMLResponse)
def test_telegram():
    ok, detail = notify.send_test()
    if ok:
        body = "<div class='alert'>✅ Mensaje de prueba enviado. Mira tu Telegram.</div>"
    else:
        body = (f"<div class='alert' style='border-color:#7c2d12;background:#2a1a12'>"
                f"❌ Telegram respondió: <b>{_e(detail)}</b></div>"
                "<p class='muted'>Causas habituales: <b>chat not found</b> → el "
                "TELEGRAM_CHAT_ID no es correcto o aún no has escrito ningún mensaje "
                "a tu bot (escríbele /start y vuelve a mirar tu chat id en "
                "<code>https://api.telegram.org/bot&lt;TOKEN&gt;/getUpdates</code>); "
                "<b>unauthorized</b> → el TELEGRAM_BOT_TOKEN no es válido.</p>")
    return _page("Prueba de Telegram", f"<p><a href='/'>← volver</a></p>{body}")


@app.post("/searches/{search_id}/toggle")
def toggle(search_id: int):
    db.toggle_active(search_id)
    return RedirectResponse("/", status_code=303)


@app.post("/searches/{search_id}/delete")
def delete(search_id: int):
    db.delete_search(search_id)
    return RedirectResponse("/", status_code=303)
