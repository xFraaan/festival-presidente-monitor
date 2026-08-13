# Monitor — Festival Presidente

Monitorea `https://festivalpresidente.tuboleta.com.do/` cada 5 minutos y envía una alerta a Discord cuando detecta un cambio relevante en la página.

---

## Estructura del repositorio

```
web-monitor/
├── .github/
│   └── workflows/
│       └── monitor.yml      # Workflow de GitHub Actions
├── state/
│   ├── .gitkeep             # Mantiene el directorio en git
│   └── page_hash.json       # Estado persistido (generado automáticamente)
├── monitor.py               # Script principal
├── requirements.txt         # Dependencias Python
└── README.md
```

---

## Cómo funciona

### Detección de cambios

1. Playwright lanza Chromium headless y carga la página completa (incluyendo JavaScript).
2. Se espera a que la red quede inactiva (`networkidle`) más 4 segundos adicionales para contenido lazy-loaded.
3. BeautifulSoup extrae el texto visible, **descartando** los elementos que generan ruido.
4. Se calcula un hash SHA-256 del texto limpio.
5. Se compara con el hash guardado en `state/page_hash.json`.
6. Si son distintos → alerta a Discord → actualiza el estado.

### Por qué Playwright y no `requests`

La página carga su contenido (lineup, precios, disponibilidad) mediante JavaScript/AJAX. Un simple `requests` devuelve únicamente los esqueletos HTML con textos "Cargando…". Playwright renderiza la página completa como lo haría un navegador real.

### Persistencia del estado

El estado se guarda en `state/page_hash.json` dentro del propio repositorio. Después de cada run donde el estado cambia, el workflow hace un `git commit` + `git push` automático. Esto es más confiable que GitHub Cache (puede expirar) o Artifacts (expiran en 90 días).

### Falsos positivos — qué se excluye

| Categoría | Motivo |
|---|---|
| `<script>`, `<style>`, `<noscript>` | Código técnico, no contenido |
| Elementos con clase/id que contienen: `timer`, `countdown`, `clock`, `cronometro` | Contadores regresivos |
| Clases con `cart`, `carrito`, `badge` | Contador del carrito de compras |
| Clases con `loading`, `spinner`, `cargando` | Indicadores de carga |
| Clases con `cookie`, `consent`, `gdpr`, `banner`, `modal`, `popup` | Avisos de cookies y modales |
| Scripts de analytics: `gtag`, `fbq`, `hotjar`, `intercom`, etc. | Tracking de terceros |
| Texto `HH:MM:SS` (regex) | Clocks en vivo |
| Texto "X días/horas/minutos restantes" (regex) | Tiempos relativos |

---

## Configuración paso a paso

### 1. Crear el repositorio en GitHub

> **IMPORTANTE:** Usa un repositorio **público** para aprovechar los minutos ilimitados de GitHub Actions. Con un repositorio privado, 288 ejecuciones diarias de ~1.5 min cada una superan los 2,000 minutos gratuitos mensuales.

1. Ve a [github.com/new](https://github.com/new).
2. Nombra el repositorio (por ejemplo: `festival-presidente-monitor`).
3. Selecciona **Public**.
4. Crea el repositorio **sin** README ni .gitignore (el tuyo ya los tiene).

### 2. Subir los archivos

```bash
git init
git add .
git commit -m "chore: initial setup"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/festival-presidente-monitor.git
git push -u origin main
```

### 3. Configurar el GitHub Secret `DISCORD_WEBHOOK_URL`

El Webhook de Discord **nunca** debe aparecer en el código fuente. Se configura como Secret en GitHub:

1. Abre tu repositorio en GitHub.
2. Ve a **Settings** → **Secrets and variables** → **Actions**.
3. Haz clic en **New repository secret**.
4. En **Name** escribe exactamente: `DISCORD_WEBHOOK_URL`
5. En **Secret** pega la URL del Webhook de Discord (la obtienes en Discord → canal → Editar canal → Integraciones → Webhooks → Crear Webhook → Copiar URL del Webhook).
6. Haz clic en **Add secret**.

### 4. Activar GitHub Actions

GitHub Actions se activa automáticamente al detectar archivos en `.github/workflows/`. Sin embargo, los workflows programados (`schedule`) solo corren en la **rama por defecto** (normalmente `main`).

Para verificar que está activo:

1. Ve a la pestaña **Actions** de tu repositorio.
2. Deberías ver el workflow **Monitor - Festival Presidente**.
3. Si aparece un aviso de "workflows disabled", haz clic en **Enable**.

> **Nota:** GitHub puede tardar hasta 15-30 minutos en ejecutar el primer run programado después del push inicial.

---

## Primera ejecución

En la primera ejecución el script:
- Obtiene el contenido actual de la página.
- Lo guarda en `state/page_hash.json`.
- **No envía ninguna alerta**.
- El workflow hace commit y push de ese archivo.

A partir de la segunda ejecución, cualquier cambio relevante dispara la alerta:

```
🚨🚨🚨 Cambio Realizado!
```

---

## Prueba manual

### Ejecutar el workflow manualmente desde GitHub

1. Ve a **Actions** → **Monitor - Festival Presidente**.
2. Haz clic en **Run workflow** → **Run workflow**.
3. Observa los logs en tiempo real.

### Ejecutar localmente

```bash
# Instalar dependencias
pip install -r requirements.txt
playwright install chromium --with-deps

# Primera ejecución (guarda estado, no alerta)
python monitor.py

# Segunda ejecución (compara)
DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..." python monitor.py
```

### Forzar un cambio para probar la alerta

```bash
# Borra el estado para simular un cambio
rm state/page_hash.json
DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..." python monitor.py
```

---

## Solución de problemas

### El workflow no aparece en la pestaña Actions

- Verifica que el archivo esté en `.github/workflows/monitor.yml` en la rama `main`.
- Haz un push de prueba para activar la detección.

### Error: `DISCORD_WEBHOOK_URL` no definido

- Verifica que el Secret esté configurado en Settings → Secrets and variables → Actions.
- El nombre debe ser exactamente `DISCORD_WEBHOOK_URL` (sensible a mayúsculas).

### El workflow falla con timeout

- La página puede estar temporalmente caída. El timeout está configurado en 30 segundos para la carga y 10 minutos para el job completo.
- Los fallos temporales no actualizan el estado; el próximo run intentará de nuevo.

### Se reciben falsas alarmas

- Revisa los logs del workflow para ver qué contenido está cambiando.
- Agrega el patrón problemático a `_DYNAMIC_ATTR_RE` o `_DYNAMIC_TEXT_RES` en `monitor.py`.

### `git push` falla en el workflow (error 403)

- Verifica que el workflow tenga `permissions: contents: write` (ya incluido).
- Si usas protección de rama (branch protection), puede requerir ajustes.

### Los runs programados se ejecutan con retraso

- Comportamiento normal de GitHub. Durante alta carga pueden demorarse 15-60 minutos. No afecta la confiabilidad del monitor a largo plazo.

---

## Limitaciones conocidas

| Limitación | Detalle |
|---|---|
| Frecuencia mínima | GitHub no garantiza exactamente cada 5 minutos; puede haber retrasos |
| Repos privados | Los 2,000 minutos/mes gratuitos se consumen rápido con esta frecuencia |
| Páginas con CAPTCHA | Playwright puede ser bloqueado por sistemas anti-bot agresivos |
| Cambios de layout CSS | Si solo cambia el estilo visual sin afectar el texto, no se detecta |
| Páginas A/B testing | Variaciones aleatorias del sitio pueden generar falsas alarmas |
