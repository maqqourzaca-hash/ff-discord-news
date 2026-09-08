#!/usr/bin/env python3
"""
Envía al mismo canal de Discord un resumen de los eventos económicos
importantes de LA SEMANA QUE EMPIEZA, usando el feed de Forex Factory.

Pensado para ejecutarse el LUNES muy pronto por la mañana (ver
.github/workflows/ff-weekly.yml), justo después de que el feed "esta
semana" de Forex Factory rote a la semana que acaba de empezar.

Añade:
    - Un párrafo introductorio en lenguaje natural sobre qué días concentran
      la volatilidad esperada (solo a partir de datos reales del feed).
    - Una etiqueta de volatilidad por día (Alta / Moderada / Tranquilo).
    - Una frase de contexto breve para eventos clave reconocidos
      (FOMC, CPI, NFP, decisiones de tipos, PIB, PMI...), solo cuando el
      título del evento coincide con uno de esos patrones conocidos.

No inventa horas ni eventos que no vengan en el feed: si un día no trae
eventos que pasen los filtros, se muestra tal cual como "sin eventos".

Variables de entorno (se reutilizan los mismos filtros que el aviso diario):
    DISCORD_WEBHOOK_URL  -> (obligatoria) URL del webhook de Discord
    FF_IMPACTS           -> por defecto "High,Medium,Holiday"
    FF_CURRENCIES        -> por defecto "EUR,GBP,USD"
    FF_TIMEZONE          -> por defecto "Europe/Madrid"
"""

import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

IMPACT_EMOJI = {
    "High": "🔴",
    "Medium": "🟠",
    "Low": "🟡",
    "Holiday": "⚪",
}

DIAS_ES = {
    "Monday": "Lunes",
    "Tuesday": "Martes",
    "Wednesday": "Miércoles",
    "Thursday": "Jueves",
    "Friday": "Viernes",
    "Saturday": "Sábado",
    "Sunday": "Domingo",
}

# Patrones (regex, sin distinguir mayúsculas) -> frase de contexto breve.
# Se aplica solo al primer patrón que coincida con el título del evento.
CONTEXTOS = [
    (r"fomc|federal funds rate|fed interest rate|monetary policy statement.*fed",
     "El mercado espera si la Fed mantiene, sube o baja los tipos de interés — suele mover fuerte al USD y al oro."),
    (r"\bcpi\b|consumer price index|inflation rate",
     "Mide la inflación; una sorpresa respecto a la previsión suele generar movimientos bruscos."),
    (r"non-?farm|nfp|employment change",
     "El informe de empleo más seguido del mes; históricamente uno de los que más volatilidad genera en USD."),
    (r"interest rate|rate decision|monetary policy statement|refinancing rate",
     "Decisión de tipos de interés; puede mover con fuerza la divisa correspondiente."),
    (r"\bgdp\b|gross domestic product",
     "Mide el crecimiento económico del país en el periodo."),
    (r"retail sales",
     "Termómetro del consumo; relevante para la fortaleza de la economía."),
    (r"unemployment rate|jobless claims|unemployment claims",
     "Dato de empleo relevante para las expectativas de política monetaria."),
    (r"\bpmi\b",
     "Indicador adelantado de la actividad económica del sector."),
    (r"press conference",
     "Rueda de prensa donde suele haber pistas sobre próximos movimientos de política monetaria."),
]


def get_config():
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        sys.exit("ERROR: falta la variable de entorno DISCORD_WEBHOOK_URL")

    impacts = os.environ.get("FF_IMPACTS", "High,Medium,Holiday")
    impacts = {i.strip() for i in impacts.split(",") if i.strip()}

    currencies_env = os.environ.get("FF_CURRENCIES", "EUR,GBP,USD")
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


def filter_and_group(events, tz, impacts, currencies):
    by_day = defaultdict(list)
    for ev in events:
        try:
            ev_dt = datetime.fromisoformat(ev["date"])
        except (KeyError, ValueError):
            continue
        ev_dt_local = ev_dt.astimezone(tz)

        if impacts and ev.get("impact") not in impacts:
            continue
        if currencies and ev.get("country", "").upper() not in currencies:
            continue

        by_day[ev_dt_local.date()].append((ev_dt_local, ev))

    for day in by_day:
        by_day[day].sort(key=lambda x: x[0])

    return dict(sorted(by_day.items()))


