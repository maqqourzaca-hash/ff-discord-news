#!/usr/bin/env python3
"""
Envía a Discord un informe semanal del COT (Commitment of Traders) de la CFTC
para los instrumentos que se operan en la comunidad: DXY, EURUSD, GBPUSD y XAUUSD.

Fuente de datos: API pública de la CFTC (Socrata), informe "Legacy - Futures Only".
La CFTC publica este informe cada VIERNES a las 15:30 hora de Nueva York, con datos
de posiciones del martes anterior. Por eso este script está pensado para ejecutarse
el SÁBADO por la mañana (ver .github/workflows/ff-cot.yml), con margen de sobra.

Qué muestra por cada instrumento:
    - Posición neta de los "Non-Commercial" (grandes especuladores/fondos):
      posiciones largas menos cortas.
    - Cambio de esa posición neta respecto al informe de la semana anterior.
    - Esa posición neta como % del interés abierto total (para ver si es una
      posición relevante o marginal).

Importante: el COT es un dato de SESGO de posicionamiento, no una señal de
entrada. Se ofrece como contexto fundamental para contrastar con el análisis
técnico de cada trader, no como recomendación de operativa.

Variables de entorno:
    DISCORD_WEBHOOK_URL_COT  -> (obligatoria) URL del webhook del canal #informe-cot
"""

import os
import sys
from datetime import datetime

import requests

CFTC_API = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"

# (etiqueta a mostrar, nombre exacto en el feed de la CFTC, tipo de lectura)
# tipo "directo": net largo = sesgo alcista en el propio instrumento (EUR, GBP, Oro)
# tipo "dxy": net largo = sesgo alcista en USD -> normalmente sesgo bajista en pares EURUSD/GBPUSD
INSTRUMENTOS = [
    ("DXY (USD Index)", "USD INDEX - ICE FUTURES U.S.", "dxy"),
    ("EURUSD (Euro FX)", "EURO FX - CHICAGO MERCANTILE EXCHANGE", "directo"),
    ("GBPUSD (British Pound)", "BRITISH POUND STERLING - CHICAGO MERCANTILE EXCHANGE", "directo"),
    ("XAUUSD (Gold)", "GOLD - COMMODITY EXCHANGE INC.", "directo"),
]


def get_config():
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL_COT")
    if not webhook_url:
        sys.exit("ERROR: falta la variable de entorno DISCORD_WEBHOOK_URL_COT")
    return webhook_url


def fetch_last_two_reports(market_name):
    params = {
        "market_and_exchange_names": market_name,
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$limit": 2,
    }
    resp = requests.get(CFTC_API, params=params, timeout=20)
    resp.raise_for_status()
    return resp.json()


def analizar_instrumento(label, market_name, tipo):
    rows = fetch_last_two_reports(market_name)
    if not rows:
        return {
            "label": label,
            "ok": False,
            "motivo": "No se encontraron datos para este mercado en el feed de la CFTC.",
        }

    actual = rows[0]
    anterior = rows[1] if len(rows) > 1 else None

    try:
        long_actual = int(actual["noncomm_positions_long_all"])
        short_actual = int(actual["noncomm_positions_short_all"])
        open_interest = int(actual.get("open_interest_all", 0) or 0)
    except (KeyError, ValueError):
        return {
            "label": label,
            "ok": False,
            "motivo": "Formato de datos inesperado en la respuesta de la CFTC.",
        }

    net_actual = long_actual - short_actual
    pct_oi = (net_actual / open_interest * 100) if open_interest else None

    cambio = None
    if anterior:
        try:
            long_ant = int(anterior["noncomm_positions_long_all"])
            short_ant = int(anterior["noncomm_positions_short_all"])
            cambio = net_actual - (long_ant - short_ant)
        except (KeyError, ValueError):
            cambio = None

    fecha = actual.get("report_date_as_yyyy_mm_dd", "")[:10]

    return {
        "label": label,
        "ok": True,
        "fecha": fecha,
        "net": net_actual,
        "cambio": cambio,
        "pct_oi": pct_oi,
        "tipo": tipo,
    }


def describir_cambio(cambio):
    if cambio is None:
        return "sin dato de la semana anterior para comparar"
    if cambio > 0:
        return "aumentando su posición" if cambio > 0 else ""
    if cambio < 0:
        return "reduciendo su posición"
    return "sin apenas cambios respecto a la semana anterior"


