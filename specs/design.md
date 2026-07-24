# Diseño técnico — Agente de compras

## Arquitectura

```
┌────────────────────────── contenedor Docker ──────────────────────────┐
│                                                                        │
│  FastAPI (web.py)                          Planificador (asyncio)      │
│  ├─ GET  /                 panel           bucle cada 60 s:            │
│  ├─ POST /searches         crear           busca vigilancias vencidas  │
│  ├─ POST /…/run            lanzar ahora ─┐ y las ejecuta en un thread  │
│  ├─ POST /…/edit           editar        │          │                  │
│  ├─ POST /…/toggle         pausar        │          │                  │
│  └─ POST /…/delete         borrar        └──────────┤                  │
│                                                     ▼                  │
│                                      run_search(id)                    │
│                                      ├─ agent.search_offers()   ──────────► API OpenAI
│                                      │   (Responses API + web_search)  │   (búsqueda web)
│                                      ├─ filtro de radio (km) y estado  │
│                                      ├─ db.upsert_offer()              │
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
| `agent.py` | Llamada a la API de OpenAI: instrucciones del agente, herramienta `web_search` con `user_location`, restricción de radio en km y de estado, salida estructurada JSON validada por schema, y reintentos ante errores transitorios. |
| `db.py` | Persistencia SQLite: `busquedas`, `ofertas`, `precios`, `avisos`, `ejecuciones`; migraciones idempotentes; búsquedas vencidas y mínimo histórico. |
| `web.py` | Panel HTML (server-rendered, sin JS), endpoints de gestión, filtros de radio y estado, planificador en `lifespan`, y lógica de generación de avisos. |
| `notify.py` | Envío opcional a Telegram (`sendMessage`); si no hay credenciales, no-op. |
| `main.py` | CLI interactiva con `rich` (modo búsqueda puntual). |

## Decisiones de diseño

1. **OpenAI Responses API con `web_search`** en lugar de scraping propio:
   los portales cambian y bloquean scrapers; la búsqueda web del modelo
   generaliza a cualquier producto y portal. Contrapartida: dependencia de la
   calidad de resultados del buscador y coste por ejecución.
2. **Salida estructurada (`json_schema`, strict)** para la vigilancia: se
   necesita comparar precios entre ejecuciones, así que el modelo devuelve
   `{offers: [{title, price_eur, location, distance_km, condition_text,
   condition, url, is_bargain, reason}], summary}`. Hay un fallback que
   extrae el primer bloque `{...}` si el modelo envolviera el JSON en texto.
3. **Detección de "mejor oferta" por mínimo histórico**: la clave de
   deduplicación es `(busqueda_id, url)`. Una oferta nueva con
   `precio < MIN(precios anteriores)` dispara aviso. En la primera ejecución
   solo se avisa de la mejor, para no inundar de notificaciones.
4. **SQLite + volumen** en vez de un SGBD externo: un solo usuario, escrituras
   escasas (una tanda por búsqueda cada X horas). Conexión por operación con
   `timeout=30` para tolerar concurrencia planificador/panel.
5. **Planificador propio con asyncio** (bucle de 60 s + `asyncio.to_thread`)
   en vez de APScheduler/cron: una dependencia menos y suficiente para
   intervalos en horas. El set `_running` evita ejecuciones solapadas de
   la misma búsqueda (y da feedback "⏳ buscando…" en el panel).
6. **HTML server-rendered sin framework de frontend**: formularios `POST` +
   redirect 303. Minimiza superficie y dependencias; suficiente para un panel
   personal. Los tokens de estilo, los componentes y las reglas de redacción y
   validación de la interfaz están en [`ui.md`](ui.md), que es normativo para
   cualquier pantalla nueva. La **validación vive en el servidor**, no en atributos HTML5
   restrictivos: un `step`/`max` en un campo numérico rechaza valores
   legítimos en el navegador con un mensaje confuso (con `min=1 step=10`, los
   200 km válidos se convertían en "escribe 201"). Los campos numéricos usan
   `step="any"` sin tope y el servidor normaliza (vacío, 0, negativo o texto
   = sin límite). La consulta es un `textarea` multilínea: las
   especificaciones largas se leen y editan mejor por líneas, y los saltos se
   conservan (`\r\n` → `\n`).
7. **Auth HTTP Basic opcional por env var**: dependencia global de FastAPI que
   solo se activa si `WEB_PASSWORD` está definida — en local no estorba, en
   internet protege.
8. **Radio en dos niveles (instrucción + filtro en servidor)**: se pide al
   modelo que descarte lo que esté fuera del radio *y* se filtra en el
   servidor con `distance_km`. El modelo no garantiza cumplir la
   restricción; el filtro del servidor sí. Las ofertas con `distance_km`
   nula no se descartan (se marcan "distancia sin confirmar") para no perder
   anuncios buenos cuya ubicación no es parseable.
9. **Estado (nuevo/usado) con el mismo patrón que el radio**: `condition_text`
   en texto libre es lo que dice el anuncio y sirve para leerlo; para poder
   filtrar hace falta un valor normalizado, así que el modelo devuelve
   además `condition` ∈ {`nuevo`, `usado`, `null`}. Se pide la restricción en
   las instrucciones **y** se filtra en el servidor; `null` no se descarta
   (se marca "estado sin confirmar"). "Indiferente" (columna a NULL) es el
   valor por defecto y no filtra nada, de modo que las búsquedas ya
   existentes no cambian de comportamiento tras la migración.
10. **Código en inglés, producto en español, base de datos intacta**: los
    identificadores, comentarios, docstrings, logs, tests, rutas, campos de
    formulario y claves del schema del modelo están en inglés, porque es el
    idioma en el que se lee y se busca código. Todo lo que lee una persona
    —panel, avisos, CLI, instrucciones al modelo— sigue en español (ver
    [`ui.md`](ui.md)). El **esquema SQLite se queda en español** a propósito:
    renombrar tablas y columnas obligaría a migrar una base ya desplegada, y
    el beneficio es cosmético. La frontera es `db.py`: código inglés que lee
    filas con claves españolas (`b["consulta"]`, `o["titulo"]`). Al tocar
    `web.py` hay que distinguir los dos vocabularios, porque conviven en la
    misma función: los dicts que vienen del modelo usan claves inglesas
    (`title`, `price_eur`, `is_bargain`) y las filas de la base, españolas.

## Modelo de datos

```sql
busquedas   (id, consulta, ciudad, radio_km, pais,
             estado_deseado,           -- 'nuevo' | 'usado' | NULL = indiferente
             intervalo_horas, activa, creada, ultima_ejecucion,
             ultimo_resumen, ultimo_error)