def contexto_para(titulo):
    for patron, frase in CONTEXTOS:
        if re.search(patron, titulo, re.IGNORECASE):
            return frase
    return None


def dia_es(day):
    return DIAS_ES.get(day.strftime("%A"), day.strftime("%A"))


def nivel_dia(events):
    """Devuelve (emoji, etiqueta) según el impacto más alto real del día.
    Los festivos (Holiday) no cuentan para el nivel de volatilidad."""
    impactos = {ev.get("impact") for _, ev in events}
    if "High" in impactos:
        return "🔴", "Alta volatilidad esperada"
    if "Medium" in impactos:
        return "🟠", "Volatilidad moderada"
    return "🟢", "Tranquilo"


def build_intro(by_day):
    dias_altos = []  # (day, [titulos High])
    dias_medios = []
    dias_tranquilos = []

    for day, events in by_day.items():
        impactos_dia = {ev.get("impact") for _, ev in events}
        if "High" in impactos_dia:
            titulos = [ev["title"] for _, ev in events if ev.get("impact") == "High"]
            dias_altos.append((day, titulos))
        elif "Medium" in impactos_dia:
            dias_medios.append(day)
        else:
            dias_tranquilos.append(day)

    if not dias_altos and not dias_medios:
        return "Semana tranquila según tus filtros: no se esperan eventos de impacto alto o medio."

    partes = []
    if dias_altos:
        frases = []
        for day, titulos in dias_altos:
            titulos_str = " y ".join(dict.fromkeys(titulos[:2]))  # sin duplicados, máx 2
            frases.append(f"el {dia_es(day).lower()} ({titulos_str})")
        partes.append("Semana con volatilidad alta esperada: " + ", ".join(frases) + ".")

    if dias_medios:
        dias_str = ", ".join(dia_es(d) for d in dias_medios)
        partes.append(f"Impacto moderado el {dias_str}.")

    if dias_tranquilos and (dias_altos or dias_medios):
        dias_str = ", ".join(dia_es(d) for d in dias_tranquilos)
        partes.append(f"El resto de días ({dias_str}) se esperan más tranquilos.")

    return " ".join(partes)


def build_embeds(by_day):
    if not by_day:
        return [{
            "title": "🗓️ Vista previa semanal",
            "description": "No hay eventos que coincidan con los filtros configurados para la semana que viene.",
            "color": 0x2ECC71,
        }]

    first_day = next(iter(by_day))
    last_day = list(by_day)[-1]
    rango = f"{first_day.strftime('%d/%m')} - {last_day.strftime('%d/%m')}"

    intro = build_intro(by_day)

    blocks = [intro]
    for day, events in by_day.items():
        emoji_dia, etiqueta_dia = nivel_dia(events)
        lines = [f"**{dia_es(day)} {day.strftime('%d/%m')} — {emoji_dia} {etiqueta_dia}**"]

        if not events:
            lines.append("_Sin eventos que coincidan con los filtros._")
        else:
            for ev_dt_local, ev in events:
                impact = ev.get("impact", "Low")
                emoji = IMPACT_EMOJI.get(impact, "⚪")
                hora = ev_dt_local.strftime("%H:%M")
                country = ev.get("country", "")
                title = ev.get("title", "Evento")
                lines.append(f"{emoji} `{hora}` `{country}` — {title}")

                if impact == "High":
                    nota = contexto_para(title)
                    if nota:
                        lines.append(f"　　_{nota}_")

        blocks.append("\n".join(lines))

    # Discord limita cada descripción a 4096 caracteres; dividimos en varios embeds si hace falta
    embeds = []
    chunk = []
    length = 0
    for block in blocks:
        if length + len(block) > 3800:
            embeds.append(chunk)
            chunk = []
            length = 0
        chunk.append(block)
        length += len(block)
    if chunk:
        embeds.append(chunk)

    result = []
    for i, chunk in enumerate(embeds):
        result.append({
            "title": f"🗓️ Vista previa semanal ({rango})" if i == 0 else "🗓️ (continuación)",
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
    by_day = filter_and_group(events, tz, impacts, currencies)
    embeds = build_embeds(by_day)
    send_to_discord(webhook_url, embeds)
    total = sum(len(v) for v in by_day.values())
    print(f"Enviado correctamente: {total} eventos en {len(by_day)} días.")


if __name__ == "__main__":
    main()
