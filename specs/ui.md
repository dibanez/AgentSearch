# Diseño de interfaz — Agente de compras

Guía de estilo e instrucciones de UI del panel web. Es normativa: cualquier
pantalla nueva (detalle de un aviso, filtros nuevos…) debe salir de aquí, y
todo lo que se añada al panel debe poder describirse con los componentes y los
tokens de este documento. Si algo no encaja, primero se amplía este spec.

Complementa a [`requirements.md`](requirements.md) (qué hace el producto) y a
[`design.md`](design.md) (cómo está construido por dentro). La implementación
vive en `src/shopping_agent/web.py` (`_CSS`, `_page`, y los generadores HTML
de cada ruta).

## Principios

1. **HTML servido por el servidor, sin framework de frontend.** Formularios
   `POST` + redirect 303. Sin build step, sin bundler, sin JS de aplicación.
   El único JS admisible es un `onsubmit='return confirm(...)'` en acciones
   destructivas.
2. **Sin recursos externos.** Nada de CDNs, fuentes web, iconos remotos ni
   analítica: el panel debe funcionar igual en un servidor sin salida a
   internet y no filtra qué mira el usuario. Tipografía del sistema
   (`system-ui`), iconografía con emoji.
3. **Una sola hoja de estilo embebida** (`_CSS` en `web.py`), servida dentro
   del `<style>` de cada página. Sin ficheros estáticos que cachear ni
   versionar.
4. **Densidad informativa antes que decoración.** Es un panel de trabajo: se
   prioriza ver muchas ofertas y su estado de un vistazo sobre el espacio en
   blanco. Las tablas son la unidad principal de presentación.
5. **La pantalla no miente.** Lo que el agente no ha podido confirmar se marca
   como "sin confirmar" o "—", nunca se rellena con un valor inventado ni se
   oculta la fila.
6. **Todo en español**, incluidos textos de interfaz, mensajes de error y
   `placeholder`. Trato de tú. El código que los genera está en inglés
   (identificadores, rutas, campos de formulario y clases CSS): la frontera
   está en la cadena de texto, no en la plantilla.
7. **Todo el contenido dinámico se escapa** con `_e()` (`html.escape`) antes de
   interpolarlo. Sin excepciones: los títulos y resúmenes vienen de la API y de
   anuncios de terceros.

## Tokens de diseño

Tema oscuro único (no hay modo claro; el panel se usa a menudo de noche y
reduce el consumo en pantallas OLED). Los valores son los de `_CSS`:

| Token | Valor | Uso |
|---|---|---|
| Fondo página | `#111` | `body` |
| Texto | `#eee` | texto general |
| Texto de títulos | `#fff` | `h1`, `h2` |
| Texto secundario | `#999`, `.85rem` | clase `.muted`: metadatos, fechas, notas de ayuda |
| Enlace | `#7cc0ff` | `a` |
| Superficie elevada | `#1a1a1a` + borde `#333` | clase `.card` |
| Separador | `#333` | bordes de tabla y de tarjeta |
| Campo de formulario | fondo `#222`, borde `#444` | `input`, `select`, `textarea` |
| Acción primaria | `#2563eb` sobre `#fff` | `button` |
| Acción destructiva | `#b91c1c` | `button.red` |
| Acción secundaria | `#444` | `button.grey` |
| Destacado / chollo | `#fbbf24` | clase `.bargain` |
| Aviso informativo | fondo `#1a2436`, borde `#2c3e5d` | clase `.alert` |
| Aviso de alarma | fondo `#2a1a12`, borde `#7c2d12` | límite diario alcanzado, error de Telegram |
| Texto de error | `#f87171` | `ultimo_error` en el listado |

Radios: `4px` en controles (input, button), `6px` en avisos, `8px` en tarjetas.
Espaciado: múltiplos de `0.4rem`; relleno de celda `.4rem .6rem`, de tarjeta
`1rem`. Tipografía: `system-ui, sans-serif`; los controles heredan con
`font:inherit` (nunca la fuente por defecto del navegador para formularios).

Un color nuevo requiere una razón semántica nueva. Antes de añadirlo, comprobar
si el significado ya lo cubre `.muted`, `.alert`, `.bargain` o el rojo de error.

## Estructura de página