def interpretar(resultado):
    net = resultado["net"]
    cambio = resultado["cambio"]
    tipo = resultado["tipo"]

    if tipo == "directo":
        if net > 0:
            postura = "netos largos"
            sesgo = "alcista"
        elif net < 0:
            postura = "netos cortos"
            sesgo = "bajista"
        else:
            postura = "prácticamente planos"
            sesgo = "neutral"

        if cambio is not None and cambio != 0:
            direccion_cambio = "aumentando" if (cambio > 0) == (net >= 0) else "reduciendo"
            matiz = f", {direccion_cambio} convicción en ese sesgo esta semana"
        else:
            matiz = ""

        return (
            f"Los grandes especuladores están {postura} en este mercado{matiz}. "
            f"Esto sugiere un sesgo de fondo **{sesgo}** para el par."
        )

    else:  # dxy
        if net > 0:
            postura = "netos largos de USD"
            sesgo_usd = "alcista"
            efecto = "bajista para EURUSD y GBPUSD"
        elif net < 0:
            postura = "netos cortos de USD"
            sesgo_usd = "bajista"
            efecto = "alcista para EURUSD y GBPUSD"
        else:
            postura = "prácticamente planos en USD"
            sesgo_usd = "neutral"
            efecto = "sin sesgo claro para los pares de USD"

        if cambio is not None and cambio != 0:
            direccion_cambio = "aumentando" if (cambio > 0) == (net >= 0) else "reduciendo"
            matiz = f", {direccion_cambio} convicción en esa postura esta semana"
        else:
            matiz = ""

        return (
            f"Los grandes especuladores están {postura}{matiz}. "
            f"Esto apunta a un sesgo **{sesgo_usd}** en el dólar, orientativamente **{efecto}**."
        )


def build_embed(resultados):
    fecha_informe = next((r["fecha"] for r in resultados if r.get("ok")), None)
    titulo = f"📑 Informe COT semanal ({fecha_informe})" if fecha_informe else "📑 Informe COT semanal"

    bloques = []
    for r in resultados:
        if not r.get("ok"):
            bloques.append(f"**{r['label']}**\n⚠️ {r['motivo']}")
            continue

        net = r["net"]
        cambio = r["cambio"]
        pct_oi = r["pct_oi"]

        signo_net = "+" if net > 0 else ""
        linea_net = f"Posición neta: `{signo_net}{net:,}` contratos"
        if pct_oi is not None:
            linea_net += f" (`{pct_oi:+.1f}%` del interés abierto)"

        if cambio is not None:
            signo_cambio = "+" if cambio > 0 else ""
            linea_cambio = f"Cambio semanal: `{signo_cambio}{cambio:,}` contratos"
        else:
            linea_cambio = "Cambio semanal: sin dato de la semana anterior"

        interpretacion = interpretar(r)

        bloques.append(
            f"**{r['label']}**\n{linea_net}\n{linea_cambio}\n{interpretacion}"
        )

    disclaimer = (
        "⚠️ _Recordatorio: esto es un dato de **sesgo de posicionamiento** de los grandes "
        "especuladores, no una señal de entrada. Contrastadlo siempre con vuestro propio "
        "análisis técnico antes de operar._"
    )
    bloques.append(disclaimer)

    descripcion = "\n\n".join(bloques)

    return {
        "title": titulo,
        "description": descripcion,
        "color": 0x9B59B6,
        "footer": {"text": "Fuente: CFTC (Commitments of Traders, Legacy Futures Only)"},
    }


def send_to_discord(webhook_url, embed):
    payload = {
        "username": "Forex Factory News",
        "embeds": [embed],
    }
    resp = requests.post(webhook_url, json=payload, timeout=20)
    resp.raise_for_status()


def main():
    webhook_url = get_config()

    resultados = []
    for label, market_name, tipo in INSTRUMENTOS:
        resultados.append(analizar_instrumento(label, market_name, tipo))

    embed = build_embed(resultados)
    send_to_discord(webhook_url, embed)

    ok_count = sum(1 for r in resultados if r.get("ok"))
    print(f"Informe COT enviado: {ok_count}/{len(resultados)} instrumentos con datos.")


if __name__ == "__main__":
    main()
