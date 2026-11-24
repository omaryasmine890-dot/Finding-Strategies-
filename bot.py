"""البوت الحي: يقرأ الشموع من MT5 أو Binance، يحسب الإشارات، ويتداول ورقياً (الخروج عند TP1 أو SL)."""
import json
import os
import threading
import time

import binance_feed
from strategy import DEFAULTS, compute

try:                      # MT5 عبر الـ EA (نفس feed.py الحالي)
    import feed
except Exception:         # إذا لم يوجد feed.py يعمل البوت بـ Binance فقط
    feed = None

TF_MIN = {"1": 1, "3": 3, "5": 5, "15": 15, "30": 30, "60": 60, "240": 240, "D": 1440}

CFG = dict(DEFAULTS)
CFG.update({"source": os.getenv("SOURCE", "mt5"), "tf": os.getenv("TF", "3"),
            "mt5_symbol": os.getenv("MT5_SYMBOL", "XAUUSD247m"),
            "bn_symbol": os.getenv("BINANCE_SYMBOL", "XAUUSDT")})
SETTINGS_FILE = os.getenv("SETTINGS_FILE", "settings.json")
TRADES_FILE = os.getenv("TRADES_FILE", "trades.json")
try:
    with open(SETTINGS_FILE, encoding="utf-8") as f:
        CFG.update({k: v for k, v in json.load(f).items() if k in CFG})
except Exception:
    pass

# مفتاح الربط مع الـ EA (نفس السابق)
MT5 = {"key": os.getenv("MT5_KEY", "")}
try:
    with open(os.getenv("MT5_FILE", "mt5.json"), encoding="utf-8") as f:
        if not MT5["key"]:
            MT5["key"] = json.load(f).get("key", "")
except Exception:
    pass

FIELDS = {"source": str, "tf": str, "mt5_symbol": str, "bn_symbol": str,
          "vol_on": int, "vol_level": float, "vol_n": int,
          "imp_on": int, "fast": int, "slow": int, "ma_mode": str, "src": str, "entry": str,
          "mom_on": int, "rsi_n": int, "ob": float, "os": float, "sl": float, "tp": float}
CHOICES = {"source": ("mt5", "binance"), "tf": tuple(TF_MIN), "ma_mode": ("rma", "ema", "sma"),
           "src": ("close", "hl2", "hlc3", "ohlc4"), "entry": ("fast", "cross")}

LOCK = threading.Lock()
STATE = {"status": "starting", "error": "", "price": None, "candles": [], "fast": [], "slow": [],
         "rsi": [], "marks": []}
_trade, _closed, _no, _last_t, _paused = None, [], 0, None, False

try:
    with open(TRADES_FILE, encoding="utf-8") as f:
        _d = json.load(f)
    _closed, _no, _trade = _d.get("closed", [])[-500:], int(_d.get("no", 0)), _d.get("trade")
except Exception:
    pass


def _save(path, obj):
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        os.replace(tmp, path)
    except Exception:
        pass


def _save_trades():
    _save(TRADES_FILE, {"no": _no, "closed": _closed[-500:], "trade": _trade})


def symbol():
    return CFG["mt5_symbol"] if CFG["source"] == "mt5" else CFG["bn_symbol"]


def fetch_live(limit=400):
    """آخر الشموع، وآخر واحدة هي الجارية."""
    m = TF_MIN[CFG["tf"]]
    if CFG["source"] == "binance":
        return binance_feed.recent(CFG["bn_symbol"], m, limit)
    if feed is None:
        raise RuntimeError("feed.py غير موجود: اختر Binance")
    return feed.fetch_recent(CFG["mt5_symbol"], CFG["tf"], limit, feed.EXCHANGE)


def fetch_history(tf, days):
    m = TF_MIN[tf]
    if CFG["source"] == "binance":
        return binance_feed.history(CFG["bn_symbol"], m, days)
    if feed is None:
        raise RuntimeError("feed.py غير موجود: اختر Binance")
    if not feed.mt5_info()["connected"]:
        raise RuntimeError("الـ EA غير متصل بـ MT5، شغّله أولاً")
    return feed.history(CFG["mt5_symbol"], m, days)


def _close(res, px, pts):
    global _trade
    t = dict(_trade, exit=px, res=res, pts=pts, t_out=int(time.time()))
    _closed.append(t)
    _trade = None
    _save_trades()


