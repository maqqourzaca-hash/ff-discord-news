#!/usr/bin/env python3
"""
Envía a un canal de Discord (vía webhook) el calendario económico
del día actual, obtenido del feed público de Forex Factory.

Uso:
    export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/xxx/yyy"
    python ff_news_discord.py

Variables de entorno opcionales:
    FF_IMPACTS   -> impactos a incluir, separados por coma (por defecto: "High,Medium")
                    valores posibles: High, Medium, Low, Holiday
    FF_CURRENCIES -> divisas a incluir, separadas por coma (por defecto: todas)
                     ej: "USD,EUR,GBP,JPY"
    FF_TIMEZONE  -> zona horaria para mostrar las horas (por defecto: "Europe/Madrid")
"""

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# Colores para el borde del embed de Discord, según el impacto
IMPACT_COLORS = {
    "High": 0xE74C3C,     # rojo
    "Medium": 0xF39C12,   # naranja
    "Low": 0xF1C40F,      # amarillo
    "Holiday": 0x95A5A6,  # gris
}

IMPACT_EMOJI = {
    "High": "🔴",
    "Medium": "🟠",
    "Low": "🟡",
    "Holiday": "⚪",
}


def get_config():
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        sys.exit("ERROR: falta la variable de entorno DISCORD_WEBHOOK_URL")

    impacts = os.environ.get("FF_IMPACTS", "High,Medium")
    impacts = {i.strip() for i in impacts.split(",") if i.strip()}

    currencies_env = os.environ.get("FF_CURRENCIES", "")
    currencies = {c.strip().upper() for c in currencies_env.split(",") if c.strip()}

    tz_name = os.environ.get("FF_TIMEZONE", "Europe/Madrid")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        sys.exit(f"ERROR: zona horaria inválida: {tz_name}")

    return webhook_url, impacts, currencies, tz


def fetch_events():
    resp = requests.get(FEED_URL, timeout=20)
    resp.raise_for_status()
    return resp.json()


def filter_today(events, tz, impacts, currencies):
    today = datetime.now(tz).date()
    filtered = []
    for ev in events:
        # El feed trae "date" en formato ISO 8601 con offset (ej: 2026-09-07T08:30:00-04:00)
        try:
            ev_dt = datetime.fromisoformat(ev["date"])
        except (KeyError, ValueError):
            continue
        ev_dt_local = ev_dt.astimezone(tz)
        if ev_dt_local.date() != today:
            continue
        if impacts and ev.get("impact") not in impacts:
            continue
        if currencies and ev.get("country", "").upper() not in currencies:
            continue
        filtered.append((ev_dt_local, ev))
    filtered.sort(key=lambda x: x[0])
    return filtered


def build_embeds(filtered, tz):
    if not filtered:
        return [{
            "title": "📅 Calendario económico de hoy",
            "description": "No hay eventos que coincidan con los filtros configurados para hoy.",
            "color": 0x2ECC71,
        }]

    lines = []
    for ev_dt_local, ev in filtered:
        impact = ev.get("impact", "Low")
        emoji = IMPACT_EMOJI.get(impact, "⚪")
        hora = ev_dt_local.strftime("%H:%M")
        title = ev.get("title", "Evento")
        country = ev.get("country", "")
        forecast = ev.get("forecast") or "—"
        previous = ev.get("previous") or "—"
        lines.append(
            f"{emoji} **{hora}** `{country}` — {title}\n"
            f"　　Previsión: `{forecast}`  ·  Anterior: `{previous}`"
        )

    # Discord limita cada campo/descripcion a 4096 caracteres, dividimos si hace falta
    embeds = []
    chunk = []
    length = 0
    for line in lines:
        if length + len(line) > 3800:
            embeds.append(chunk)
            chunk = []
            length = 0
        chunk.append(line)
        length += len(line)
    if chunk:
        embeds.append(chunk)

    today_str = datetime.now(tz).strftime("%A %d de %B, %Y")
    result = []
    for i, chunk in enumerate(embeds):
        result.append({
            "title": f"📅 Calendario económico — {today_str}" if i == 0 else "📅 (continuación)",
            "description": "\n\n".join(chunk),
            "color": 0x3498DB,
        })
    return result


def send_to_discord(webhook_url, embeds):
    payload = {
        "username": "Forex Factory News",
        "embeds": embeds,
    }
    resp = requests.post(webhook_url, json=payload, timeout=20)
    resp.raise_for_status()


def main():
    webhook_url, impacts, currencies, tz = get_config()
    events = fetch_events()
    filtered = filter_today(events, tz, impacts, currencies)
    embeds = build_embeds(filtered, tz)
    send_to_discord(webhook_url, embeds)
    print(f"Enviado correctamente: {len(filtered)} eventos.")


if __name__ == "__main__":
    main()