```
<h1>🛒 Agente de compras</h1>     ← cabecera fija en todas las páginas (_page)
  [acciones de contexto]           ← "← volver" como primer elemento si no es la portada
  [formularios / tarjetas]
  [banners de estado]
  <h2>Sección</h2> + tabla
```

- Ancho máximo `960px`, centrado, `padding:1rem`. No hay barra lateral ni menú:
  la navegación es la portada más el enlace "← volver".
- `<meta name='viewport' content='width=device-width,initial-scale=1'>` siempre:
  el panel se consulta desde el móvil cuando llega un aviso de Telegram.
- `<title>` = contexto real de la página (la consulta en el detalle), no el
  nombre de la aplicación repetido.
- El orden en la portada es: **crear** (formulario) → **estado del sistema**
  (ejecuciones/límite) → **búsquedas** → **avisos recientes**. Lo accionable
  arriba, lo histórico abajo.

## Componentes

### Tarjeta (`.card`)
Agrupa un formulario o un bloque de resumen. Lleva un `<h2>` o un `<b>` como
encabezado. Se usa también con `<details><summary>✏️ Editar búsqueda</summary>`
para formularios secundarios que deben estar disponibles pero no ocupar sitio.

### Tabla
Unidad principal de listado. Cabecera con `<th>`, alineación a la izquierda,
`vertical-align:top` (las celdas contienen sub-líneas). Patrón de celda:

```
<td> valor principal
     <div class='muted'>metadato secundario</div> </td>
```

Así el listado de búsquedas mete zona, intervalo y última ejecución bajo la
consulta, y el detalle mete el histórico de precios bajo el precio actual. La
última columna de una tabla de gestión es la de acciones, sin encabezado.

### Botones y acciones
- Un solo botón primario por bloque; el resto en gris.
- Las acciones son formularios `POST` (`form.inline`), nunca enlaces `GET`: no
  deben poder dispararse desde un prefetch del navegador.
- Toda acción destructiva confirma: `onsubmit='return confirm("¿Borrar esta
  búsqueda y sus ofertas?")'`, y el texto de la confirmación dice **qué más se
  pierde**, no solo el objeto principal.
- Etiquetas en imperativo y concretas: "Buscar ahora", "Guardar cambios",
  "Vigilar", "Probar Telegram". Nunca "Aceptar" ni "Enviar".

### Formularios
- Campos en una línea de flujo natural con su unidad textual alrededor
  ("cada `[6]` horas"), en lugar de `<label>` sobre cada input: el formulario
  se lee como una frase.
- El `placeholder` describe el campo (`Ciudad`, `km`); el `title` explica la
  regla (`Radio de búsqueda en km. Vacío = sin límite de distancia`).
- Debajo del formulario, un `<p class='muted'>` explica el comportamiento no
  obvio (qué pasa si dejas los km vacíos, qué cuenta como usado, qué se
  conserva al editar).
- Los formularios de edición llegan **precargados** con los valores actuales;
  los numéricos se formatean con `:g` para no mostrar `100.0`.
- Campos de texto largo (`consulta`) son `<textarea rows='4'>` al 100 % de
  ancho y `resize:vertical`, tanto en alta como en edición. Los saltos de línea
  se conservan y se muestran con `white-space:pre-line`.

#### Validación: en el servidor, no en atributos restrictivos
Regla firme, aprendida de un fallo real: `min='1' step='10'` en el campo de km
hacía que el navegador rechazara `200` pidiendo `201`, porque `step` se cuenta
desde `min`. Los atributos HTML5 solo se usan como ayuda de teclado y de tipo
(`type='number'`, `step='any'`), **nunca** como validación de negocio:

- Nada de `max` ni de `step` distinto de `any` en campos que el usuario rellena
  libremente.
- La normalización real vive en el servidor (`_radius_from_form`,
  `_condition_from_form`, `_query_from_form`) y es tolerante: acepta coma
  decimal, espacios sobrantes y saltos de línea de Windows, y convierte lo
  vacío o inválido en el valor por defecto sin dar error.
- `required` sí se usa, porque expresa una regla real y no bloquea valores
  válidos.