def step():
    global _trade, _no, _last_t
    cs = fetch_live()
    if len(cs) < 30:
        raise RuntimeError("بيانات غير كافية")
    price = cs[-1]["c"]
    closed = cs[:-1]
    a = compute(closed, CFG)
    with LOCK:
        # إدارة الصفقة بالسعر الحالي (SL أولاً)
        if _trade:
            d = _trade["d"]
            if (price - _trade["sl"]) * d <= 0:
                _close("SL", _trade["sl"], -_trade["slv"])
            elif (price - _trade["tp"]) * d >= 0:
                _close("TP", _trade["tp"], _trade["tpv"])
        # إشارة جديدة عند إغلاق شمعة جديدة
        t_last = closed[-1]["t"]
        if t_last != _last_t:
            first = _last_t is None
            _last_t = t_last
            s = a["sig"][-1]
            if s and not _trade and not first and not _paused:
                d = 1 if s == "BUY" else -1
                _no += 1
                _trade = {"no": _no, "side": s, "d": d, "entry": price,
                          "sl": price - d * float(CFG["sl"]), "tp": price + d * float(CFG["tp"]),
                          "slv": float(CFG["sl"]), "tpv": float(CFG["tp"]), "t_in": int(time.time()),
                          "src": CFG["source"], "tf": CFG["tf"]}
                _save_trades()
        k = 120
        sub = closed[-(k - 1):] + [cs[-1]]
        off = len(closed) - (k - 1)
        marks = [{"i": j - off, "side": a["sig"][j]} for j in range(max(0, off), len(closed)) if a["sig"][j]]
        STATE.update(status="paused" if _paused else "running", error="", price=price, candles=sub,
                     fast=a["fast"][-(k - 1):], slow=a["slow"][-(k - 1):], rsi=a["rsi"][-(k - 1):],
                     marks=marks, updated=int(time.time()))


def loop():
    while True:
        try:
            step()
        except Exception as e:
            with LOCK:
                STATE.update(status="error", error=str(e))
        time.sleep(5)


_started = False


def start():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=loop, daemon=True).start()


def _stats():
    n = len(_closed)
    w = sum(1 for t in _closed if t["res"] == "TP")
    return {"n": n, "win": w, "loss": n - w, "wr": round(w / n * 100, 1) if n else None,
            "pts": round(sum(t["pts"] for t in _closed), 1)}


def snapshot():
    with LOCK:
        d = dict(STATE)
        d["cfg"] = dict(CFG)
        d["symbol"] = symbol()
        d["trade"] = dict(_trade) if _trade else None
        d["log"] = _closed[::-1][:30]
        d["stats"] = _stats()
        d["paused"] = _paused
        d["mt5"] = feed.mt5_info() if feed else {"connected": False}
        return d


def update_cfg(new):
    global _trade, _last_t
    clean = {}
    for k, t in FIELDS.items():
        if k in new and str(new[k]).strip() != "":
            try:
                v = t(new[k])
            except (TypeError, ValueError):
                raise ValueError("قيمة غير صالحة: %s" % k)
            if t is str:
                v = v.strip()
                if k == "tf":
                    v = v.upper() if v.lower() == "d" else v
                elif k not in ("mt5_symbol", "bn_symbol"):
                    v = v.lower()
                else:
                    v = v.upper() if k == "bn_symbol" else v
            elif v < 0:
                raise ValueError("قيمة سالبة: %s" % k)
            if k in CHOICES and v not in CHOICES[k]:
                raise ValueError("قيمة غير مدعومة: %s" % k)
            clean[k] = v
    if clean.get("fast", CFG["fast"]) >= clean.get("slow", CFG["slow"]):
        raise ValueError("المتوسط السريع يجب أن يكون أصغر من البطيء")
    if clean.get("sl", 1) <= 0 or clean.get("tp", 1) <= 0:
        raise ValueError("SL و TP يجب أن يكونا أكبر من 0")
    with LOCK:
        changed = any(k in clean and clean[k] != CFG.get(k) for k in ("source", "tf", "mt5_symbol", "bn_symbol"))
        CFG.update(clean)
        if changed:          # صفقة بأسعار مصدر/فريم آخر لا تُدار
            _trade = None
            _last_t = None
            _save_trades()
        _save(SETTINGS_FILE, CFG)


def reset_stats():
    global _trade, _no
    with LOCK:
        _closed.clear()
        _trade, _no = None, 0
        _save_trades()


def toggle_pause():
    global _paused
    _paused = not _paused
    return _paused


def mt5_sync():
    """ما يقرؤه الـ EA الحالي: الرمز والفريم وطلبات التاريخ. التداول الآلي معطّل في هذا البوت."""
    with LOCK:
        d = {"trade_on": 0, "symbol": CFG["mt5_symbol"], "tf": TF_MIN[CFG["tf"]], "lot": 0.01,
             "sig_id": 0, "side": "", "sl": 0.0, "tp": 0.0, "age": 0, "trail": 0, "buf": 0, "n_tp": 1,
             "tp1": float(CFG["tp"])}
        for k in range(2, 11):
            d["tp%d" % k] = float(CFG["tp"])
    h = feed.pending_hist() if feed else None
    d.update(hist_sym=h["sym"] if h else "", hist_tf=h["tf"] if h else 0, hist_days=h["days"] if h else 0)
    return d
