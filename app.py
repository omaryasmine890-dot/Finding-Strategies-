import os
from datetime import datetime

import numpy as np
from flask import Flask, render_template_string, request

import strategy_miner as sm

app = Flask(__name__)

MAX_CANDLES = 50000  # حماية من الطلبات الضخمة

PAGE = """<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Strategy Miner</title>
<style>
  body{font-family:system-ui,sans-serif;background:#0f1419;color:#e6e6e6;margin:0;padding:14px}
  h1{font-size:20px;margin:0 0 12px}
  h2{font-size:16px;margin:18px 0 8px}
  form{background:#1a212b;padding:12px;border-radius:10px}
  label{display:block;font-size:13px;margin:8px 0 3px;color:#9fb0c3}
  input,select{width:100%;box-sizing:border-box;padding:9px;border-radius:7px;border:1px solid #2d3a4a;background:#0f1419;color:#fff;font-size:15px}
  .row{display:grid;grid-template-columns:1fr 1fr;gap:8px}
  button{margin-top:14px;width:100%;padding:12px;border:0;border-radius:8px;background:#2f9e44;color:#fff;font-size:16px}
  .err{background:#5c1a1a;padding:10px;border-radius:8px;margin-top:12px}
  .info{color:#9fb0c3;font-size:13px;margin-top:10px}
  .wrap{overflow-x:auto}
  table{border-collapse:collapse;width:100%;font-size:13px;margin-top:6px}
  th,td{padding:6px 8px;border-bottom:1px solid #2d3a4a;text-align:right;white-space:nowrap}
  td.rule{white-space:normal;min-width:180px}
  .good{color:#51cf66}.bad{color:#ff6b6b}
</style>
</head>
<body>
<h1>Strategy Miner</h1>
<form method="post">
  <div class="row">
    <div><label>الزوج</label><input name="symbol" value="{{ f.symbol }}"></div>
    <div><label>الفريم</label>
      <select name="interval">
        {% for i in intervals %}<option value="{{ i }}" {{ 'selected' if i==f.interval }}>{{ i }}</option>{% endfor %}
      </select></div>
  </div>
  <div class="row">
    <div><label>عدد الأيام</label><input name="days" type="number" value="{{ f.days }}"></div>
    <div><label>نسبة الحركة %</label><input name="pct" type="number" step="0.1" value="{{ f.pct }}"></div>
  </div>
  <div class="row">
    <div><label>خلال كم شمعة</label><input name="candles" type="number" value="{{ f.candles }}"></div>
    <div><label>أقصى عدد شروط (1-3)</label><input name="combo" type="number" min="1" max="3" value="{{ f.combo }}"></div>
  </div>
  <div class="row">
    <div><label>من تاريخ (اختياري)</label><input name="start" type="date" value="{{ f.start }}"></div>
    <div><label>إلى تاريخ (اختياري)</label><input name="end" type="date" value="{{ f.end }}"></div>
  </div>
  <div class="row">
    <div><label>أقل عدد حالات</label><input name="min_samples" type="number" value="{{ f.min_samples }}"></div>
    <div><label>أقل Lift</label><input name="min_lift" type="number" step="0.05" value="{{ f.min_lift }}"></div>
  </div>
  <div class="row">
    <div><label>Lookback (شموع)</label><input name="lookback" type="number" min="1" value="{{ f.lookback }}"></div>
    <div><label>نسبة الاستخراج</label><input name="train" type="number" step="0.05" min="0.4" max="0.9" value="{{ f.train }}"></div>
  </div>
  <button type="submit">ابدأ التحليل</button>
</form>

{% if error %}<div class="err">{{ error }}</div>{% endif %}

{% if res %}
  <div class="info">
    {{ res.candles }} شمعة | أحداث صعود: {{ res.ups }} | أحداث هبوط: {{ res.dns }}<br>
    الاحتمال العام: صعود {{ res.bu }}% | هبوط {{ res.bd }}%
  </div>
  {% for title, rows in [('أفضل قواعد الشراء', res.buy), ('أفضل قواعد البيع', res.sell)] %}
    <h2>{{ title }}</h2>
    {% if rows %}
    <div class="wrap"><table>
      <tr><th>القاعدة</th><th>حالات</th><th>%</th><th>Lift</th><th>اختبار: حالات</th><th>اختبار %</th><th>اختبار Lift</th></tr>
      {% for r in rows %}
      <tr>
        <td class="rule">{{ r.rule }}</td><td>{{ r.n }}</td><td>{{ r.p }}</td><td>{{ r.lift }}</td>
        <td>{{ r.tn }}</td><td>{{ r.tp }}</td>
        <td class="{{ 'good' if r.tlift_val is not none and r.tlift_val >= 1.1 else 'bad' }}">{{ r.tlift }}</td>
      </tr>
      {% endfor %}
    </table></div>
    {% else %}<div class="info">لا توجد قواعد تحقق الحد الأدنى.</div>{% endif %}
  {% endfor %}
  <div class="info">القاعدة الموثوقة هي التي يبقى Lift الاختبار فيها (الأخضر) فوق 1 وقريباً من Lift الاستخراج.</div>
{% endif %}
</body></html>
"""


