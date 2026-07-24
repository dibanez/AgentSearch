# Diseño técnico — Agente de compras

## Arquitectura

```
┌────────────────────────── contenedor Docker ──────────────────────────┐
│                                                                        │
│  FastAPI (web.py)                          Planificador (asyncio)      │
│  ├─ GET  /                 panel           bucle cada 60 s:            │
│  ├─ POST /busquedas        crear           busca vigilancias vencidas  │
│  ├─ POST /…/ejecutar       lanzar ahora ─┐ y las ejecuta en un thread  │
│  ├─ POST /…/alternar       pausar        │          │                  │
│  └─ POST /…/borrar         borrar        └──────────┤                  │
│                                                     ▼                  │
│                                      ejecutar_busqueda(id)             │
│                                      ├─ agent.buscar_ofertas()  ──────────► API OpenAI
│                                      │   (Responses API + web_search)  │   (búsqueda web)
│                                      ├─ db.upsert_oferta()             │
│                                      └─ avisos → db + notify (Telegram)│
│                                                                        │
│  SQLite en /data/agente.db (volumen persistente)                       │
└────────────────────────────────────────────────────────────────────────┘
```

Además existe una CLI interactiva (`main.py`, comando `comprador`) que usa la
misma API con conversación multi-turno (`previous_response_id`).

## Módulos

| Módulo | Responsabilidad |
|---|---|
| `agent.py` | Llamada a la API de OpenAI: instrucciones del agente, herramienta `web_search` con `user_location`, y salida estructurada JSON validada por schema. |
| `db.py` | Persistencia SQLite: tablas `busquedas`, `ofertas`, `avisos`; cálculo de búsquedas vencidas y mínimo histórico. |
| `web.py` | Panel HTML (server-rendered, sin JS), endpoints de gestión, planificador en `lifespan`, y lógica de generación de avisos. |
| `notify.py` | Envío opcional a Telegram (`sendMessage`); si no hay credenciales, no-op. |
| `main.py` | CLI interactiva con `rich` (modo búsqueda puntual). |

## Decisiones de diseño

1. **OpenAI Responses API con `web_search`** en lugar de scraping propio:
   los portales cambian y bloquean scrapers; la búsqueda web del modelo
   generaliza a cualquier producto y portal. Contrapartida: dependencia de la
   calidad de resultados del buscador y coste por ejecución.
2. **Salida estructurada (`json_schema`, strict)** para la vigilancia: se
   necesita comparar precios entre ejecuciones, así que el modelo devuelve
   `{ofertas: [{titulo, precio_eur, ubicacion, estado, url, es_chollo,
   motivo}], resumen}`. Hay un fallback que extrae el primer bloque `{...}`
   si el modelo envolviera el JSON en texto.
3. **Detección de "mejor oferta" por mínimo histórico**: la clave de
   deduplicación es `(busqueda_id, url)`. Una oferta nueva con
   `precio < MIN(precios anteriores)` dispara aviso. En la primera ejecución
   solo se avisa de la mejor, para no inundar de notificaciones.
4. **SQLite + volumen** en vez de un SGBD externo: un solo usuario, escrituras
   escasas (una tanda por búsqueda cada X horas). Conexión por operación con
   `timeout=30` para tolerar concurrencia planificador/panel.
5. **Planificador propio con asyncio** (bucle de 60 s + `asyncio.to_thread`)
   en vez de APScheduler/cron: una dependencia menos y suficiente para
   intervalos en horas. El set `_en_ejecucion` evita ejecuciones solapadas de
   la misma búsqueda (y da feedback "⏳ buscando…" en el panel).
6. **HTML server-rendered sin framework de frontend**: formularios `POST` +
   redirect 303. Minimiza superficie y dependencias; suficiente para un panel
   personal.
7. **Auth HTTP Basic opcional por env var**: dependencia global de FastAPI que
   solo se activa si `WEB_PASSWORD` está definida — en local no estorba, en
   internet protege.

## Modelo de datos

```sql
busquedas   (id, consulta, ciudad, pais, intervalo_horas, activa,
             creada, ultima_ejecucion, ultimo_resumen, ultimo_error)
ofertas     (id, busqueda_id→busquedas, url, titulo, precio, ubicacion, estado,
             es_chollo, motivo, primera_vez, ultima_vez,
             UNIQUE(busqueda_id, url))
precios     (id, oferta_id→ofertas, precio, visto)      -- snapshot del precio
                                                        -- inicial y de cada cambio
avisos      (id, busqueda_id→busquedas, mensaje, url, creado)
ejecuciones (id, busqueda_id→busquedas SET NULL, creado) -- una fila por llamada
                                                         -- a la API (límite diario)
```

Borrado en cascada (`ON DELETE CASCADE` + `PRAGMA foreign_keys=ON`).
Fechas en ISO 8601 UTC.

## Configuración (variables de entorno)

| Variable | Uso | Por defecto |
|---|---|---|
| `OPENAI_API_KEY` | Autenticación con OpenAI | — (obligatoria) |
| `OPENAI_MODEL` | Modelo de la Responses API | `gpt-5` |
| `DB_PATH` | Ruta del fichero SQLite | `data/agente.db` (`/data/agente.db` en Docker) |
| `WEB_PASSWORD` | Contraseña HTTP Basic del panel | vacía = sin auth |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Avisos por Telegram | vacías = solo panel |
| `MAX_EJECUCIONES_DIA` | Límite de llamadas a la API por día (todas las búsquedas). Al alcanzarlo, las ejecuciones se omiten antes de llamar a la API hasta las 00:00 UTC | `24` (`0` = sin límite) |

## Manejo de errores

- Fallo de la API u oferta no parseable → se guarda en
  `busquedas.ultimo_error`, visible en el panel; el planificador sigue.
- Fallo de Telegram → se registra en el log y el aviso queda igualmente en el
  panel (la notificación es best-effort).
- Precios `null` (anuncios sin precio) → se muestran como "—" y no participan
  en el mínimo histórico.

## Despliegue

- `Dockerfile`: `python:3.12-slim`, `pip install .`, uvicorn en el puerto 8000,
  `VOLUME /data`.
- `docker-compose.yml`: servicio único + volumen nombrado `agente_data`,
  `restart: unless-stopped`. En Dokploy se crea como aplicación Compose y se
  apunta el dominio al puerto 8000.
