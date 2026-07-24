"""Search logic: queries the OpenAI API with web search enabled and returns the
offers it finds in a structured format (JSON) so they can be compared between
runs."""

from __future__ import annotations

import json
import logging
import os
import time

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)

log = logging.getLogger(__name__)

MODEL = os.environ.get("OPENAI_MODEL", "gpt-5")
BASE_BACKOFF_S = 2  # wait before the first retry; doubles on every attempt

INSTRUCTIONS = """\
Eres un agente experto en compras. Busca en internet ofertas reales y actuales
del producto que pide el usuario.

Método:
1. Haz varias búsquedas web con distintos enfoques: portales de compraventa
   (Milanuncios, Wallapop, coches.net, Autocasion, Amazon, Idealo, etc. según
   el producto), tiendas oficiales y comparadores de precios.
2. Respeta la zona de búsqueda indicada más abajo.
3. Verifica que cada oferta cumple las especificaciones pedidas; descarta las
   que no cumplan. No inventes datos: si algo no aparece en el anuncio, usa null.
4. Marca como chollo (is_bargain=true) solo las ofertas claramente por debajo
   del precio de mercado para su estado y antigüedad.

Devuelve entre 3 y 10 ofertas con su URL real (el enlace directo al anuncio,
nunca la portada del portal). En "reason" explica en una frase por qué la
oferta es buena o qué pega tiene. En "summary" describe brevemente el estado
del mercado y cuál es la mejor opción."""


def _condition_block(wanted_condition: str | None) -> str:
    """Instruction block about the wanted product condition (nuevo/usado)."""
    if wanted_condition == "nuevo":
        return (
            "\n\nEstado del producto (OBLIGATORIO): SOLO producto nuevo, sin estrenar. "
            "Busca en tiendas, distribuidores oficiales y outlets, y descarta los "
            "anuncios de segunda mano. Ojo: reacondicionado, de exposición, "
            "seminuevo o 'como nuevo' NO son nuevos; descártalos."
        )
    if wanted_condition == "usado":
        return (
            "\n\nEstado del producto (OBLIGATORIO): SOLO producto de segunda mano. "
            "Busca en portales de compraventa entre particulares y en venta de "
            "ocasión, y descarta el producto nuevo a estrenar. Reacondicionado, de "
            "exposición y seminuevo SÍ valen: cuentan como usados."
        )
    return ("\n\nEstado del producto: indiferente, vale nuevo y de segunda mano; "
            "compara ambas opciones.")


def _instructions(city: str | None, radius_km: float | None,
                  wanted_condition: str | None = None) -> str:
    """Agent instructions with the search area and the condition applied."""
    reference = city or "la ubicación del usuario"
    if radius_km:
        area = (
            f"\n\nZona de búsqueda (OBLIGATORIO): incluye SOLO ofertas situadas a "
            f"{radius_km:g} km o menos de {reference}. Descarta las que estén más "
            f"lejos aunque el precio sea mejor, y NO amplíes el radio por tu cuenta: "
            f"si dentro del radio hay pocas opciones, dilo en el resumen."
        )
    else:
        area = (
            f"\n\nZona de búsqueda: sin límite de distancia. Prioriza lo más cercano a "
            f"{reference} cuando precio y estado sean comparables, y amplía el alcance "
            f"si cerca hay pocas opciones (indícalo en el resumen)."
        )
    return INSTRUCTIONS + area + _condition_block(wanted_condition) + (
        f"\n\nEn \"distance_km\" indica la distancia aproximada en km desde "
        f"{reference} hasta la ubicación del anuncio. Si el anuncio no permite "
        f"deducir dónde está, usa null: no la inventes ni la estimes a ojo."
        f"\n\nEn \"condition\" clasifica la oferta con exactamente una de estas dos "
        f"palabras: \"nuevo\" (sin estrenar) o \"usado\" (segunda mano, incluidos "
        f"reacondicionado, de exposición y seminuevo). Si el anuncio no lo deja "
        f"claro, usa null. En \"condition_text\" sigue poniendo el texto del anuncio "
        f"(\"como nuevo, 2 dueños\", \"precintado\"…)."
    )

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["offers", "summary"],
    "properties": {
        "summary": {"type": "string"},
        "offers": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "title", "price_eur", "location", "distance_km", "condition_text",
                    "condition", "url", "is_bargain", "reason",
                ],
                "properties": {
                    "title": {"type": "string"},
                    "price_eur": {"type": ["number", "null"]},
                    "location": {"type": ["string", "null"]},
                    "distance_km": {"type": ["number", "null"]},
                    "condition_text": {"type": ["string", "null"]},
                    "condition": {
                        "type": ["string", "null"],
                        "description": "'nuevo' o 'usado'; null si no está claro",
                    },
                    "url": {"type": "string"},
                    "is_bargain": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
            },
        },
    },
}


