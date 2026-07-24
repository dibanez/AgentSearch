# Requisitos — Agente de compras

## Visión

Un agente que busca en internet productos que el usuario quiere comprar
(p. ej. una caravana), localiza **el mejor precio y la mejor calidad cerca de
su ubicación** según las especificaciones indicadas, y **vigila el mercado de
forma periódica** avisando cuando aparece una oferta mejor.

## Usuarios y contexto

- Usuario único (autoalojado). Despliegue en un servidor propio con Dokploy.
- Idioma de la interfaz y de las respuestas: español.
- Proveedor de IA: **API de OpenAI** (decisión del usuario), Responses API con
  la herramienta de búsqueda web integrada.

## Requisitos funcionales

### RF1 — Búsqueda puntual (CLI)
1. CUANDO el usuario describe un producto con especificaciones y presupuesto,
   el agente DEBE buscar en internet ofertas reales y actuales.
2. El agente DEBE priorizar resultados cercanos a la ciudad/país del usuario
   y ampliarlo si hay pocas opciones, indicándolo.
3. El agente DEBE devolver una tabla con las 5–8 mejores opciones (nombre,
   precio, ubicación, estado, enlace real al anuncio) y una recomendación
   razonada de calidad-precio.
4. El agente NO DEBE inventar datos: lo que no aparezca en el anuncio se marca
   como "no especificado".
5. La conversación DEBE mantener contexto para afinar la búsqueda en turnos
   siguientes ("¿y con calefacción?", "amplía a 200 km").

### RF2 — Vigilancia periódica (panel web)
1. El usuario DEBE poder guardar búsquedas vigiladas con: consulta, ciudad,
   país e intervalo de repetición en horas.
2. El sistema DEBE ejecutar cada búsqueda activa automáticamente cuando venza
   su intervalo, sin intervención del usuario.
3. El usuario DEBE poder: lanzar una búsqueda manualmente ("Buscar ahora"),
   pausarla/reanudarla y borrarla.
4. Las ofertas encontradas DEBEN persistir (histórico por búsqueda), y las
   repetidas (misma URL) DEBEN actualizarse en lugar de duplicarse.

### RF3 — Avisos de mejor oferta
1. CUANDO una ejecución encuentra una oferta nueva con precio inferior al
   mínimo histórico de esa búsqueda, el sistema DEBE generar un aviso 📉.
2. CUANDO el agente marca una oferta nueva como chollo (precio claramente por
   debajo de mercado), el sistema DEBE generar un aviso 🔥.
2b. CUANDO una oferta ya conocida baja de precio respecto al último precio
   visto, el sistema DEBE generar un aviso 💶, indicando además si la bajada
   supone un nuevo mínimo de la búsqueda.
3. En la primera ejecución de una búsqueda, el sistema DEBE avisar solo de la
   mejor oferta inicial 🏆 (no de todas).
4. Los avisos DEBEN verse en el panel y, si hay credenciales de Telegram
   configuradas, enviarse también por Telegram con el enlace al anuncio.

### RF4 — Despliegue
1. El servicio DEBE ejecutarse en Docker y ser desplegable en Dokploy
   (Dockerfile + docker-compose).
2. Los datos DEBEN sobrevivir a un redeploy (volumen persistente).
3. Toda la configuración DEBE hacerse por variables de entorno.

## Requisitos no funcionales

- **RNF1 Seguridad**: el panel DEBE poder protegerse con contraseña
  (`WEB_PASSWORD`, HTTP Basic) al estar expuesto a internet. Las claves de API
  nunca se guardan en el repositorio.
- **RNF2 Coste**: el intervalo de vigilancia es configurable por búsqueda
  (mínimo 1 h), y existe un límite global de llamadas a la API por día
  (`MAX_EJECUCIONES_DIA`); al alcanzarlo no se hacen más llamadas hasta el día
  siguiente y el panel lo indica.
- **RNF3 Robustez**: un fallo en una búsqueda (API caída, respuesta no
  parseable) NO DEBE tumbar el servicio; se registra el error y se muestra en
  el panel, y el planificador continúa.
- **RNF4 Simplicidad operativa**: sin dependencias externas de infraestructura
  (la persistencia es SQLite en un volumen; no requiere Postgres/Redis).

### RF5 — Histórico de precios
1. El sistema DEBE guardar un snapshot del precio inicial de cada oferta y de
   cada cambio posterior.
2. La página de detalle DEBE mostrar la evolución de precio de las ofertas con
   más de un snapshot (cadena de precios con fechas).

## Fuera de alcance (por ahora)

- Multiusuario y cuentas.
- Scraping directo de portales (se delega en la búsqueda web del modelo).
- Cálculo real de distancias por GPS (la distancia es la del anuncio).
