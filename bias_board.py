"""
Bias Board — Dashboard diario objetivo de sesgo de mercado.

Metodología (100% objetiva, fija y pública — no se ajusta después de ver
resultados):
- Tendencia: SMA50 vs SMA200 (cruce estándar usado en toda la industria)
- Confirmación: precio actual respecto a la SMA50
- Fuerza de la tendencia: ADX(14) — indicador estándar, objetivo
- Volatilidad relativa: ATR(14) actual vs su media de 20 periodos

Regla de clasificación (auditable, siempre la misma):
  ALCISTA  : close > SMA50 > SMA200  y ADX > 20
  BAJISTA  : close < SMA50 < SMA200  y ADX > 20
  SIN TENDENCIA CLARA : cualquier otro caso (incluye ADX <= 20, que
                        significa que no hay una dirección dominante)

Todos los valores numéricos crudos se muestran en la tabla para que
cualquier miembro pueda comprobar por qué se llegó a esa conclusión.
"""

import os
import sys
import requests
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

# ------------------------------------------------------------------
# Configuración
# ------------------------------------------------------------------

TWELVE_DATA_API_KEY = os.environ["TWELVE_DATA_API_KEY"]
DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOKBIAS_URL"]

NOMBRE_COMUNIDAD = "SKYPIPS ACADEMY"  # cámbialo si quieres otro texto en la cabecera

# Símbolo en Twelve Data -> nombre a mostrar en la tabla.
# NAS100 y SP500 se siguen vía ETF (QQQ/SPY) porque los símbolos nativos de
# índice (NDX/SPX) son poco fiables en el plan gratuito de Twelve Data.
# Se etiquetan como "(proxy)" para ser transparentes con la comunidad:
# el ETF sigue el índice casi 1:1 en dirección, pero no es el futuro exacto.
ASSETS = [
    ("XAU/USD", "XAU/USD (Oro)"),
    ("XAG/USD", "XAG/USD (Plata)"),
    ("EUR/USD", "EUR/USD"),
    ("GBP/USD", "GBP/USD"),
    ("DXY",     "DXY (Índice USD)"),
    ("QQQ",     "NAS100 (proxy QQQ)"),
    ("SPY",     "SP500 (proxy SPY)"),
]

TWELVE_DATA_URL = "https://api.twelvedata.com/time_series"
OUTPUT_SIZE = 260  # ~1 año de velas diarias, margen suficiente para SMA200

# Paleta oscura, pensada para verse bien dentro de Discord (tema oscuro)
BG_COLOR = "#1e2124"
PANEL_COLOR = "#26292c"
HEADER_COLOR = "#2f3136"
TEXT_COLOR = "#f2f3f5"
MUTED_COLOR = "#9aa0a6"
GREEN = "#3ba55d"
RED = "#ed4245"
GRAY = "#a3a6aa"


# ------------------------------------------------------------------
# Obtención de datos
# ------------------------------------------------------------------

def fetch_daily_series(symbol: str) -> pd.DataFrame:
    params = {
        "symbol": symbol,
        "interval": "1day",
        "outputsize": OUTPUT_SIZE,
        "apikey": TWELVE_DATA_API_KEY,
        "order": "ASC",
    }
    resp = requests.get(TWELVE_DATA_URL, params=params, timeout=30)
    data = resp.json()

    if "values" not in data:
        raise RuntimeError(f"Error al obtener {symbol}: {data}")

    df = pd.DataFrame(data["values"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float)
    return df.sort_values("datetime").reset_index(drop=True)


# ------------------------------------------------------------------
# Indicadores objetivos (implementación manual, sin dependencias frágiles)
# ------------------------------------------------------------------

def compute_sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(window=length).mean()


def compute_atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window=length).mean()


