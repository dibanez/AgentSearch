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
   **radio en km (opcional)**, país, **estado del producto (nuevo / usado /
   indiferente)** e intervalo de repetición en horas.
2. El sistema DEBE ejecutar cada búsqueda activa automáticamente cuando venza
   su intervalo, sin intervención del usuario.
3. El usuario DEBE poder: lanzar una búsqueda manualmente ("Buscar ahora"),
   editarla, pausarla/reanudarla y borrarla.
4. Las ofertas encontradas DEBEN persistir (histórico por búsqueda), y las
   repetidas (misma URL) DEBEN actualizarse en lugar de duplicarse.
5. El campo de **consulta DEBE ser multilínea** (área de texto) en el alta y en
   la edición, para poder escribir las especificaciones por líneas y verlas
   completas. Los saltos de línea DEBEN conservarse al guardar (normalizando
   los de Windows) y respetarse al mostrar la búsqueda.

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

### RF5 — Histórico de precios
1. El sistema DEBE guardar un snapshot del precio inicial de cada oferta y de
   cada cambio posterior.
2. La página de detalle DEBE mostrar la evolución de precio de las ofertas con
   más de un snapshot (cadena de precios con fechas).

### RF6 — Radio de búsqueda en km

1. El formulario de alta y edición DEBE incluir un campo **"km"** junto a la
   ciudad, opcional.
2. SI el usuario indica un radio, el sistema DEBE buscar **solo dentro de ese
   radio** respecto a la ciudad indicada: la instrucción al agente lo exige
   explícitamente y, además, el servidor descarta las ofertas cuya distancia
   conocida supere el radio (el modelo no garantiza cumplirlo por sí solo).
3. SI el usuario NO indica radio, el sistema DEBE buscar **sin límite de
   distancia**, priorizando las opciones más cercanas a igualdad de
   precio/estado y ampliando el alcance cuando haya pocas opciones cerca.
4. El agente DEBE devolver, por oferta, una **distancia estimada en km** desde
   la ciudad de referencia cuando pueda deducirla del anuncio; si no puede,
   `null`.
5. Las ofertas con distancia desconocida NO DEBEN descartarse: se guardan y se
   muestran marcadas como "distancia sin confirmar".
6. La distancia DEBE mostrarse en el listado de ofertas del detalle, y el radio
   activo DEBE verse en la ficha de la búsqueda.
7. Cambiar el radio de una búsqueda existente NO DEBE borrar el histórico de
   ofertas ni de precios ya guardado.
8. El campo de km DEBE aceptar **cualquier valor positivo**, con decimales y
   sin tope: ni pasos obligatorios ni máximos que rechacen valores redondos
   habituales (escribir 200 no puede exigir 201). La validación real es del
   servidor: 0, negativos o texto no numérico se interpretan como "sin
   límite".

### RF7 — Estado del producto (nuevo / usado)

1. El formulario de alta y de edición DEBE incluir un selector **"Estado"** con
   tres opciones: **indiferente** (por defecto), **nuevo** y **usado**.
2. SI el usuario elige nuevo o usado, el sistema DEBE buscar solo productos en
   ese estado: la instrucción al agente lo exige (portales y filtros acordes:
   tiendas y outlet para nuevo, compraventa de segunda mano para usado) y,
   además, el servidor descarta las ofertas cuya condición no coincida.
3. SI el usuario elige indiferente, NO DEBE aplicarse ningún filtro por estado
   y ambos tipos de oferta son válidos.
4. El agente DEBE devolver, por oferta, una **condición normalizada**
   (`nuevo`, `usado` o `null` si el anuncio no lo deja claro), además del
   campo de estado en texto libre que ya devuelve ("como nuevo, 2 dueños",
   "reacondicionado"…), que se sigue mostrando tal cual.
5. Las ofertas con condición desconocida NO DEBEN descartarse: se guardan y se
   muestran marcadas como "estado sin confirmar", igual que con la distancia.
6. Un producto **reacondicionado o de exposición** DEBE clasificarse como
   usado, no como nuevo.
7. El estado elegido DEBE verse en la ficha de la búsqueda y en el listado
   junto a la zona, y cambiarlo NO DEBE borrar el histórico de ofertas ni de
   precios.

## Requisitos no funcionales

- **RNF1 Seguridad**: el panel DEBE poder protegerse con contraseña
  (`WEB_PASSWORD`, HTTP Basic) al estar expuesto a internet. Las claves de API
  nunca se guardan en el repositorio.
- **RNF2 Coste**: el intervalo de vigilancia es configurable por búsqueda
  (mínimo 1 h), y existe un límite global de llamadas a la API por día
  (`MAX_RUNS_PER_DAY`); al alcanzarlo no se hacen más llamadas hasta el día
  siguiente y el panel lo indica.
- **RNF3 Robustez**: un fallo en una búsqueda (API caída, respuesta no
  parseable) NO DEBE tumbar el servicio; se registra el error y se muestra en
  el panel, y el planificador continúa. Los errores **transitorios** del
  proveedor (5xx, 429, cortes de red) DEBEN reintentarse con espera creciente
  antes de darse por fallidos; los errores de petición (400, 401) no. El
  mensaje mostrado DEBE ser legible y accionable, y una ejecución fallida NO
  DEBE consumir cuota del límite diario.
- **RNF4 Simplicidad operativa**: sin dependencias externas de infraestructura
  (la persistencia es SQLite en un volumen; no requiere Postgres/Redis).
- **RNF5 Interfaz**: toda pantalla DEBE ajustarse a la guía de interfaz
  ([`ui.md`](ui.md)): HTML servido por el servidor sin framework ni recursos
  externos, tokens de estilo y componentes ya definidos, validación en el
  servidor (nunca atributos HTML5 que rechacen valores legítimos), estados
  vacíos y de error con texto propio, y microcopy en español de tú.
- **RNF6 Idioma**: el código (identificadores, comentarios, docstrings, logs,
  tests, rutas y campos de formulario) DEBE escribirse en inglés, y todo lo que
  lee una persona —panel, avisos, CLI, documentación e instrucciones al
  modelo— DEBE escribirse en español. Los nombres de tablas y columnas de
  SQLite NO DEBEN traducirse: hay una base de datos desplegada y el código en
  inglés lee sus filas con claves en español.

## Fuera de alcance (por ahora)

- Multiusuario y cuentas (registro, login, roles): el servicio es de uso
  personal y se protege, si hace falta, con `WEB_PASSWORD`.
- Sistema de créditos y facturación del uso: el coste de la API lo asume el
  propio operador, acotado con `MAX_RUNS_PER_DAY`.
- Scraping directo de portales (se delega en la búsqueda web del modelo).
- Cálculo real de distancias por geocodificación propia: la distancia es la
  que estima el agente a partir de la ubicación del anuncio.