def _web_search_tool(city: str | None, country: str) -> dict:
    location: dict = {"type": "approximate", "country": country or "ES"}
    if city:
        location["city"] = city
    return {"type": "web_search", "user_location": location}


def _retries() -> int:
    """Total number of attempts per search (1 = no retries)."""
    try:
        # The old name REINTENTOS_API is still read for compatibility.
        raw = os.environ.get("API_RETRIES") or os.environ.get("REINTENTOS_API", "3")
        return max(1, int(raw))
    except ValueError:
        return 3


def _is_transient(exc: Exception) -> bool:
    """Is it worth retrying? OpenAI server failures (5xx), rate limits and
    network problems are; a 400 from a malformed request is not."""
    if isinstance(exc, (APIConnectionError, APITimeoutError, RateLimitError)):
        return True
    return isinstance(exc, APIStatusError) and exc.status_code >= 500


def _create_response(client: OpenAI, **kwargs):
    """Calls the API, retrying transient errors with an increasing backoff."""
    attempts = _retries()
    for attempt in range(1, attempts + 1):
        try:
            return client.responses.create(**kwargs)
        except Exception as exc:
            if attempt == attempts or not _is_transient(exc):
                raise
            wait = BASE_BACKOFF_S * 2 ** (attempt - 1)
            log.warning("Transient API error (%s: %s). Retry %s/%s in %ss",
                        exc.__class__.__name__, exc, attempt + 1, attempts, wait)
            time.sleep(wait)


def _extract_json(text: str) -> dict:
    """Fallback in case the model wraps the JSON in text."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"La respuesta no contiene JSON: {text[:200]}")
    return json.loads(text[start:end + 1])


def search_offers(query: str, city: str | None, country: str,
                  radius_km: float | None = None,
                  wanted_condition: str | None = None) -> dict:
    """Runs a search and returns {"offers": [...], "summary": "..."}.

    `radius_km` limits the search to that radius around `city`; with None the
    search has no distance limit and simply prioritises the closest results.
    `wanted_condition` ("nuevo"/"usado"/None) restricts the product condition.
    """
    client = OpenAI()
    context = []
    if city:
        context.append(f"Mi ubicación: {city}, {country}")
    if radius_km:
        context.append(f"radio máximo: {radius_km:g} km")
    if wanted_condition:
        context.append(f"solo producto {wanted_condition}")
    user_input = f"({' · '.join(context)}) {query}" if context else query

    response = _create_response(
        client,
        model=MODEL,
        instructions=_instructions(city, radius_km, wanted_condition),
        input=user_input,
        tools=[_web_search_tool(city, country)],
        text={
            "format": {
                "type": "json_schema",
                "name": "search_result",
                "strict": True,
                "schema": SCHEMA,
            }
        },
    )
    try:
        data = json.loads(response.output_text)
    except json.JSONDecodeError:
        data = _extract_json(response.output_text)

    data.setdefault("offers", [])
    data.setdefault("summary", "")
    return data
