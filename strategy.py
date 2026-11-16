"""
الدخول على فريم صغير (15 دقيقة افتراضياً):
  بيع : سحب سيولة فوق القمة ثم إغلاق شمعة داخل المدى  → هدف 1 = 50% ، هدف 2 = القاع
  شراء: سحب سيولة تحت القاع ثم إغلاق شمعة داخل المدى → هدف 1 = 50% ، هدف 2 = القمة
لا تداول إذا كان السعر يتذبذب حول مستوى 50%.
"""
import time

import requests

DAY = 86400000
TFM = {"1": 1, "3": 3, "5": 5, "15": 15, "30": 30, "60": 60}
BYBIT = "https://api.bybit.com/v5/market/kline"
BINANCE = "https://data-api.binance.vision/api/v3/klines"

DEF = {"exchange": "bybit", "symbol": "BTCUSDT", "tf": "15",
       "sl_buf": 0.05,   # هامش إضافي للوقف خلف قمة/قاع السحب (% من السعر)
       "be_on": 1,       # نقل الوقف إلى الدخول بعد TP1
       "once": 1,        # صفقة واحدة لكل اتجاه في اليوم
       "chop_on": 1, "chop_n": 24, "chop_x": 4}   # فلتر التذبذب حول 50%


# ---------------------------------------------------------------- البيانات
def _page(ex, symbol, tf, end_ms, limit):
    """صفحة شموع مرتبة من الأقدم للأحدث: [{t,o,h,l,c,v}]."""
    if ex == "bybit":
        p = {"category": "linear", "symbol": symbol, "interval": "D" if tf == "D" else tf, "limit": limit}
        if end_ms:
            p["end"] = end_ms
        j = requests.get(BYBIT, params=p, timeout=15).json()
        if j.get("retCode") != 0:
            raise RuntimeError(j.get("retMsg", "bybit error"))
        rows = list(reversed(j["result"]["list"]))
    else:
        iv = {"D": "1d", "60": "1h"}.get(tf, tf + "m")
        p = {"symbol": symbol, "interval": iv, "limit": limit}
        if end_ms:
            p["endTime"] = end_ms
        j = requests.get(BINANCE, params=p, timeout=15).json()
        if not isinstance(j, list):
            raise RuntimeError(str(j.get("msg", "binance error")))
        rows = j
    return [{"t": int(k[0]), "o": float(k[1]), "h": float(k[2]), "l": float(k[3]),
             "c": float(k[4]), "v": float(k[5])} for k in rows]


def _order(ex):
    return [ex, "binance" if ex == "bybit" else "bybit"]   # عند فشل منصة نجرّب الأخرى


def fetch_recent(ex, symbol, tf, n=200):
    last = None
    for e in _order(ex):
        try:
            p = _page(e, symbol, tf, None, n)
            if p:
                return p, e
        except Exception as x:
            last = x
    raise RuntimeError("تعذّر جلب البيانات: %s" % last)


def fetch_range(ex, symbol, tf, start_ms):
    last = None
    for e in _order(ex):
        try:
            out, end = [], int(time.time() * 1000)
            while end > start_ms:
                page = _page(e, symbol, tf, end, 1000)
                if not page:
                    break
                out.extend(page)
                end = page[0]["t"] - 1
            if not out:
                raise RuntimeError("لا توجد بيانات")
            d = {c["t"]: c for c in out}
            return [d[k] for k in sorted(d) if k >= start_ms], e
        except Exception as x:
            last = x
    raise RuntimeError("تعذّر جلب البيانات: %s" % last)


# ---------------------------------------------------------------- المنطق
def day_levels(daily):
    """{بداية اليوم: (قمة, قاع, 50%)} مأخوذة من شمعة اليوم السابق."""
    return {c["t"] + DAY: (c["h"], c["l"], (c["h"] + c["l"]) / 2) for c in daily if c["h"] > c["l"]}