def defaults():
    c = sm.CONFIG
    return {"symbol": c["SYMBOL"], "interval": c["INTERVAL"], "days": c["DAYS"],
            "pct": c["EVENT_PCT"], "candles": c["EVENT_CANDLES"], "combo": c["MAX_COMBO"],
            "start": "", "end": "", "min_samples": c["MIN_SAMPLES"], "min_lift": c["MIN_LIFT"],
            "lookback": c["LOOKBACK"], "train": c["TRAIN_RATIO"]}


def fmt_pct(x):
    return "-" if x is None or x != x else f"{x * 100:.0f}%"


def fmt_num(x):
    return "-" if x is None or x != x else f"{x:.2f}"


def to_rows(df, top):
    rows = []
    for _, r in df.head(top).iterrows():
        tl = r.get("test_Lift")
        rows.append({
            "rule": r["القاعدة"], "n": int(r["الحالات"]), "p": fmt_pct(r["النسبة"]),
            "lift": fmt_num(r["Lift"]),
            "tn": int(r["test_حالات"]), "tp": fmt_pct(r["test_نسبة"]),
            "tlift": fmt_num(tl), "tlift_val": None if tl != tl else float(tl),
        })
    return rows


def run(form):
    cfg = dict(sm.CONFIG)
    cfg["SYMBOL"] = form["symbol"].strip().upper()
    cfg["INTERVAL"] = form["interval"]
    cfg["DAYS"] = int(form["days"])
    cfg["EVENT_PCT"] = float(form["pct"])
    cfg["EVENT_CANDLES"] = int(form["candles"])
    cfg["MAX_COMBO"] = min(3, max(1, int(form["combo"])))
    cfg["MIN_SAMPLES"] = int(form["min_samples"])
    cfg["MIN_LIFT"] = float(form["min_lift"])
    cfg["LOOKBACK"] = max(1, int(form["lookback"]))
    cfg["TRAIN_RATIO"] = min(0.9, max(0.4, float(form["train"])))
    cfg["START"] = form["start"] or None
    cfg["END"] = form["end"] or None
    cfg["CSV"] = None

    if cfg["INTERVAL"] not in sm.INTERVAL_MS:
        raise ValueError("فريم غير مدعوم")
    # تقدير عدد الشموع قبل التحميل
    if cfg["START"]:
        s = datetime.fromisoformat(cfg["START"])
        e = datetime.fromisoformat(cfg["END"]) if cfg["END"] else datetime.utcnow()
        span_ms = (e - s).total_seconds() * 1000
    else:
        span_ms = cfg["DAYS"] * 86_400_000
    if span_ms / sm.INTERVAL_MS[cfg["INTERVAL"]] > MAX_CANDLES:
        raise ValueError(f"الفترة كبيرة (أكثر من {MAX_CANDLES} شمعة). قلّل الأيام أو كبّر الفريم.")

    df = sm.load_data(cfg)
    if len(df) < 300:
        raise ValueError("بيانات قليلة جداً (أقل من 300 شمعة). وسّع الفترة.")

    labels = sm.label_events(df, cfg["EVENT_PCT"], cfg["EVENT_CANDLES"])
    conds = sm.build_conditions(df, cfg)
    split = int(len(df) * cfg["TRAIN_RATIO"])
    train = np.zeros(len(df), bool)
    train[:split] = True
    test = ~train

    rules, bu, bd = sm.mine(conds, labels, train, cfg)
    res = {"candles": len(df), "ups": int((labels == 1).sum()), "dns": int((labels == -1).sum()),
           "bu": f"{bu * 100:.1f}", "bd": f"{bd * 100:.1f}", "buy": [], "sell": []}
    if not rules.empty:
        rules = sm.validate(rules.sort_values("z", ascending=False), conds, labels, test, cfg)
        res["buy"] = to_rows(rules[rules["الاتجاه"] == "شراء"], 10)
        res["sell"] = to_rows(rules[rules["الاتجاه"] == "بيع"], 10)
    return res