ofertas     (id, busqueda_id→busquedas, url, titulo, precio, ubicacion,
             distancia_km, estado,     -- texto libre del anuncio
             condicion,                -- 'nuevo' | 'usado' | NULL = sin confirmar
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

**Migraciones**: `init_db()` aplica migraciones idempotentes (comprobando
`PRAGMA table_info` y añadiendo la columna solo si falta) para las columnas
incorporadas después del despliegue inicial: `busquedas.radio_km`,
`busquedas.estado_deseado`, `ofertas.distancia_km` y `ofertas.condicion`. Nada
se borra ni se recrea, así que el histórico de ofertas, precios y avisos
sobrevive a cada actualización.

## Configuración (variables de entorno)

| Variable | Uso | Por defecto |
|---|---|---|
| `OPENAI_API_KEY` | Autenticación con OpenAI | — (obligatoria) |
| `OPENAI_MODEL` | Modelo de la Responses API | `gpt-5` |
| `DB_PATH` | Ruta del fichero SQLite | `data/agente.db` (`/data/agente.db` en Docker) |
| `WEB_PASSWORD` | Contraseña HTTP Basic del panel | vacía = sin auth |
| `MAX_RUNS_PER_DAY` | Límite de llamadas a la API por día (todas las búsquedas). Al alcanzarlo, las ejecuciones se omiten antes de llamar a la API hasta las 00:00 UTC. El nombre antiguo se sigue leyendo por compatibilidad | `24` (`0` = sin límite) |
| `API_RETRIES` | Intentos por búsqueda ante errores transitorios de OpenAI (5xx, 429, red), con espera creciente 2 s → 4 s → … El nombre antiguo se sigue leyendo por compatibilidad | `3` (`1` = sin reintentos) |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Avisos por Telegram | vacías = solo panel |

## Manejo de errores

- Fallo **transitorio** de la API (5xx de OpenAI, 429, corte de red) → se
  reintenta hasta `API_RETRIES` veces con espera creciente (2 s, 4 s, …)
  dentro de la misma ejecución. Los errores de petición (400, 401) no se
  reintentan: reintentarlos solo gasta tiempo.
- Fallo de la API u oferta no parseable → se guarda en
  `busquedas.ultimo_error` **traducido a un mensaje legible** (el volcado
  crudo de la API va al log), visible en el panel; el planificador sigue.
- Una ejecución que falla **no cuenta** para el límite diario: el contador
  registra solo las llamadas que la API llegó a atender.
- Fallo de Telegram → se registra en el log con la descripción exacta de la
  API y el aviso queda igualmente en el panel (la notificación es
  best-effort).
- Precios `null` (anuncios sin precio) → se muestran como "—" y no participan
  en el mínimo histórico.
- `distance_km` nula con radio definido → la oferta se conserva marcada como
  "distancia sin confirmar" (decisión 8).
- `condition` nula con estado deseado definido → la oferta se conserva marcada
  como "estado sin confirmar" (decisión 9).

## Despliegue

- `Dockerfile`: `python:3.12-slim`, `pip install .`, uvicorn en el puerto 8000,
  `VOLUME /data`.
- `docker-compose.yml`: servicio único + volumen nombrado `agente_data`,
  `restart: unless-stopped`. En Dokploy se crea como aplicación Compose y se
  apunta el dominio al puerto 8000 (sin publicar puertos en el host).
- Si el panel queda expuesto a internet, HTTPS (Traefik/Let's Encrypt en
  Dokploy) y `WEB_PASSWORD` definida.
