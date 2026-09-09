"""
Bias Board — Dashboard diario objetivo de sesgo de mercado.

Metodología (100% objetiva, sin discrecionalidad):
- Tendencia: SMA50 vs SMA200 (cruce estándar, "Golden/Death Cross" logic)
- Confirmación de tendencia: precio actual vs SMA50
- Fuerza de tendencia: ADX(14) — estándar de la industria
- Volatilidad: ATR(14) actual vs su media de 20 periodos (¿está más o menos
  volátil de lo normal?)

Regla de clasificación (fija y pública, no se ajusta después de ver resultados):
  ALCISTA CONFIRMADA  : close > SMA50 > SMA200  y ADX > 20
  BAJISTA CONFIRMADA  : close < SMA50 < SMA200  y ADX > 20
  EN RANGO / NEUTRAL  : cualquier otro caso (incluye ADX <= 20, que indica
                        ausencia de tendencia direccional clara)

Todos los valores numéricos crudos (SMA50, SMA200, ADX, ATR) se muestran
en la tabla para que cualquiera pueda auditar la conclusión.
"""

import os
import sys
import io
import requests
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ------------------------------------------------------------------
# Configuración
# ------------------------------------------------------------------

TWELVE_DATA_API_KEY = os.environ["TWELVE_DATA_API_KEY"]
DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOKBIAS_URL"]

# Símbolos en formato Twelve Data. Ajusta esta lista a los activos
# que sigas en tu comunidad.
SYMBOLS = [
    "XAU/USD",
    "EUR/USD",
    "GBP/USD",
    "USD/JPY",
    "AUD/USD",
    "USD/CAD",
    "USD/CHF",
    "DXY",
]

TWELVE_DATA_URL = "https://api.twelvedata.com/time_series"

# Necesitamos suficiente histórico para calcular SMA200 + ADX/ATR con margen.
OUTPUT_SIZE = 260  # ~1 año de velas diarias


# ------------------------------------------------------------------
# Obtención de datos
# ------------------------------------------------------------------

def fetch_daily_series(symbol: str) -> pd.DataFrame:
    """Descarga velas diarias OHLC para un símbolo desde Twelve Data."""
    params = {
        "symbol": symbol,
        "interval": "1day",
        "outputsize": OUTPUT_SIZE,
        "apikey": TWELVE_DATA_API_KEY,
        "order": "ASC",  # más antiguo -> más reciente
    }
    resp = requests.get(TWELVE_DATA_URL, params=params, timeout=30)
    data = resp.json()

    if "values" not in data:
        raise RuntimeError(f"Error al obtener {symbol}: {data}")

    df = pd.DataFrame(data["values"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float)
    df = df.sort_values("datetime").reset_index(drop=True)
    return df


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
    adx = dx.rolling(window=length).mean()
    return adx


def classify_bias(close: float, sma50: float, sma200: float, adx: float) -> str:
    """Regla fija y pública. No discrecional."""
    if pd.isna(sma50) or pd.isna(sma200) or pd.isna(adx):
        return "Datos insuficientes"
    if close > sma50 > sma200 and adx > 20:
        return "Alcista confirmada"
    if close < sma50 < sma200 and adx > 20:
        return "Bajista confirmada"
    return "Rango / Neutral"


# ------------------------------------------------------------------
# Pipeline principal
# ------------------------------------------------------------------

def build_dataset() -> pd.DataFrame:
    rows = []
    for symbol in SYMBOLS:
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

        bias = classify_bias(last["close"], last["SMA50"], last["SMA200"], last["ADX14"])

        rows.append({
            "Activo": symbol,
            "Sesgo": bias,
            "Var 1D": f"{var_1d:+.2f}%",
            "Var 5D": f"{var_5d:+.2f}%",
            "ADX(14)": f"{last['ADX14']:.1f}" if pd.notna(last["ADX14"]) else "N/D",
            "Vol. relativa": f"{vol_relativa:+.0f}%" if pd.notna(vol_relativa) else "N/D",
        })

    return pd.DataFrame(rows)


def render_table_image(df: pd.DataFrame, path: str):
    fig, ax = plt.subplots(figsize=(9, 0.55 * len(df) + 1.5))
    ax.axis("off")

    colors = []
    for bias in df["Sesgo"]:
        if bias == "Alcista confirmada":
            colors.append(["#d9f2e3"] * len(df.columns))
        elif bias == "Bajista confirmada":
            colors.append(["#fde2e2"] * len(df.columns))
        else:
            colors.append(["#f0f0f0"] * len(df.columns))

    table = ax.table(
        cellText=df.values,
        colLabels=df.columns,
        cellColours=colors,
        loc="center",
        cellLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(11)
    table.scale(1, 1.8)

    ax.set_title(
        "Bias Board — Sesgo objetivo diario\n"
        "Metodología: SMA50/SMA200 + ADX(14) | Datos: Twelve Data",
        fontsize=12, pad=20, loc="left",
    )

    plt.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def send_to_discord(image_path: str, df: pd.DataFrame):
    n_alcista = (df["Sesgo"] == "Alcista confirmada").sum()
    n_bajista = (df["Sesgo"] == "Bajista confirmada").sum()
    n_rango = (df["Sesgo"] == "Rango / Neutral").sum()

    content = (
        f"**Bias Board diario** — {pd.Timestamp.utcnow().strftime('%Y-%m-%d')}\n"
        f"Alcista: {n_alcista} | Bajista: {n_bajista} | Rango: {n_rango}\n"
        f"_Metodología objetiva: SMA50/SMA200 + ADX(14). No es consejo de inversión._"
    )

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
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