### Banners de estado (`.alert`)
Tres variantes por color, no por icono:
- **Informativo** (azul): avisos de ofertas, confirmación de acción correcta.
- **Alarma** (marrón/rojo): límite diario alcanzado, fallo de Telegram.
- **Error de una búsqueda**: línea `.muted` en color `#f87171` bajo la fila de
  esa búsqueda, no un banner global — el fallo es de una búsqueda, no del
  sistema.

Un mensaje de error debe decir **qué ha pasado, si se reintentará y qué puede
hacer el usuario**. Ejemplos válidos, tal como los produce `_readable_error`:
"Error temporal de OpenAI (500)… se volverá a intentar en la siguiente
ejecución", "Límite de peticiones o saldo de OpenAI agotado (429). Revisa el
crédito de tu cuenta de OpenAI", "OPENAI_API_KEY no válida (401)". El volcado
técnico completo va al log, no a la pantalla.

### Estados vacíos
Cada listado tiene su texto propio en `.muted`, en positivo y sin ilustración:
"Aún no hay búsquedas guardadas.", "Sin avisos todavía.", "Todavía no hay
ofertas guardadas.". Nunca una tabla con la cabecera y el cuerpo vacío.

### Estado de progreso
No hay spinners ni polling. El progreso se comunica con el texto de estado de
la fila: `🟢 activa`, `⏸️ pausada`, `⏳ buscando…` (mientras la búsqueda está en
`_running`). El usuario recarga la página para ver el resultado; el aviso
de Telegram es el mecanismo de notificación real.

## Iconografía

Emoji, con significado fijo en toda la aplicación:

| Emoji | Significado |
|---|---|
| 🛒 | La aplicación |
| 🟢 / ⏸️ / ⏳ | Búsqueda activa / pausada / ejecutándose |
| 🏆 | Mejor oferta inicial (primera ejecución) |
| 📉 | Nueva oferta por debajo del mínimo histórico |
| 💶 | Bajada de precio de un anuncio ya conocido |
| 🔥 | Posible chollo |
| ⚠️ | Error en una búsqueda |
| ⛔ | Límite diario alcanzado |
| ✅ / ❌ | Resultado de una acción de prueba |
| ✏️ | Editar |
| 📏 / 🏷️ / 📍 | Radio, estado del producto, ubicación |

Un emoji nunca es el único portador de información: siempre va acompañado de
texto ("🟢 activa"), para lectores de pantalla y para cuando la fuente no lo
tiene.

## Redacción (microcopy)

- Segunda persona del singular: "Deja los **km** vacíos para buscar sin
  límite".
- Precios sin decimales y con el símbolo pegado (`13500€`); distancias en km
  enteros (`120 km`); intervalos con `:g` (`6h`, `0.5h`); fechas en `YYYY-MM-DD`
  (se corta el ISO con `[:10]`).
- Los desconocidos se escriben `—` cuando no hay dato, y "sin confirmar" cuando
  el dato existía pero el agente no ha podido verificarlo con el filtro activo.
- Al descartar resultados, el resumen dice **cuántos y por qué**: "Ofertas
  descartadas: 3 por estar a más de 100 km de Madrid; 2 por no ser producto
  usado." Nunca se descarta en silencio.

## Accesibilidad y responsive

- Contraste mínimo AA sobre el fondo `#111` para el texto principal; `.muted`
  (`#999`) queda reservado a información secundaria y nunca es el único sitio
  donde aparece un dato crítico.
- Los controles nativos conservan el foco por defecto del navegador; no se
  elimina el `outline`.
- `lang='es'` en `<html>`.
- Sin media queries: el ancho máximo y los porcentajes bastan. Las tablas
  anchas (detalle de ofertas, 6 columnas) se comprimen en móvil; si una tabla
  futura no cabe, se envuelve en un contenedor con `overflow-x:auto`, nunca se
  reduce el tamaño de letra.
- Los enlaces a anuncios externos abren en pestaña nueva (`target='_blank'`);
  la navegación interna, no.

## Pantallas nuevas

Antes de inventar nada, comprobar si la pantalla se puede montar con lo que ya
hay: cabecera + "← volver", `.card` para lo accionable, tabla para lo listado,
`.alert` para lo excepcional y `.muted` para lo secundario. Casi siempre se
puede.

Si de verdad hace falta un componente nuevo, se añade **primero aquí** (con su
token de color si lo lleva y su regla de uso) y después se implementa, para que
la guía no se quede por detrás del panel.
