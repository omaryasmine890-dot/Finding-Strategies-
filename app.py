import hmac
import json
import os

from flask import Flask, Response, jsonify, request, send_from_directory

import backtest as bt
import bot

app = Flask(__name__, static_folder="static")
bot.start()

MAX_CANDLES = int(os.getenv("MAX_CANDLES", "30000"))   # حد أقصى لعدد الشموع في اختبار واحد
BT_COST = float(os.getenv("BT_COST", "0.3"))


def authorized(data):
    pw = os.getenv("ADMIN_PASSWORD")
    return (not pw) or data.get("password") == pw


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/health")
def health():
    return "ok"


@app.route("/api/state")
def state():
    return jsonify(bot.snapshot())


@app.route("/api/config", methods=["POST"])
def config():
    data = request.get_json(silent=True) or {}
    if not authorized(data):
        return jsonify(error="كلمة المرور غير صحيحة"), 403
    try:
        bot.update_cfg({k: v for k, v in data.items() if k != "password"})
    except (ValueError, TypeError) as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True)


@app.route("/api/reset", methods=["POST"])
def reset():
    if not authorized(request.get_json(silent=True) or {}):
        return jsonify(error="كلمة المرور غير صحيحة"), 403
    bot.reset_stats()
    return jsonify(ok=True)


@app.route("/api/pause", methods=["POST"])
def pause():
    if not authorized(request.get_json(silent=True) or {}):
        return jsonify(error="كلمة المرور غير صحيحة"), 403
    return jsonify(ok=True, paused=bot.toggle_pause())


@app.route("/api/backtest", methods=["POST"])
def backtest():
    fail = lambda m: (jsonify(error=m, total_trades=0), 200)
    try:
        data = request.get_json(silent=True) or {}
        tf = str(data.get("interval") or bot.CFG["tf"]).strip()
        tf = "D" if tf.lower() == "d" else tf
        if tf not in bot.TF_MIN:
            return fail("فريم غير مدعوم: %s" % tf)
        try:
            cost = float(data["cost"]) if str(data.get("cost", "")).strip() else BT_COST
        except (TypeError, ValueError):
            return fail("قيمة السبريد غير صحيحة")
        cost = max(0.0, cost)
        days = max(1, int(data.get("days") or 30))
        days = min(days, max(1, MAX_CANDLES * bot.TF_MIN[tf] // 1440))
        try:
            cs = bot.fetch_history(tf, days)
        except Exception as e:      # يشمل feed.Pending (التاريخ قيد التحميل من الـ EA)
            return fail(str(e))
        cs = cs[:-1]                # آخر شمعة غير مغلقة
        if len(cs) < 150:
            return fail("بيانات غير كافية (%d شمعة)" % len(cs))
        cfg = dict(bot.CFG)
        trades, _ = bt.simulate(cs, cfg)
        out = bt.stats(trades, cs, cfg, cost)
        out.update(timeframe=tf, days_used=days, source=bot.CFG["source"], symbol=bot.symbol())
        return jsonify(out)
    except Exception as e:
        return fail(str(e))


# ---------------------------------------------------------------------
# الربط مع MetaTrader 5 (نفس نقاط الـ EA الحالي: الدفع والمزامنة)
# ---------------------------------------------------------------------
def mt5_authorized():
    key = bot.MT5["key"]
    given = str(request.args.get("key", ""))
    return bool(key) and hmac.compare_digest(given.encode(), key.encode())


@app.route("/api/mt5/push", methods=["POST"])
def mt5_push():
    if bot.feed is None:
        return jsonify(error="feed.py غير موجود"), 500
    if not mt5_authorized():
        return jsonify(error="مفتاح MT5 غير صحيح أو غير مضبوط"), 403
    d = request.get_json(silent=True, force=True) or {}
    try:
        bot.feed.push(d["symbol"], d["tf"], d.get("bars", []), d.get("bid", 0), d.get("ask", 0),
                      d.get("mode", "live"), d.get("days", 0), bool(d.get("last", 0)))
    except (KeyError, ValueError, TypeError) as e:
        return jsonify(error="بيانات غير صالحة: %s" % e), 400
    return jsonify(ok=True)


@app.route("/api/mt5/sync")
def mt5_sync():
    if not mt5_authorized():
        return jsonify(error="مفتاح MT5 غير صحيح أو غير مضبوط"), 403
    return Response(json.dumps(bot.mt5_sync(), separators=(",", ":")), mimetype="application/json")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
