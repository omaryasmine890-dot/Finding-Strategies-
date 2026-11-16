import os
import time

from flask import Flask, jsonify, request, send_from_directory

import bot
import strategy as st

app = Flask(__name__, static_folder="static")
bot.start()

MAX_CANDLES = 15000  # حد أقصى لعدد الشموع في الاختبار الواحد (لتفادي انتهاء المهلة)


def authorized(data):
    pw = os.getenv("ADMIN_PASSWORD")
    return (not pw) or data.get("password") == pw


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/state")
def state():
    return jsonify(bot.snapshot())


@app.route("/api/config", methods=["POST"])
def config():
    data = request.get_json(silent=True) or {}
    if not authorized(data):
        return jsonify(error="كلمة المرور غير صحيحة"), 403
    try:
        bot.update_cfg(data.get("cfg", {}))
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


@app.route("/health")
def health():
    return "ok"


@app.route("/api/backtest", methods=["POST"])
def backtest():
    try:
        data = request.get_json(silent=True) or {}
        cfg = dict(bot.snapshot()["cfg"])
        tf = str(data.get("interval") or cfg["tf"])
        if tf not in st.TFM:
            return jsonify(error="فريم غير مدعوم: %s" % tf, total_trades=0, win_rate=0), 200
        days = int(data.get("days") or 30)
        days = max(1, min(days, MAX_CANDLES * st.TFM[tf] // 1440))
        start = int(time.time() * 1000) - days * st.DAY
        cs, src = st.fetch_range(cfg["exchange"], cfg["symbol"], tf, start)
        if len(cs) < 100:
            return jsonify(error="بيانات غير كافية", total_trades=0, win_rate=0), 200
        daily, _ = st.fetch_range(src, cfg["symbol"], "D", start - 3 * st.DAY)
        s = st.summarize(st.backtest(cs, daily, cfg))
        return jsonify(total_trades=s["n"], tp1_hits=s["tp1"], tp2_wins=s["tp2"], tp1_stop=s["stop1"],
                       sl_losses=s["sl"], win_rate=s["win"] or 0, total_pct=s["pnl"], total_r=s["r"],
                       src=src, days_used=days, candles=len(cs))
    except Exception as e:
        return jsonify(error=str(e), total_trades=0, win_rate=0), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
