"""بيانات Binance (عقود Futures الدائمة، مثل XAUUSDT) بدون مفاتيح API."""
import os
import time

import requests

BASE = os.getenv("BINANCE_URL", "https://fapi.binance.com")
INTERVAL = {1: "1m", 3: "3m", 5: "5m", 15: "15m", 30: "30m", 60: "1h", 240: "4h", 1440: "1d"}
_cache = {}


def _get(params):
    r = requests.get(BASE + "/fapi/v1/klines", params=params, timeout=15)
    if r.status_code != 200:
        raise RuntimeError("Binance: %s" % r.text[:200])
    return [{"t": int(k[0]), "o": float(k[1]), "h": float(k[2]), "l": float(k[3]),
             "c": float(k[4]), "v": float(k[5])} for k in r.json()]


def recent(symbol, minutes, limit=400):
    """آخر الشموع (آخر واحدة هي الشمعة الجارية)."""
    return _get({"symbol": symbol, "interval": INTERVAL[minutes], "limit": min(1500, int(limit))})


def history(symbol, minutes, days):
    """شموع آخر `days` يوم (مغلقة + الجارية)، مع ذاكرة مؤقتة لمدة دقيقة."""
    key = (symbol, minutes, days)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    start = int((time.time() - days * 86400) * 1000)
    out, end = [], None
    while True:
        params = {"symbol": symbol, "interval": INTERVAL[minutes], "limit": 1500, "startTime": start}
        if end:
            params["endTime"] = end
        part = _get(params)
        if not part:
            break
        out.extend(part)
        if len(part) < 1500:
            break
        start = part[-1]["t"] + 1
        if len(out) > 60000:
            break
    _cache[key] = (time.time(), out)
    return out
