# 🛒 Agente de compras

Agente que busca en internet el producto que quieres comprar (por ejemplo, una
caravana) y te localiza **el mejor precio y la mejor calidad cerca de tu
ubicación**, cumpliendo las especificaciones que le indiques.

Tiene dos modos:

- **Panel web con vigilancia periódica** — guardas búsquedas y el agente las
  repite automáticamente cada X horas. Guarda las ofertas en SQLite y te avisa
  cuando aparece una oferta mejor que el mínimo anterior o un posible chollo
  (en el panel y, opcionalmente, por Telegram). Es el modo pensado para
  desplegar en Docker/Dokploy.
- **CLI interactiva** — para búsquedas puntuales desde la terminal.

Usa la API de OpenAI (Responses API) con búsqueda web integrada.

## Despliegue en Dokploy (Docker)

1. Sube este repositorio a Git y créalo en Dokploy como aplicación **Docker
   Compose** (o Dockerfile) apuntando al repo.
2. Define las variables de entorno:

   | Variable | Descripción | Obligatoria |
   |---|---|---|
   | `OPENAI_API_KEY` | Clave de la API de OpenAI | ✅ |
   | `OPENAI_MODEL` | Modelo a usar (por defecto `gpt-5`) | — |
   | `WEB_PASSWORD` | Contraseña del panel (HTTP Basic). Ponla si el panel es accesible desde internet | recomendada |
   | `TELEGRAM_BOT_TOKEN` | Token del bot de Telegram para avisos | — |
   | `TELEGRAM_CHAT_ID` | Chat ID donde enviar los avisos | — |
   | `MAX_EJECUCIONES_DIA` | Límite de gasto: máximo de llamadas a la API al día entre todas las búsquedas (por defecto `24`; `0` = sin límite) | — |

3. El servicio escucha en el puerto **8000**; configura el dominio/proxy de
   Dokploy hacia ese puerto. La base de datos vive en el volumen `agente_data`
   (`/data`), así que las búsquedas sobreviven a los redeploys.

Para probarlo en local:

```bash
cp .env.example .env   # y rellena OPENAI_API_KEY (docker compose lo lee solo)
docker compose up --build
# abre http://localhost:8000
```

## Cómo funciona la vigilancia

1. En el panel añades una búsqueda: *"caravana 4 plazas con baño, menos de
   15.000€, máx. 10 años"*, tu ciudad y cada cuántas horas repetirla.
2. El planificador la ejecuta a su intervalo (y también puedes lanzar
   "Buscar ahora"). Cada ejecución busca en portales de compraventa, tiendas y
   comparadores, y guarda las ofertas encontradas.
3. Se genera un aviso cuando:
   - aparece una oferta **más barata que el mínimo histórico** de esa búsqueda 📉
   - un anuncio ya conocido **baja de precio** (indicando si marca nuevo mínimo) 💶
   - el agente detecta un **posible chollo** (precio muy por debajo de mercado) 🔥
   - es la primera ejecución (te presenta la mejor oferta inicial) 🏆
4. Cada oferta guarda su **histórico de precios** (visible en el detalle de la
   búsqueda), y un **límite de gasto diario** (`MAX_EJECUCIONES_DIA`) frena las
   llamadas a la API si se supera.

Para ejecutar los tests: `uv run pytest`

### Avisos por Telegram (opcional)

1. Crea un bot con [@BotFather](https://t.me/BotFather) → te da el `TELEGRAM_BOT_TOKEN`.
2. Escribe cualquier mensaje a tu bot y visita
   `https://api.telegram.org/bot<TOKEN>/getUpdates` → el `chat.id` que aparece
   es tu `TELEGRAM_CHAT_ID`.
3. Define ambas variables y redespliega.

## CLI interactiva (uso local)

```bash
export OPENAI_API_KEY='sk-...'
uv run comprador
```

## Desarrollo

```bash
uv sync
uv run uvicorn agente_compras.web:app --reload   # panel en http://localhost:8000
```

Estructura:

```
src/agente_compras/
  agent.py    # búsqueda con OpenAI + web_search (salida JSON estructurada)
  db.py       # SQLite: búsquedas, ofertas, avisos
  web.py      # panel FastAPI + planificador periódico
  notify.py   # avisos por Telegram (opcional)
  main.py     # CLI interactiva
```

La documentación de desarrollo está en [`specs/`](specs/):
[requisitos](specs/requirements.md) · [diseño técnico](specs/design.md) ·
[tareas](specs/tasks.md).
