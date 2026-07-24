# Tareas — Agente de compras

Desglose del desarrollo. `[x]` = implementado y verificado; `[ ]` = pendiente.

## Fase 1 — Agente CLI de búsqueda puntual ✅ (2026-07-24)

- [x] 1.1 Crear el proyecto Python (`pyproject.toml`, `uv`, paquete `shopping_agent`)
- [x] 1.2 Integrar la API de OpenAI (Responses API) con la herramienta `web_search`
      y `user_location` (ciudad/país del usuario)
- [x] 1.3 Escribir las instrucciones del agente: método de búsqueda multi-portal,
      priorización por cercanía, verificación de especificaciones, formato de
      salida (tabla + recomendación calidad-precio, sin inventar datos)
- [x] 1.4 CLI interactiva (`comprador`) con `rich`: pregunta ubicación, bucle de
      conversación multi-turno vía `previous_response_id`, salida Markdown
- [x] 1.5 Verificar instalación e importación (`uv sync`, entrypoint)

## Fase 2 — Vigilancia periódica + panel web ✅ (2026-07-24)

- [x] 2.1 Extraer la búsqueda a `agent.py` con **salida estructurada**
      (`json_schema` strict: ofertas con título, precio, ubicación, estado,
      URL, es_chollo, motivo + resumen) y fallback de parseo
- [x] 2.2 Persistencia SQLite (`db.py`): búsquedas, ofertas (dedupe por
      `busqueda_id+url`), avisos, búsquedas vencidas, mínimo histórico
- [x] 2.3 Panel FastAPI (`web.py`): listado, alta, detalle con histórico de
      ofertas ordenado por precio, "Buscar ahora", pausar/reanudar, borrar
- [x] 2.4 Planificador asyncio en `lifespan`: comprueba cada 60 s las
      búsquedas activas vencidas y las ejecuta; protección contra ejecuciones
      solapadas (`_running`)
- [x] 2.5 Lógica de avisos: 📉 nueva mejor oferta (precio < mínimo histórico),
      🔥 posible chollo, 🏆 mejor oferta inicial (solo primera ejecución)
- [x] 2.6 Notificaciones Telegram opcionales (`notify.py`, best-effort)
- [x] 2.7 Auth HTTP Basic opcional (`WEB_PASSWORD`)
- [x] 2.8 Probar endpoints en local (200/303, alta y detalle) y planificador

## Fase 3 — Docker y despliegue en Dokploy ✅ (2026-07-24)

- [x] 3.1 `Dockerfile` (python:3.12-slim, uvicorn:8000, `VOLUME /data`)
- [x] 3.2 `docker-compose.yml` con volumen persistente `agente_data`,
      variables de entorno y `restart: unless-stopped`
- [x] 3.3 `.dockerignore`
- [x] 3.4 Verificar build de la imagen y arranque del contenedor, incl. auth
      (401 sin credenciales / 200 con ellas)
- [x] 3.5 Documentar despliegue en Dokploy y configuración de Telegram (README)

## Fase 4 — Documentación de desarrollo ✅ (2026-07-24)

- [x] 4.1 `specs/requirements.md` — requisitos funcionales y no funcionales
- [x] 4.2 `specs/design.md` — arquitectura, decisiones, modelo de datos
- [x] 4.3 `specs/tasks.md` — este desglose
- [x] 4.4 `specs/ui.md` — guía de interfaz: principios, tokens de estilo,
      componentes, validación en servidor, iconografía y microcopy —
      2026-07-26

## Fase 5 — Radio de búsqueda en km ✅ (2026-07-25)

- [x] 5.1 `busquedas.radio_km` (opcional) + campo "km" junto a ciudad en los
      formularios de alta y edición, conservando el histórico al cambiarlo
- [x] 5.2 Instrucciones del agente: si hay radio, exigir explícitamente solo
      ofertas dentro de N km de la ciudad; si no lo hay, sin límite de
      distancia priorizando cercanía
- [x] 5.3 Schema de salida: `distance_km` (number|null) por oferta;
      `ofertas.distancia_km` en la base de datos
