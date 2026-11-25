
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

SYMBOL = "BTCEUR"
BASE_URLS = [
    "https://data-api.binance.vision",
    "https://api.binance.com",
]
MIN_CANDLES = 220


def get_json(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "BTC-Strategy-Monitor/1.0"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read())


def fetch_binance(path, params):
    query = urllib.parse.urlencode(params)
    errors = []

    for base in BASE_URLS:
        try:
            return get_json(f"{base}{path}?{query}")
        except Exception as exc:
            errors.append(f"{base}: {exc}")

    raise RuntimeError("Binance niet bereikbaar: " + " | ".join(errors))

def fetch_cmc_fear_greed():
    url = (
        "https://pro-api.coinmarketcap.com/"
        "public-api/v3/fear-and-greed/latest"
    )
    response = get_json(url)

    data = response.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("Ongeldig CoinMarketCap-antwoord")

    value = data.get("value")
    update_time = data.get("update_time")
    classification = data.get("value_classification")

    if not isinstance(value, int) or not 0 <= value <= 100:
        raise RuntimeError("Ongeldige Fear & Greed-waarde")

    if not update_time or not classification:
        raise RuntimeError("Fear & Greed-gegevens onvolledig")

    return {
        "value": value,
        "classification": classification,
        "update_time": update_time,
        "source": "CoinMarketCap"
    }


def sma(values, period):
    return sum(values[-period:]) / period


def rsi_wilder(closes, period=14):
    changes = [
        closes[i] - closes[i - 1]
        for i in range(1, len(closes))
    ]

    gains = [max(change, 0) for change in changes]
    losses = [max(-change, 0) for change in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(changes)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def main():
    now_ms = int(time.time() * 1000)

    ticker = fetch_binance(
        "/api/v3/ticker/price",
        {"symbol": SYMBOL}
    )
    current_price = float(ticker["price"])

    raw = fetch_binance(
        "/api/v3/klines",
        {"symbol": SYMBOL, "interval": "1d", "limit": 230}
    )

    if not isinstance(raw, list):
        raise RuntimeError("Ongeldig Binance-klineformaat")

    # Alleen volledig afgesloten candles gebruiken.
    candles = [
        row for row in raw
        if int(row[6]) < now_ms
    ]

    candles.sort(key=lambda row: int(row[0]))

    if len(candles) < MIN_CANDLES:
        raise RuntimeError(
            f"Onvoldoende afgesloten candles: {len(candles)}, "
            f"minimaal {MIN_CANDLES} vereist"
        )

    candles = candles[-MIN_CANDLES:]

    opens = [int(row[0]) for row in candles]
    closes = [float(row[4]) for row in candles]

    if any(not (value > 0) for value in closes):
        raise RuntimeError("Ongeldige slotkoers aangetroffen")

    if len(set(opens)) != len(opens):
        raise RuntimeError("Dubbele candle gevonden")

    expected_day = 86400000
    for previous, current in zip(opens, opens[1:]):
        if current - previous != expected_day:
            raise RuntimeError(
                "Ontbrekende of onregelmatige dagelijkse candle gevonden"
            )

    candle_date = datetime.fromtimestamp(
        opens[-1] / 1000, timezone.utc
    ).strftime("%Y-%m-%d")

    result = {
        "source": "Binance Spot",
        "symbol": SYMBOL,
        "interval": "1d",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "candle_date_utc": candle_date,
        "current_price_eur": current_price,
        "last_closed_daily_close_eur": closes[-1],
        "candles_used": len(candles),
        "sma20": sma(closes, 20),
        "sma50": sma(closes, 50),
        "sma200": sma(closes, 200),
        "rsi14_wilder": rsi_wilder(closes, 14),
        "validation": {
            "enough_candles": True,
            "chronological": True,
            "no_duplicate_candles": True,
            "no_missing_daily_candles": True,
            "current_candle_excluded": True
        }
    }

    with open("btc_data.json", "w", encoding="utf-8") as file:
        json.dump(result, file, indent=2, ensure_ascii=False)

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
