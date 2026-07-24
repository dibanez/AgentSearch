# Tareas — Agente de compras

Desglose del desarrollo. `[x]` = implementado y verificado; `[ ]` = pendiente.

## Fase 1 — Agente CLI de búsqueda puntual ✅ (2026-07-24)

- [x] 1.1 Crear el proyecto Python (`pyproject.toml`, `uv`, paquete `agente_compras`)
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
      solapadas (`_en_ejecucion`)
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

## Pendiente / ideas futuras

- [ ] 5.1 Desplegar en Dokploy y verificar en producción (dominio, volumen,
      primera búsqueda real end-to-end)
- [x] 5.2 Histórico de precios por oferta (tabla `precios` de snapshots:
      precio inicial + cada cambio) con la evolución visible en la página de
      detalle ("14000€ → 13500€ → 12900€" con fechas) — 2026-07-24
- [x] 5.3 Notificar también bajadas de precio de ofertas ya conocidas 💶
      (con indicación de si la bajada marca un nuevo mínimo) — 2026-07-24,
      verificado con test de avisos con la API simulada
- [ ] 5.4 Modo no interactivo de la CLI (`comprador "caravana < 15000€"`)
- [ ] 5.5 Presupuesto máximo por búsqueda como campo propio (además de en el
      texto), para filtrar ofertas en el servidor
- [ ] 5.6 Página de detalle del aviso + marcar avisos como leídos
- [x] 5.7 Límite de gasto diario: tabla `ejecuciones` + `MAX_EJECUCIONES_DIA`
      (por defecto 24; 0 = sin límite). Al alcanzarlo, las ejecuciones se
      omiten sin llamar a la API hasta las 00:00 UTC; el panel muestra el
      contador y un banner de aviso — 2026-07-24
- [x] 5.8 Tests automatizados con pytest (16 tests): unitarios de `db.py`
      (dedupe, mínimo histórico, pendientes, cascada, historial, contador) y
      de la lógica de avisos con la API simulada (inicial, nueva mejor,
      chollo, bajadas, subidas sin aviso, error de API, límite diario) —
      2026-07-24, `uv run pytest`
- [ ] 5.9 Otros canales de aviso: ntfy, email