- [x] 5.4 Filtro en servidor (`_filter_by_radius`): descartar ofertas con
      distancia conocida mayor que el radio, conservar las de distancia
      desconocida marcadas "sin confirmar", y dejar constancia de cuántas se
      descartaron en el resumen de la ejecución
- [x] 5.5 Mostrar distancia en la tabla de ofertas y la zona (ciudad, país,
      radio o "sin límite de km") en el listado y en la ficha
- [x] 5.6 Tests: parseo del campo, filtro por radio (dentro / límite exacto /
      fuera / desconocida / no numérica), ejecución completa descartando la
      oferta lejana, distancia conservada al desaparecer del anuncio, edición
      del radio sin pérdida de histórico e instrucciones enviadas al modelo
- [x] 5.7 Migraciones idempotentes en `init_db()` (`_MIGRATIONS` +
      `PRAGMA table_info`), verificadas sobre una base de datos con el
      esquema anterior: nada se borra ni se recrea
- [x] 5.8 La CLI pregunta también el radio y lo respeta en las instrucciones
- [x] 5.9 Campo de km sin restricciones de navegador (`step="any"`, sin `max`):
      el `min=1 step=10` anterior rechazaba 200 km pidiendo 201. La validación
      la hace el servidor — 2026-07-25

## Fase 6 — Estado del producto: nuevo / usado ✅ (2026-07-25)

Filtro opcional por estado al crear la búsqueda (RF7). Mismo patrón que el
radio de km: instrucción al agente + filtro en servidor, sin descartar lo
desconocido.

- [x] 6.1 `busquedas.estado_deseado` (`nuevo` | `usado` | NULL = indiferente) y
      `ofertas.condicion` (`nuevo` | `usado` | NULL = sin confirmar), añadidas
      a `_MIGRATIONS` (idempotentes, sin tocar los datos existentes)
- [x] 6.2 Selector **Estado** (indiferente / nuevo / usado) en los formularios
      de alta y edición, junto a los km; por defecto indiferente, y editarlo
      no borra el histórico
- [x] 6.3 Instrucciones del agente según el estado pedido: solo producto nuevo
      (tiendas, outlet, precintado) o solo de segunda mano (compraventa),
      clasificando **reacondicionado y exposición como usado**
- [x] 6.4 Schema de salida: `condition` (`"nuevo"` | `"usado"` | null) además
      del `condition_text` en texto libre que ya se muestra; solo se guardan valores
      canónicos (`web._condition` normaliza y descarta lo demás)
- [x] 6.5 Filtro en servidor (`_filter_by_condition`): descartar las ofertas
      cuya condición conocida no coincida con la pedida, conservar las de
      condición desconocida marcadas "sin confirmar", y contar las
      descartadas en el resumen de la ejecución (junto a las del radio)
- [x] 6.6 Mostrar la condición en la tabla de ofertas y el estado pedido en el
      listado y en la ficha de la búsqueda
- [x] 6.7 Tests (13): parseo del selector, normalización de la condición,
      filtro por estado (coincide / no coincide / desconocida / indiferente),
      ejecución completa descartando la oferta del estado contrario,
      combinación con el radio, condición conservada al desaparecer del
      anuncio, edición del estado sin pérdida de histórico e instrucciones
      enviadas al modelo; migración verificada sobre el esquema desplegado
- [x] 6.8 README: documentar el selector de estado
- [x] 6.9 La CLI pregunta también el estado y lo respeta en las instrucciones

## Fase 7 — Código en inglés ✅ (2026-07-26)

El código (identificadores, comentarios, docstrings, tests y nombre del
paquete) pasa a inglés, mientras que la interfaz, los prompts del agente y el
esquema SQLite siguen en español: no cambia nada de lo que lee el usuario ni
de lo que ya está desplegado.

- [x] 7.1 Paquete renombrado a `shopping_agent`; imports, `pyproject.toml`,
      `Dockerfile` y entrypoint actualizados
- [x] 7.2 Identificadores, comentarios, docstrings y mensajes de log en inglés
      en los cinco módulos
- [x] 7.3 Claves del schema de salida del modelo en inglés (`offers`, `title`,
      `price_eur`, `distance_km`, `condition`, `condition_text`, `is_bargain`,
      `reason`, `summary`), con las instrucciones al modelo actualizadas para
      nombrarlas
