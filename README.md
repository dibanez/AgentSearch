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
   | `MAX_RUNS_PER_DAY` | Límite de gasto: máximo de llamadas a la API al día entre todas las búsquedas (por defecto `24`; `0` = sin límite). Antes `MAX_EJECUCIONES_DIA`, que se sigue leyendo | — |
   | `API_RETRIES` | Intentos por búsqueda ante errores transitorios de OpenAI (5xx, 429, red), con espera creciente (por defecto `3`; `1` = sin reintentos). Antes `REINTENTOS_API`, que se sigue leyendo | — |

3. En **Domains** de la aplicación, añade tu dominio apuntando al puerto
   **8000** del servicio. El compose no publica puertos en el host (no hace
   falta: Traefik llega al contenedor por la red interna, y publicarlos
   provoca conflictos de tipo "port is already allocated" si el puerto está
   ocupado en el servidor). La base de datos vive en el volumen `agente_data`
   (`/data`), así que las búsquedas sobreviven a los redeploys.

Para probarlo en local (aquí sí se publica el puerto, vía archivo adicional):

```bash
cp .env.example .env   # y rellena OPENAI_API_KEY (docker compose lo lee solo)
docker compose -f docker-compose.yml -f docker-compose.local.yml up --build
# abre http://localhost:8000  (otro puerto: HOST_PORT=8080 en .env)
```

## Cómo funciona la vigilancia

1. En el panel añades una búsqueda: *"caravana 4 plazas con baño, menos de
   15.000€, máx. 10 años"*, tu ciudad, el **radio en km** (opcional), el
   **estado** y cada cuántas horas repetirla.
   - Con **km**: solo se guardan ofertas dentro de ese radio de tu ciudad (se
     le exige al agente y además se filtra en el servidor). Las ofertas cuya
     ubicación no se puede deducir se conservan marcadas "sin confirmar".
   - Sin **km**: busca sin límite de distancia, priorizando lo más cercano.
   - **Estado**: *indiferente* (por defecto), *solo nuevo* o *solo usado*. Con
     uno de los dos, se descartan las ofertas del estado contrario;
     reacondicionado y de exposición cuentan como usado, y lo que el anuncio
     no aclara se conserva marcado "sin confirmar".
2. El planificador la ejecuta a su intervalo (y también puedes lanzar
   "Buscar ahora"). Cada ejecución busca en portales de compraventa, tiendas y
   comparadores, y guarda las ofertas encontradas.
3. Se genera un aviso cuando:
   - aparece una oferta **más barata que el mínimo histórico** de esa búsqueda 📉
   - un anuncio ya conocido **baja de precio** (indicando si marca nuevo mínimo) 💶
   - el agente detecta un **posible chollo** (precio muy por debajo de mercado) 🔥
   - es la primera ejecución (te presenta la mejor oferta inicial) 🏆
4. Cada oferta guarda su **histórico de precios** y su **distancia estimada**
   (visibles en el detalle de la búsqueda), y un **límite de gasto diario**
   (`MAX_RUNS_PER_DAY`) frena las llamadas a la API si se supera.

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
uv run uvicorn shopping_agent.web:app --reload   # panel en http://localhost:8000
```

Estructura:

```
src/shopping_agent/
  agent.py    # búsqueda con OpenAI + web_search (salida JSON estructurada)
  db.py       # SQLite: búsquedas, ofertas, avisos
  web.py      # panel FastAPI + planificador periódico
  notify.py   # avisos por Telegram (opcional)
  main.py     # CLI interactiva
```

El **código está en inglés** (identificadores, comentarios, docstrings y tests)
y la **interfaz en español**: los textos del panel, los avisos y las
instrucciones que se le envían al modelo se escriben en español, y el esquema
SQLite conserva sus nombres originales (`busquedas`, `ofertas`, `radio_km`…)
para no tocar la base de datos ya desplegada.

La documentación de desarrollo está en [`specs/`](specs/):
[requisitos](specs/requirements.md) · [diseño técnico](specs/design.md) ·
[diseño de interfaz](specs/ui.md) · [tareas](specs/tasks.md).