def compute_adx(df: pd.DataFrame, length: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_high, prev_low, prev_close = high.shift(1), low.shift(1), close.shift(1)

    plus_dm = (high - prev_high).where(
        (high - prev_high) > (prev_low - low), 0.0
    ).clip(lower=0)
    minus_dm = (prev_low - low).where(
        (prev_low - low) > (high - prev_high), 0.0
    ).clip(lower=0)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    atr = tr.rolling(window=length).mean()
    plus_di = 100 * (plus_dm.rolling(window=length).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(window=length).mean() / atr)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return dx.rolling(window=length).mean()


def classify_bias(close: float, sma50: float, sma200: float, adx: float):
    """Devuelve (etiqueta, flecha, color). Regla fija y pública."""
    if pd.isna(sma50) or pd.isna(sma200) or pd.isna(adx):
        return "Datos insuficientes", "?", GRAY
    if close > sma50 > sma200 and adx > 20:
        return "Alcista", "▲", GREEN
    if close < sma50 < sma200 and adx > 20:
        return "Bajista", "▼", RED
    return "Neutral", "➔", GRAY


# ------------------------------------------------------------------
# Pipeline principal
# ------------------------------------------------------------------

def build_dataset() -> pd.DataFrame:
    rows = []
    for symbol, display_name in ASSETS:
        try:
            df = fetch_daily_series(symbol)
        except Exception as exc:
            print(f"[AVISO] No se pudo obtener {symbol}: {exc}", file=sys.stderr)
            continue

        df["SMA50"] = compute_sma(df["close"], 50)
        df["SMA200"] = compute_sma(df["close"], 200)
        df["ATR14"] = compute_atr(df, 14)
        df["ADX14"] = compute_adx(df, 14)
        df["ATR_avg20"] = df["ATR14"].rolling(window=20).mean()

        last = df.iloc[-1]
        prev_1d = df.iloc[-2]
        prev_5d = df.iloc[-6] if len(df) > 6 else df.iloc[0]

        var_1d = (last["close"] / prev_1d["close"] - 1) * 100
        var_5d = (last["close"] / prev_5d["close"] - 1) * 100
        vol_relativa = (
            (last["ATR14"] / last["ATR_avg20"] - 1) * 100
            if pd.notna(last["ATR_avg20"]) and last["ATR_avg20"] != 0
            else float("nan")
        )

        etiqueta, flecha, color = classify_bias(
            last["close"], last["SMA50"], last["SMA200"], last["ADX14"]
        )

        rows.append({
            "Activo": display_name,
            "Sesgo": etiqueta,
            "Flecha": flecha,
            "Color": color,
            "Var 1D": var_1d,
            "Var 5D": var_5d,
            "ADX": last["ADX14"],
            "VolRel": vol_relativa,
        })

    return pd.DataFrame(rows)


# ------------------------------------------------------------------
# Render de la imagen (diseño oscuro, con leyenda explicativa)
# ------------------------------------------------------------------

def render_table_image(df: pd.DataFrame, path: str):
    n = len(df)
    fig = plt.figure(figsize=(9.5, 1.1 * n + 4.6), facecolor=BG_COLOR)
    gs = GridSpec(3, 1, height_ratios=[1.1, 0.11 * n + 1.4, 2.1], hspace=0.05)

    # --- Cabecera -----------------------------------------------------
    ax_header = fig.add_subplot(gs[0])
    ax_header.axis("off")
    ax_header.set_facecolor(BG_COLOR)
    fecha = pd.Timestamp.utcnow().strftime("%d/%m/%Y")
    ax_header.text(0.02, 0.75, NOMBRE_COMUNIDAD, fontsize=13, color=MUTED_COLOR,
                    fontweight="bold", ha="left", va="top", transform=ax_header.transAxes)
    ax_header.text(0.02, 0.35, "Bias Board diario", fontsize=22, color=TEXT_COLOR,
                    fontweight="bold", ha="left", va="top", transform=ax_header.transAxes)
    ax_header.text(0.02, 0.02, f"{fecha}  ·  Sesgo técnico objetivo por activo",
                    fontsize=11, color=MUTED_COLOR, ha="left", va="top",
                    transform=ax_header.transAxes)

    # --- Tabla ----------------------------------------------------------
    ax = fig.add_subplot(gs[1])
    ax.axis("off")
    ax.set_facecolor(BG_COLOR)

    col_labels = ["Activo", "Sesgo", "Var. 1 día", "Var. 5 días", "Volatilidad"]
    row_height = 1.0 / (n + 1)

    # cabecera de columnas
    col_x = [0.02, 0.37, 0.58, 0.75, 0.90]
    for x, label in zip(col_x, col_labels):
        ax.text(x, 1 - row_height * 0.5, label, fontsize=10.5, color=MUTED_COLOR,
                 fontweight="bold", ha="left", va="center")
    ax.axhline(1 - row_height, color="#3a3d41", linewidth=1)

    for i, row in df.iterrows():
        y = 1 - row_height * (i + 1.5)
        # franja de fondo alterna
        if i % 2 == 0:
            ax.axhspan(y - row_height / 2, y + row_height / 2, color=PANEL_COLOR, zorder=0)

        ax.text(col_x[0], y, row["Activo"], fontsize=11, color=TEXT_COLOR, va="center")

        ax.text(col_x[1], y, f'{row["Flecha"]}  {row["Sesgo"]}', fontsize=11,
                 color=row["Color"], fontweight="bold", va="center")

        var1_color = GREEN if row["Var 1D"] >= 0 else RED
        ax.text(col_x[2], y, f'{row["Var 1D"]:+.2f}%', fontsize=11, color=var1_color, va="center")

        var5_color = GREEN if row["Var 5D"] >= 0 else RED
        ax.text(col_x[3], y, f'{row["Var 5D"]:+.2f}%', fontsize=11, color=var5_color, va="center")

        if pd.notna(row["VolRel"]):
            vol_texto = "Alta" if row["VolRel"] > 15 else ("Baja" if row["VolRel"] < -15 else "Normal")
        else:
            vol_texto = "N/D"
        ax.text(col_x[4], y, vol_texto, fontsize=11, color=MUTED_COLOR, va="center")

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    # --- Leyenda / explicación en lenguaje llano ------------------------
    ax_legend = fig.add_subplot(gs[2])
    ax_legend.axis("off")
    ax_legend.set_facecolor(BG_COLOR)

    leyenda_titulo = "¿Cómo se lee esta tabla?"
    leyenda_texto = (
        "▲ Alcista / ▼ Bajista: la tendencia técnica está confirmada (precio y medias\n"
        "móviles alineados, con fuerza direccional suficiente). ➔ Neutral:\n"
        "el activo está en rango, sin una dirección dominante por ahora.\n\n"
        "Var. 1 día / 5 días: variación real del precio en ese periodo.\n"
        "Volatilidad: si el activo se está moviendo más (Alta), menos (Baja) o igual\n"
        "(Normal) que su comportamiento habitual de las últimas semanas.\n\n"
        "Metodología fija: cruce SMA50/SMA200 + ADX(14) > 20. Datos: Twelve Data.\n"
        "Es matemática aplicada de forma constante, no una opinión — la misma\n"
        "fórmula siempre da el mismo resultado sobre los mismos datos.\n\n"
        "El mercado es impredecible y no existe \"la verdad del mercado\": esto es\n"
        "un mapa objetivo del estado actual, no una señal de entrada. Cada trader\n"
        "debe hacer su propio análisis técnico antes de operar."
    )
    ax_legend.text(0.02, 0.95, leyenda_titulo, fontsize=12, color=TEXT_COLOR,
                    fontweight="bold", ha="left", va="top", transform=ax_legend.transAxes)
    ax_legend.text(0.02, 0.82, leyenda_texto, fontsize=9.5, color=MUTED_COLOR,
                    ha="left", va="top", transform=ax_legend.transAxes, linespacing=1.6)

    fig.patch.set_facecolor(BG_COLOR)
    plt.savefig(path, dpi=200, bbox_inches="tight", facecolor=BG_COLOR)
    plt.close(fig)


def send_to_discord(image_path: str, df: pd.DataFrame):
    ahora = pd.Timestamp.utcnow()
    hora_txt = ahora.strftime("%H:%M UTC")
    fecha_txt = ahora.strftime("%d/%m/%Y")

    content = f"**📊 Bias Board — {NOMBRE_COMUNIDAD}** · {fecha_txt} {hora_txt}"

    with open(image_path, "rb") as f:
        files = {"file": ("bias_board.png", f, "image/png")}
        payload = {"content": content}
        resp = requests.post(DISCORD_WEBHOOK_URL, data=payload, files=files, timeout=30)
        resp.raise_for_status()


def main():
    df = build_dataset()
    if df.empty:
        print("No se obtuvo ningún dato. Abortando.", file=sys.stderr)
        sys.exit(1)

    image_path = "/tmp/bias_board.png"
    render_table_image(df, image_path)
    send_to_discord(image_path, df)
    print("Bias Board enviado correctamente.")
    print(df.drop(columns=["Color", "Flecha"]).to_string(index=False))


if __name__ == "__main__":
    main()