@app.route("/", methods=["GET", "POST"])
def index():
    f, res, error = defaults(), None, None
    if request.method == "POST":
        f.update({k: request.form.get(k, v) for k, v in f.items()})
        try:
            res = run(request.form)
        except SystemExit as e:  # sm.load_data يستخدم sys.exit عند الأخطاء
            error = str(e)
        except Exception as e:
            error = f"خطأ: {e}"
    return render_template_string(PAGE, f=f, res=res, error=error,
                                  intervals=list(sm.INTERVAL_MS))


@app.route("/health")
def health():
    return "ok"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))import os
from datetime import datetime

import numpy as np
from flask import Flask, render_template_string, request

import strategy_miner as sm

app = Flask(__name__)

MAX_CANDLES = 50000  # حماية من الطلبات الضخمة

PAGE = """<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Strategy Miner</title>
<style>
  body{font-family:system-ui,sans-serif;background:#0f1419;color:#e6e6e6;margin:0;padding:14px}
  h1{font-size:20px;margin:0 0 12px}
  h2{font-size:16px;margin:18px 0 8px}
  form{background:#1a212b;padding:12px;border-radius:10px}
  label{display:block;font-size:13px;margin:8px 0 3px;color:#9fb0c3}
  input,select{width:100%;box-sizing:border-box;padding:9px;border-radius:7px;border:1px solid #2d3a4a;background:#0f1419;color:#fff;font-size:15px}
  .row{display:grid;grid-template-columns:1fr 1fr;gap:8px}
  button{margin-top:14px;width:100%;padding:12px;border:0;border-radius:8px;background:#2f9e44;color:#fff;font-size:16px}
  .err{background:#5c1a1a;padding:10px;border-radius:8px;margin-top:12px}
  .info{color:#9fb0c3;font-size:13px;margin-top:10px}
  .wrap{overflow-x:auto}
  table{border-collapse:collapse;width:100%;font-size:13px;margin-top:6px}
  th,td{padding:6px 8px;border-bottom:1px solid #2d3a4a;text-align:right;white-space:nowrap}
  td.rule{white-space:normal;min-width:180px}
  .good{color:#51cf66}.bad{color:#ff6b6b}
</style>
</head>
<body>
<h1>Strategy Miner</h1>
<form method="post">
  <div class="row">
    <div><label>الزوج</label><input name="symbol" value="{{ f.symbol }}"></div>
    <div><label>الفريم</label>
      <select name="interval">
        {% for i in intervals %}<option value="{{ i }}" {{ 'selected' if i==f.interval }}>{{ i }}</option>{% endfor %}
      </select></div>
  </div>
  <div class="row">
    <div><label>عدد الأيام</label><input name="days" type="number" value="{{ f.days }}"></div>
    <div><label>نسبة الحركة %</label><input name="pct" type="number" step="0.1" value="{{ f.pct }}"></div>
  </div>
  <div class="row">
    <div><label>خلال كم شمعة</label><input name="candles" type="number" value="{{ f.candles }}"></div>
    <div><label>أقصى عدد شروط (1-3)</label><input name="combo" type="number" min="1" max="3" value="{{ f.combo }}"></div>
  </div>
  <div class="row">
    <div><label>من تاريخ (اختياري)</label><input name="start" type="date" value="{{ f.start }}"></div>
    <div><label>إلى تاريخ (اختياري)</label><input name="end" type="date" value="{{ f.end }}"></div>
  </div>
  <div class="row">
    <div><label>أقل عدد حالات</label><input name="min_samples" type="number" value="{{ f.min_samples }}"></div>
    <div><label>أقل Lift</label><input name="min_lift" type="number" step="0.05" value="{{ f.min_lift }}"></div>
  </div>
  <div class="row">
    <div><label>Lookback (شموع)</label><input name="lookback" type="number" min="1" value="{{ f.lookback }}"></div>
    <div><label>نسبة الاستخراج</label><input name="train" type="number" step="0.05" min="0.4" max="0.9" value="{{ f.train }}"></div>
  </div>
  <button type="submit">ابدأ التحليل</button>
</form>

{% if error %}<div class="err">{{ error }}</div>{% endif %}

{% if res %}
  <div class="info">
    {{ res.candles }} شمعة | أحداث صعود: {{ res.ups }} | أحداث هبوط: {{ res.dns }}<br>
    الاحتمال العام: صعود {{ res.bu }}% | هبوط {{ res.bd }}%
  </div>
  {% for title, rows in [('أفضل قواعد الشراء', res.buy), ('أفضل قواعد البيع', res.sell)] %}
    <h2>{{ title }}</h2>
    {% if rows %}
    <div class="wrap"><table>
      <tr><th>القاعدة</th><th>حالات</th><th>%</th><th>Lift</th><th>اختبار: حالات</th><th>اختبار %</th><th>اختبار Lift</th></tr>
      {% for r in rows %}
      <tr>
        <td class="rule">{{ r.rule }}</td><td>{{ r.n }}</td><td>{{ r.p }}</td><td>{{ r.lift }}</td>
        <td>{{ r.tn }}</td><td>{{ r.tp }}</td>
        <td class="{{ 'good' if r.tlift_val is not none and r.tlift_val >= 1.1 else 'bad' }}">{{ r.tlift }}</td>
      </tr>
      {% endfor %}
    </table></div>
    {% else %}<div class="info">لا توجد قواعد تحقق الحد الأدنى.</div>{% endif %}
  {% endfor %}
  <div class="info">القاعدة الموثوقة هي التي يبقى Lift الاختبار فيها (الأخضر) فوق 1 وقريباً من Lift الاستخراج.</div>
{% endif %}
</body></html>
"""


