"""البوت: يجلب شموع العملة الرقمية ويتداول ورقيًا حسب استراتيجية سحب السيولة."""
import json
import os
import threading
import time
from collections import deque

import strategy as st

CFG = dict(st.DEF)
SETTINGS_FILE = os.getenv("SETTINGS_FILE", "settings.json")
try:
    with open(SETTINGS_FILE, encoding="utf-8") as f:
        CFG.update(json.load(f))
except Exception:
    pass

FIELDS = {"exchange": str, "symbol": str, "tf": str, "sl_buf": float, "be_on": int, "once": int,
          "chop_on": int, "chop_n": int, "chop_x": int}

LOCK = threading.Lock()
STATE = {"status": "starting", "error": "", "price": None, "candles": [], "levels": None,
         "src": "", "updated": 0}
_trade = None
_closed = deque(maxlen=500)
_no = 0
_last_sig = None
_used = set()
_paused = False
_daily = {"key": None, "t": 0.0, "cs": []}


def step():
    global _trade, _no, _last_sig
    ex, sym, tf = CFG["exchange"], CFG["symbol"], CFG["tf"]
    cs, src = st.fetch_recent(ex, sym, tf, 200)
    now = time.time()
    if _daily["key"] != (src, sym) or now - _daily["t"] > 60:
        dc, _ = st.fetch_recent(src, sym, "D", 5)
        _daily.update(key=(src, sym), t=now, cs=dc)
    lvmap = st.day_levels(_daily["cs"])
    price = cs[-1]["c"]
    today = cs[-1]["t"] - cs[-1]["t"] % st.DAY
    lv = lvmap.get(today)
    with LOCK:
        if _trade:
            r = st.advance(_trade, price, price, CFG)
            if r:
                r["no"] = _trade["no"]
                _closed.append(r)
                _trade = None
        i = len(cs) - 2                      # آخر شمعة مغلقة
        if _last_sig is None:                # أول تشغيل: لا نفتح صفقة من إشارة قديمة
            _last_sig = cs[i]["t"]
        elif cs[i]["t"] != _last_sig:
            _last_sig = cs[i]["t"]
            day = cs[i]["t"] - cs[i]["t"] % st.DAY
            l2 = lvmap.get(day)
            if l2 and not _trade:
                sg = st.signal(cs, i, l2, CFG)
                if sg and not (int(CFG.get("once", 1)) and (day, sg["side"]) in _used):
                    _used.add((day, sg["side"]))
                    _no += 1
                    _trade = st.make_trade(sg, cs[i]["t"])
                    _trade["no"] = _no
        STATE.update(status="running", error="", price=price, candles=cs[-96:], src=src,
                     levels={"h": lv[0], "l": lv[1], "m": lv[2]} if lv else None,
                     updated=int(time.time()))


def loop():
    while True:
        try:
            if _paused:
                with LOCK:
                    STATE.update(status="paused")
            else:
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


def snapshot():
    with LOCK:
        d = dict(STATE)
        d["cfg"] = dict(CFG)
        d["trade"] = dict(_trade) if _trade else None
        d["log"] = list(_closed)[::-1][:30]
        d["stats"] = st.summarize(list(_closed))
        d["paused"] = _paused
        return d


def update_cfg(new):
    global _trade, _last_sig
    clean = {}
    for k, t in FIELDS.items():
        if k in new and str(new[k]).strip().lower() not in ("", "none", "null", "undefined", "nan"):
            try:
                v = t(new[k])
            except (ValueError, TypeError):
                raise ValueError(f"قيمة غير صالحة في الحقل: {k}")
            if t is str:
                v = v.strip().upper() if k == "symbol" else v.strip().lower()
            elif v < 0:
                raise ValueError(f"قيمة غير صحيحة: {k}")
            clean[k] = v
    if clean.get("exchange", CFG["exchange"]) not in ("bybit", "binance"):
        raise ValueError("المنصة غير مدعومة")
    if clean.get("tf", CFG["tf"]) not in st.TFM:
        raise ValueError("الفريم غير مدعوم")
    with LOCK:
        changed = any(k in clean and clean[k] != CFG.get(k) for k in ("exchange", "symbol", "tf"))
        CFG.update(clean)
        if changed:      # صفقة الرمز/الفريم القديم لا تُدار بأسعار جديدة
            _trade = None
            _last_sig = None
            _used.clear()
            _daily["key"] = None
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(CFG, f)
        except Exception:
            pass


def reset_stats():
    global _trade, _no
    with LOCK:
        _closed.clear()
        _trade = None
        _no = 0


def toggle_pause():
    global _paused
    _paused = not _paused
    return _paused
