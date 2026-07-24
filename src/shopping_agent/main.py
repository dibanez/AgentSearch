"""Shopping agent: searches the internet for the best price and the best quality
for the product you want to buy, prioritising offers near your location.

Uses the OpenAI API (Responses API) with the built-in web search tool.
"""

from __future__ import annotations

import os
import sys

from openai import OpenAI
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

MODEL = os.environ.get("OPENAI_MODEL", "gpt-5")

INSTRUCTIONS = """\
Eres un agente experto en compras. Tu trabajo es encontrar el mejor producto \
para el usuario buscando en internet ofertas reales y actuales.

Método de trabajo:
1. Haz varias búsquedas web con distintos enfoques: portales de compraventa \
(Milanuncios, Wallapop, coches.net, Autocasion, Amazon, Idealo, etc. según el \
producto), concesionarios o tiendas oficiales, y comparadores de precios.
2. Prioriza resultados cercanos a la ubicación del usuario. Si hay pocas \
opciones cerca, amplía el radio y dilo claramente. Si el usuario indica un \
radio máximo en km, NO lo superes: descarta los anuncios que queden fuera \
aunque tengan mejor precio. Si pide solo producto nuevo o solo de segunda \
mano, respétalo (reacondicionado y de exposición cuentan como usados).
3. Verifica que cada oferta cumple las especificaciones pedidas. Descarta las \
que no cumplan y no te inventes datos: si un dato no aparece en el anuncio, \
márcalo como "no especificado".
4. Evalúa la relación calidad-precio: estado, antigüedad, marca, reputación \
del vendedor, garantía, y compara el precio con el precio medio de mercado.

Formato de respuesta (en español, en Markdown):
- Una tabla con las 5-8 mejores opciones: nombre/modelo, precio, ubicación, \
distancia aproximada, estado, y enlace al anuncio.
- Después de la tabla, tu recomendación razonada: la mejor opción en \
calidad-precio, la más barata que cumple los requisitos, y avisos (precios \
sospechosamente bajos, anuncios antiguos, etc.).
- Incluye siempre los enlaces reales de los anuncios que encontraste.

Si la petición del usuario es ambigua (falta presupuesto, especificaciones \
clave, o ubicación), pregunta antes de buscar."""


def _web_search_tool(city: str | None, country: str) -> dict:
    tool: dict = {"type": "web_search"}
    location: dict = {"type": "approximate", "country": country}
    if city:
        location["city"] = city
    tool["user_location"] = location
    return tool


def ask(client: OpenAI, console: Console, tools: list[dict],
        text: str, previous_id: str | None) -> str:
    """Send a turn to the model, show the progress and return the response.id."""
    with console.status("[bold cyan]Buscando en internet...", spinner="dots"):
        response = client.responses.create(
            model=MODEL,
            instructions=INSTRUCTIONS,
            input=text,
            tools=tools,
            previous_response_id=previous_id,
        )
    console.print()
    console.print(Markdown(response.output_text))
    console.print()
    return response.id


def main() -> None:
    console = Console()

    if not os.environ.get("OPENAI_API_KEY"):
        console.print("[red]Falta la variable de entorno OPENAI_API_KEY.[/red]")
        console.print("Ejecuta:  export OPENAI_API_KEY='sk-...'")
        sys.exit(1)

    client = OpenAI()

    console.print(Panel.fit(
        "[bold]🛒 Agente de compras[/bold]\n"
        "Dime qué quieres comprar, con qué especificaciones y presupuesto,\n"
        "y buscaré el mejor precio y calidad cerca de ti.",
        border_style="cyan",
    ))

    city = Prompt.ask("📍 ¿En qué ciudad estás?", default="")
    radius_km = Prompt.ask("📏 Radio de búsqueda en km (vacío = sin límite)", default="")
    condition = Prompt.ask("🏷️ Estado del producto", choices=["indiferente", "nuevo", "usado"],
                           default="indiferente")
    country = Prompt.ask("🌍 País (código de 2 letras)", default="ES").upper()
    tools = [_web_search_tool(city or None, country)]

    console.print(
        "\nEjemplo: [dim]quiero una caravana de segunda mano para 4 personas, "
        "con baño, menos de 15.000€ y máximo 10 años de antigüedad[/dim]\n"
        "Escribe [bold]salir[/bold] para terminar.\n"
    )

    previous_id: str | None = None
    while True:
        try:
            text = Prompt.ask("[bold green]Tú[/bold green]")
        except (EOFError, KeyboardInterrupt):
            break
        if not text.strip():
            continue
        if text.strip().lower() in {"salir", "exit", "quit"}:
            break

        if previous_id is None:
            context = []
            if city:
                context.append(f"Mi ubicación: {city}, {country}")
            if radius_km.strip():
                context.append(f"radio máximo: {radius_km.strip()} km")
            if condition != "indiferente":
                context.append(f"solo producto {condition}")
            if context:
                text = f"({' · '.join(context)}) {text}"

        try:
            previous_id = ask(client, console, tools, text, previous_id)
        except Exception as exc:  # noqa: BLE001 — show the error and keep looping
            console.print(f"[red]Error al consultar la API:[/red] {exc}")

    console.print("¡Hasta luego! 👋")


if __name__ == "__main__":
    main()
