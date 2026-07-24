"""Lógica de búsqueda: consulta la API de OpenAI con búsqueda web y devuelve
las ofertas encontradas en formato estructurado (JSON) para poder compararlas
entre ejecuciones."""

from __future__ import annotations

import json
import os

from openai import OpenAI

MODEL = os.environ.get("OPENAI_MODEL", "gpt-5")

INSTRUCCIONES = """\
Eres un agente experto en compras. Busca en internet ofertas reales y actuales
del producto que pide el usuario.

Método:
1. Haz varias búsquedas web con distintos enfoques: portales de compraventa
   (Milanuncios, Wallapop, coches.net, Autocasion, Amazon, Idealo, etc. según
   el producto), tiendas oficiales y comparadores de precios.
2. Prioriza resultados cercanos a la ubicación del usuario; si hay pocos,
   amplía el radio.
3. Verifica que cada oferta cumple las especificaciones pedidas; descarta las
   que no cumplan. No inventes datos: si algo no aparece en el anuncio, usa null.
4. Marca como chollo (es_chollo=true) solo las ofertas claramente por debajo
   del precio de mercado para su estado y antigüedad.

Devuelve entre 3 y 10 ofertas con su URL real (el enlace directo al anuncio,
nunca la portada del portal). En "motivo" explica en una frase por qué la
oferta es buena o qué pega tiene. En "resumen" describe brevemente el estado
del mercado y cuál es la mejor opción."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["ofertas", "resumen"],
    "properties": {
        "resumen": {"type": "string"},
        "ofertas": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "titulo", "precio_eur", "ubicacion", "estado",
                    "url", "es_chollo", "motivo",
                ],
                "properties": {
                    "titulo": {"type": "string"},
                    "precio_eur": {"type": ["number", "null"]},
                    "ubicacion": {"type": ["string", "null"]},
                    "estado": {"type": ["string", "null"]},
                    "url": {"type": "string"},
                    "es_chollo": {"type": "boolean"},
                    "motivo": {"type": "string"},
                },
            },
        },
    },
}


def _tool_busqueda_web(ciudad: str | None, pais: str) -> dict:
    location: dict = {"type": "approximate", "country": pais or "ES"}
    if ciudad:
        location["city"] = ciudad
    return {"type": "web_search", "user_location": location}


def _extraer_json(texto: str) -> dict:
    """Fallback por si el modelo envuelve el JSON en texto."""
    inicio = texto.find("{")
    fin = texto.rfind("}")
    if inicio == -1 or fin == -1:
        raise ValueError(f"La respuesta no contiene JSON: {texto[:200]}")
    return json.loads(texto[inicio:fin + 1])


def buscar_ofertas(consulta: str, ciudad: str | None, pais: str) -> dict:
    """Ejecuta una búsqueda y devuelve {"ofertas": [...], "resumen": "..."}."""
    client = OpenAI()
    entrada = consulta
    if ciudad:
        entrada = f"(Mi ubicación: {ciudad}, {pais}) {consulta}"

    response = client.responses.create(
        model=MODEL,
        instructions=INSTRUCCIONES,
        input=entrada,
        tools=[_tool_busqueda_web(ciudad, pais)],
        text={
            "format": {
                "type": "json_schema",
                "name": "resultado_busqueda",
                "strict": True,
                "schema": SCHEMA,
            }
        },
    )
    try:
        data = json.loads(response.output_text)
    except json.JSONDecodeError:
        data = _extraer_json(response.output_text)

    data.setdefault("ofertas", [])
    data.setdefault("resumen", "")
    return data