- [x] 7.4 Rutas y campos de formulario en inglés (`/searches`,
      `/searches/{id}/run|edit|toggle|delete`; `query`, `city`, `radius_km`,
      `country`, `wanted_condition`, `interval_hours`) y clases CSS `.red`,
      `.grey`, `.bargain`, `.alert`
- [x] 7.5 Variables de entorno `MAX_RUNS_PER_DAY` y `API_RETRIES`, leyendo los
      nombres antiguos como respaldo para no cambiar la configuración ya
      desplegada
- [x] 7.6 Esquema SQLite intacto a propósito: el código en inglés lee columnas
      en español, verificado abriendo con el código nuevo una base de datos
      creada con el anterior
- [x] 7.7 Tests traducidos y renombrados (`test_alerts.py`,
      `test_condition.py`, `test_form.py`, `test_radius.py`,
      `test_retries.py`); los 55 siguen pasando

## Fase 8 — Despliegue y verificación en producción

- [ ] 8.1 Verificar las migraciones sobre una copia de la base de datos real
      antes de desplegar
- [ ] 8.2 Desplegar en Dokploy y comprobar en producción: dominio, volumen
      persistente y una búsqueda real de principio a fin
- [ ] 8.3 Repasar que README y `.env.example` reflejan las variables de
      entorno vigentes
- [ ] 8.4 Revisar que las pantallas nuevas cumplen [`ui.md`](ui.md) y
      actualizar la guía si alguna introduce un componente que no está en ella

## Pendiente / ideas futuras

- [x] 9.2 Histórico de precios por oferta (tabla `precios` de snapshots:
      precio inicial + cada cambio) con la evolución visible en la página de
      detalle ("14000€ → 13500€ → 12900€" con fechas) — 2026-07-24
- [x] 9.3 Notificar también bajadas de precio de ofertas ya conocidas 💶
      (con indicación de si la bajada marca un nuevo mínimo) — 2026-07-24,
      verificado con test de avisos con la API simulada
- [ ] 9.4 Modo no interactivo de la CLI (`comprador "caravana < 15000€"`)
- [ ] 9.5 Presupuesto máximo por búsqueda como campo propio (además de en el
      texto), para filtrar ofertas en el servidor
- [ ] 9.6 Página de detalle del aviso + marcar avisos como leídos
- [x] 9.7 Límite de gasto diario: tabla `ejecuciones` + `MAX_RUNS_PER_DAY`
      (por defecto 24; 0 = sin límite). Al alcanzarlo, las ejecuciones se
      omiten sin llamar a la API hasta las 00:00 UTC; el panel muestra el
      contador y un banner de aviso — 2026-07-24
- [x] 9.8 Tests automatizados con pytest (16 tests): unitarios de `db.py`
      (dedupe, mínimo histórico, pendientes, cascada, historial, contador) y
      de la lógica de avisos con la API simulada (inicial, nueva mejor,
      chollo, bajadas, subidas sin aviso, error de API, límite diario) —
      2026-07-24, `uv run pytest`
- [ ] 9.9 Otros canales de aviso: ntfy, email
- [x] 9.10 Editar búsquedas guardadas (consulta, ciudad, país, intervalo) desde
      el detalle, conservando el histórico de ofertas y precios — 2026-07-24
- [x] 9.11 Botón "Probar Telegram" en el panel + descripción exacta del error
      de la API de Telegram en logs y pantalla — 2026-07-24
- [ ] 9.12 Vinculación de Telegram por código: escribir un código al bot y que
      el servicio guarde el `chat_id`, en vez de sacarlo de `getUpdates`
- [x] 9.16 Consulta como campo multilínea (`textarea`) en alta y edición, con
      los saltos de línea conservados al guardar (`\r\n` → `\n`) y respetados
      al mostrar la búsqueda — 2026-07-25
- [x] 9.17 Reintentos con espera creciente ante errores transitorios de OpenAI
      (5xx, 429, red) vía `API_RETRIES`; mensajes de error legibles en el
      panel y ejecuciones fallidas que no gastan cuota diaria — 2026-07-25
