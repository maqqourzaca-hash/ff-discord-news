# Noticias diarias de Forex Factory en Discord

Publica automáticamente el calendario económico del día en un canal de Discord.

## 1. Crear el webhook en Discord (2 minutos)
1. Ve al canal donde quieres las noticias → icono de engranaje ⚙️ → **Editar canal**.
2. En el menú izquierdo, **Integraciones** → **Webhooks** → **Nuevo webhook**.
3. Ponle un nombre (ej. "Forex Factory News") y pulsa **Copiar URL del webhook**.
4. Guarda esa URL, la necesitarás en el paso 3.

## 2. Subir este proyecto a GitHub
1. Crea un repositorio nuevo (puede ser privado) en GitHub.
2. Sube estos archivos tal cual (`ff_news_discord.py`, `requirements.txt`, la carpeta `.github/workflows/`).

## 3. Configurar el secreto del webhook
1. En tu repositorio: **Settings → Secrets and variables → Actions → New repository secret**.
2. Nombre: `DISCORD_WEBHOOK_URL`
3. Valor: pega la URL que copiaste en el paso 1.

## 4. Ajustar horario y filtros (opcional)
Edita `.github/workflows/ff-news.yml`:
- `cron: "0 7 * * *"` → hora en UTC a la que se enviará (usa https://crontab.guru para calcular).
- `FF_IMPACTS` → qué nivel de impacto incluir: `High`, `Medium`, `Low`, `Holiday` (separados por coma).
- `FF_CURRENCIES` → si quieres filtrar solo ciertas divisas, ej. `"USD,EUR,GBP"`. Déjalo vacío para todas.
- `FF_TIMEZONE` → zona horaria en la que se mostrarán las horas de los eventos (ej. `Europe/Madrid`).

## 5. Probarlo
En GitHub, ve a la pestaña **Actions** → selecciona el workflow **"Enviar noticias Forex Factory a Discord"** → **Run workflow** para probarlo manualmente sin esperar al horario programado.

A partir de ahí, se ejecutará solo todos los días a la hora configurada, sin que tengas que tener nada encendido.

## Alternativa: ejecutarlo en tu propio servidor/VPS
Si prefieres no usar GitHub Actions:
```bash
pip install -r requirements.txt
export DISCORD_WEBHOOK_URL="tu_url_aqui"
python ff_news_discord.py
```
Y añádelo a una tarea cron (Linux/Mac) o al Programador de tareas (Windows) para que se ejecute cada día a la hora que quieras.

## Notas
- El feed de Forex Factory usado es el JSON público semanal (`ff_calendar_thisweek.json`), el mismo que usan la mayoría de bots de este estilo. No requiere API key.
- Este feed solo trae datos de "esta semana" — el script filtra automáticamente los eventos del día en curso.
- Los valores "actual" (resultado real) no siempre están disponibles en este feed nada más publicarse el evento; solo previsión y valor anterior.