def defaults():
    c = sm.CONFIG
    return {"symbol": c["SYMBOL"], "interval": c["INTERVAL"], "days": c["DAYS"],
            "pct": c["EVENT_PCT"], "candles": c["EVENT_CANDLES"], "combo": c["MAX_COMBO"],
            "start": "", "end": "", "min_samples": c["MIN_SAMPLES"], "min_lift": c["MIN_LIFT"],
            "lookback": c["LOOKBACK"], "train": c["TRAIN_RATIO"]}


def fmt_pct(x):
    return "-" if x is None or x != x else f"{x * 100:.0f}%"


def fmt_num(x):
    return "-" if x is None or x != x else f"{x:.2f}"


def to_rows(df, top):
    rows = []
    for _, r in df.head(top).iterrows():
        tl = r.get("test_Lift")
        rows.append({
            "rule": r["القاعدة"], "n": int(r["الحالات"]), "p": fmt_pct(r["النسبة"]),
            "lift": fmt_num(r["Lift"]),
            "tn": int(r["test_حالات"]), "tp": fmt_pct(r["test_نسبة"]),
            "tlift": fmt_num(tl), "tlift_val": None if tl != tl else float(tl),
        })
    return rows


def run(form):
    cfg = dict(sm.CONFIG)
    cfg["SYMBOL"] = form["symbol"].strip().upper()
    cfg["INTERVAL"] = form["interval"]
    cfg["DAYS"] = int(form["days"])
    cfg["EVENT_PCT"] = float(form["pct"])
    cfg["EVENT_CANDLES"] = int(form["candles"])
    cfg["MAX_COMBO"] = min(3, max(1, int(form["combo"])))
    cfg["MIN_SAMPLES"] = int(form["min_samples"])
    cfg["MIN_LIFT"] = float(form["min_lift"])
    cfg["LOOKBACK"] = max(1, int(form["lookback"]))
    cfg["TRAIN_RATIO"] = min(0.9, max(0.4, float(form["train"])))
    cfg["START"] = form["start"] or None
    cfg["END"] = form["end"] or None
    cfg["CSV"] = None

    if cfg["INTERVAL"] not in sm.INTERVAL_MS:
        raise ValueError("فريم غير مدعوم")
    # تقدير عدد الشموع قبل التحميل
    if cfg["START"]:
        s = datetime.fromisoformat(cfg["START"])
        e = datetime.fromisoformat(cfg["END"]) if cfg["END"] else datetime.utcnow()
        span_ms = (e - s).total_seconds() * 1000
    else:
        span_ms = cfg["DAYS"] * 86_400_000
    if span_ms / sm.INTERVAL_MS[cfg["INTERVAL"]] > MAX_CANDLES:
        raise ValueError(f"الفترة كبيرة (أكثر من {MAX_CANDLES} شمعة). قلّل الأيام أو كبّر الفريم.")

    df = sm.load_data(cfg)
    if len(df) < 300:
        raise ValueError("بيانات قليلة جداً (أقل من 300 شمعة). وسّع الفترة.")

    labels = sm.label_events(df, cfg["EVENT_PCT"], cfg["EVENT_CANDLES"])
    conds = sm.build_conditions(df, cfg)
    split = int(len(df) * cfg["TRAIN_RATIO"])
    train = np.zeros(len(df), bool)
    train[:split] = True
    test = ~train

    rules, bu, bd = sm.mine(conds, labels, train, cfg)
    res = {"candles": len(df), "ups": int((labels == 1).sum()), "dns": int((labels == -1).sum()),
           "bu": f"{bu * 100:.1f}", "bd": f"{bd * 100:.1f}", "buy": [], "sell": []}
    if not rules.empty:
        rules = sm.validate(rules.sort_values("z", ascending=False), conds, labels, test, cfg)
        res["buy"] = to_rows(rules[rules["الاتجاه"] == "شراء"], 10)
        res["sell"] = to_rows(rules[rules["الاتجاه"] == "بيع"], 10)
    return res


@app.route("/", methods=["GET", "POST"])
def index():
    f, res, error = defaults(), None, None
    if request.method == "POST":
        f.update({k: request.form.get(k, v) for k, v in f.items()})
        try:
            res = run(request.form)
        except SystemExit as e:  # sm.load_data يستخدم sys.exit عند الأخطاء
            error = str(e)
        except Exception as e:
            error = f"خطأ: {e}"
    return render_template_string(PAGE, f=f, res=res, error=error,
                                  intervals=list(sm.INTERVAL_MS))


@app.route("/health")
def health():
    return "ok"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
