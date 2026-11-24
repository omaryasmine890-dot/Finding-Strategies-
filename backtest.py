"""الباكتيست: نفس منطق البوت بالضبط. الدخول عند إغلاق شمعة الإشارة، والخروج عند TP1 أو SL.
إذا لمست الشمعة الـ SL والـ TP معاً تُحسب SL (افتراض متحفظ)."""
import datetime as _dt

from strategy import compute, DEFAULTS

WARMUP = 5


def candle_time(c):
    v = c.get("t")
    if isinstance(v, (int, float)) and v > 0:
        return v / 1000.0 if v > 1e12 else float(v)
    return None


def simulate(cs, cfg):
    """cs: شموع مغلقة. يرجع قائمة الصفقات: dict(side, entry, exit, pts, res, t_in, t_out, i_in, i_out)."""
    p = dict(DEFAULTS); p.update({k: v for k, v in cfg.items() if k in DEFAULTS})
    SL, TP = float(p["sl"]), float(p["tp"])
    sig = compute(cs, cfg)["sig"]
    trades, pos = [], None
    for i in range(WARMUP, len(cs)):
        c = cs[i]
        if pos:
            d = pos["d"]
            sl_hit = c["l"] <= pos["sl"] if d == 1 else c["h"] >= pos["sl"]
            tp_hit = c["h"] >= pos["tp"] if d == 1 else c["l"] <= pos["tp"]
            if sl_hit or tp_hit:
                res, pts = ("SL", -SL) if sl_hit else ("TP", TP)
                trades.append({"side": "BUY" if d == 1 else "SELL", "entry": pos["e"],
                               "exit": pos["sl"] if sl_hit else pos["tp"], "pts": pts, "res": res,
                               "t_in": candle_time(cs[pos["i"]]), "t_out": candle_time(c),
                               "i_in": pos["i"], "i_out": i})
                pos = None
            continue
        if sig[i]:
            d = 1 if sig[i] == "BUY" else -1
            e = c["c"]
            pos = {"d": d, "e": e, "sl": e - d * SL, "tp": e + d * TP, "i": i}
    return trades, sig


def _classify(first, last, hi, lo):
    rng = hi - lo
    eff = (last - first) / rng if rng > 0 else 0.0
    return ("up" if eff >= 0.3 else "down" if eff <= -0.3 else "range"), eff


def stats(trades, cs, cfg, cost):
    p = dict(DEFAULTS); p.update({k: v for k, v in cfg.items() if k in DEFAULTS})
    SL, TP = float(p["sl"]), float(p["tp"])
    n = len(trades)
    wins = sum(1 for t in trades if t["res"] == "TP")
    nets = [t["pts"] - cost for t in trades]
    net = sum(nets)
    # أكبر تراجع والسلاسل
    eq = peak = dd = 0.0
    for x in nets:
        eq += x; peak = max(peak, eq); dd = max(dd, peak - eq)
    ml = mw = cl = cw = 0
    for t in trades:
        if t["res"] == "SL":
            cl += 1; cw = 0
        else:
            cw += 1; cl = 0
        ml, mw = max(ml, cl), max(mw, cw)
    gp = sum(x for x in nets if x > 0)
    gl = -sum(x for x in nets if x < 0)
    loss, gain = SL + cost, TP - cost
    be = round(loss / (loss + gain) * 100, 1) if gain > 0 else None
    wr = round(wins / n * 100, 2) if n else 0
    # الشراء والبيع
    sides = {}
    for name, sd in (("buy", "BUY"), ("sell", "SELL")):
        rs = [t for t in trades if t["side"] == sd]
        w = sum(1 for t in rs if t["res"] == "TP")
        sides[name] = {"n": len(rs), "win": w, "loss": len(rs) - w,
                       "wr": round(w / len(rs) * 100, 1) if rs else 0,
                       "pts": round(sum(t["pts"] - cost for t in rs), 1)}
    # الاتجاه العام
    trend = None
    if len(cs) > 1:
        first, last = cs[0]["o"], cs[-1]["c"]
        hi, lo = max(c["h"] for c in cs), min(c["l"] for c in cs)
        kind, _ = _classify(first, last, hi, lo)
        trend = {"kind": kind, "change": round(last - first, 1),
                 "pct": round((last - first) / first * 100, 2) if first else 0,
                 "hi": round(hi, 2), "lo": round(lo, 2)}
    # حسب الأسبوع (يبدأ الاثنين)
    def monday(t):
        d = _dt.datetime.utcfromtimestamp(t).date()
        return d - _dt.timedelta(days=d.weekday())
    wk_px, weeks = {}, {}
    for c in cs:
        t = candle_time(c)
        if t is None:
            continue
        k = monday(t)
        w = wk_px.get(k)
        if w is None:
            wk_px[k] = {"o": c["o"], "c": c["c"], "h": c["h"], "l": c["l"]}
        else:
            w["c"] = c["c"]; w["h"] = max(w["h"], c["h"]); w["l"] = min(w["l"], c["l"])
    for t in trades:
        if t["t_in"] is None:
            continue
        w = weeks.setdefault(monday(t["t_in"]), {"n": 0, "sl": 0, "pts": 0.0})
        w["n"] += 1; w["sl"] += t["res"] == "SL"; w["pts"] += t["pts"] - cost
    weekly = []
    for k in sorted(weeks):
        w = wk_px.get(k)
        weekly.append({"week": k.strftime("%m-%d"), "n": weeks[k]["n"], "sl": weeks[k]["sl"],
                       "pts": round(weeks[k]["pts"], 1),
                       "trend": _classify(w["o"], w["c"], w["h"], w["l"])[0] if w else ""})
    return {"total_trades": n, "wins": wins, "losing_trades": n - wins, "win_rate": wr,
            "total_points": round(net, 1), "gross_points": round(sum(t["pts"] for t in trades), 1),
            "cost": cost, "cost_total": round(cost * n, 1), "avg_points": round(net / n, 2) if n else 0,
            "max_drawdown": round(dd, 1), "max_sl_streak": ml, "max_win_streak": mw,
            "profit_factor": round(gp / gl, 2) if gl > 0 else None,
            "breakeven_wr": be, "margin": round(wr - be, 1) if (be is not None and n) else None,
            "buy": sides["buy"], "sell": sides["sell"], "trend": trend, "weekly": weekly,
            "candles": len(cs)}