def signal(cs, i, lv, cfg):
    """يفحص الشمعة المغلقة رقم i ويعيد إشارة أو None."""
    if i < 1:
        return None
    H, L, M = lv
    c, p = cs[i], cs[i - 1]
    if int(cfg.get("chop_on", 1)):
        seg = cs[max(0, i - int(cfg.get("chop_n", 24))):i + 1]
        x = sum(1 for a, b in zip(seg, seg[1:]) if (a["c"] - M) * (b["c"] - M) < 0)
        if x >= int(cfg.get("chop_x", 4)):
            return None
    buf = float(cfg.get("sl_buf", 0.05)) / 100
    e = c["c"]
    # بيع: سحب فوق القمة ثم إغلاق داخل المدى
    if (c["h"] > H and e < H) or (p["c"] >= H and e < H):
        top = max(c["h"], p["h"]) if p["h"] > H else c["h"]
        if e > M:
            return {"side": "SELL", "e": e, "sl": top * (1 + buf), "tp1": M, "tp2": L}
    # شراء: سحب تحت القاع ثم إغلاق داخل المدى
    if (c["l"] < L and e > L) or (p["c"] <= L and e > L):
        bot = min(c["l"], p["l"]) if p["l"] < L else c["l"]
        if e < M:
            return {"side": "BUY", "e": e, "sl": bot * (1 - buf), "tp1": M, "tp2": H}
    return None


def make_trade(sg, t):
    return {"side": sg["side"], "s": 1 if sg["side"] == "BUY" else -1, "e": sg["e"], "sl": sg["sl"],
            "sl0": sg["sl"], "tp1": sg["tp1"], "tp2": sg["tp2"], "stage": 0, "t": t}


def _pct(t, x):
    return t["s"] * (x - t["e"]) / t["e"] * 100


def _done(t, outcome, pnl):
    risk = abs(t["e"] - t["sl0"]) / t["e"] * 100 or 1
    return {"side": t["side"], "e": t["e"], "t0": t["t"], "outcome": outcome,
            "pnl": round(pnl, 3), "r": round(pnl / risk, 2)}


def advance(t, hi, lo, cfg):
    """يحرّك الصفقة بأعلى/أدنى سعر. نصف الكمية يُغلق عند TP1 والنصف الآخر عند TP2.
    الوقف يُفحص أولاً عند التلامس في نفس الشمعة (تقدير متحفظ). يعيد نتيجة عند الإغلاق."""
    s = t["s"]
    worst, best = (lo, hi) if s == 1 else (hi, lo)
    if s * (worst - t["sl"]) <= 0:
        if t["stage"] == 0:
            return _done(t, "SL", _pct(t, t["sl"]))
        return _done(t, "TP1_STOP", 0.5 * _pct(t, t["tp1"]) + 0.5 * _pct(t, t["sl"]))
    if t["stage"] == 0 and s * (best - t["tp1"]) >= 0:
        t["stage"] = 1
        if int(cfg.get("be_on", 1)):
            t["sl"] = t["e"]
    if t["stage"] == 1 and s * (best - t["tp2"]) >= 0:
        return _done(t, "TP2", 0.5 * _pct(t, t["tp1"]) + 0.5 * _pct(t, t["tp2"]))
    return None


def backtest(cs, daily, cfg):
    lvmap, res, pos, used = day_levels(daily), [], None, set()
    for i in range(1, len(cs)):
        c = cs[i]
        day = c["t"] - c["t"] % DAY
        if pos:   # الدخول عند إغلاق الشمعة، والإدارة تبدأ من التي بعدها
            r = advance(pos, c["h"], c["l"], cfg)
            if r:
                res.append(r)
                pos = None
            continue
        lv = lvmap.get(day)
        if not lv:
            continue
        sg = signal(cs, i, lv, cfg)
        if sg and not (int(cfg.get("once", 1)) and (day, sg["side"]) in used):
            used.add((day, sg["side"]))
            pos = make_trade(sg, c["t"])
    return res


def summarize(res):
    n = len(res)
    cnt = lambda k: sum(1 for r in res if r["outcome"] == k)
    tp2, stop1, sl = cnt("TP2"), cnt("TP1_STOP"), cnt("SL")
    return {"n": n, "tp1": tp2 + stop1, "tp2": tp2, "stop1": stop1, "sl": sl,
            "pnl": round(sum(r["pnl"] for r in res), 2), "r": round(sum(r["r"] for r in res), 2),
            "win": round(sum(1 for r in res if r["pnl"] > 0) / n * 100, 1) if n else None}
