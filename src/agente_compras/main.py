"""Agente de compras: busca en internet el mejor precio y la mejor calidad
para el producto que quieras comprar, priorizando ofertas cerca de tu ubicación.

Usa la API de OpenAI (Responses API) con la herramienta de búsqueda web integrada.
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

INSTRUCCIONES = """\
Eres un agente experto en compras. Tu trabajo es encontrar el mejor producto \
para el usuario buscando en internet ofertas reales y actuales.

Método de trabajo:
1. Haz varias búsquedas web con distintos enfoques: portales de compraventa \
(Milanuncios, Wallapop, coches.net, Autocasion, Amazon, Idealo, etc. según el \
producto), concesionarios o tiendas oficiales, y comparadores de precios.
2. Prioriza resultados cercanos a la ubicación del usuario. Si hay pocas \
opciones cerca, amplía el radio y dilo claramente.
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


def crear_busqueda_web(ciudad: str | None, pais: str) -> dict:
    tool: dict = {"type": "web_search"}
    location: dict = {"type": "approximate", "country": pais}
    if ciudad:
        location["city"] = ciudad
    tool["user_location"] = location
    return tool


def responder(client: OpenAI, console: Console, tools: list[dict],
              texto: str, previous_id: str | None) -> str:
    """Envía un turno al modelo, muestra el progreso y devuelve el response.id."""
    with console.status("[bold cyan]Buscando en internet...", spinner="dots"):
        response = client.responses.create(
            model=MODEL,
            instructions=INSTRUCCIONES,
            input=texto,
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

    ciudad = Prompt.ask("📍 ¿En qué ciudad estás?", default="")
    pais = Prompt.ask("🌍 País (código de 2 letras)", default="ES").upper()
    tools = [crear_busqueda_web(ciudad or None, pais)]

    console.print(
        "\nEjemplo: [dim]quiero una caravana de segunda mano para 4 personas, "
        "con baño, menos de 15.000€ y máximo 10 años de antigüedad[/dim]\n"
        "Escribe [bold]salir[/bold] para terminar.\n"
    )

    previous_id: str | None = None
    while True:
        try:
            texto = Prompt.ask("[bold green]Tú[/bold green]")
        except (EOFError, KeyboardInterrupt):
            break
        if not texto.strip():
            continue
        if texto.strip().lower() in {"salir", "exit", "quit"}:
            break

        if previous_id is None and ciudad:
            texto = f"(Mi ubicación: {ciudad}, {pais}) {texto}"

        try:
            previous_id = responder(client, console, tools, texto, previous_id)
        except Exception as exc:  # noqa: BLE001 — mostrar el error y seguir en el bucle
            console.print(f"[red]Error al consultar la API:[/red] {exc}")

    console.print("¡Hasta luego! 👋")


if __name__ == "__main__":
    main()
