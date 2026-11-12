import os
from datetime import datetime

import numpy as np
import pandas as pd
from flask import Flask, render_template_string, request

import strategy_miner as sm

app = Flask(__name__)

MAX_CANDLES = 50000   # حماية من الطلبات الضخمة
CHART_CANDLES = 3000  # عدد الشموع المعروضة في الرسم
FOLDS = 3             # عدد الفترات الزمنية لاختبار الثبات
DEFAULT_DAYS = 90

PAGE = """<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0b0f14">
<title>Strategy Miner</title>
<script src="https://cdn.jsdelivr.net/npm/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<style>
  :root{--bg:#0b0f14;--card:#141b24;--line:#223041;--txt:#e8eef5;--mut:#8fa1b5;
        --green:#2ecc71;--red:#ff5c5c;--blue:#4c9aff;--amber:#f5b942}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--txt);font-family:system-ui,-apple-system,"Segoe UI",Tahoma,sans-serif;
       padding:14px 14px 40px;max-width:900px;margin-inline:auto}
  header{display:flex;align-items:center;gap:10px;margin-bottom:14px}
  header .logo{width:38px;height:38px;border-radius:10px;background:linear-gradient(135deg,var(--green),var(--blue));
       display:grid;place-items:center;font-weight:800;color:#06210f}
  header h1{font-size:19px;margin:0}
  header small{color:var(--mut);display:block;font-size:12px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;margin-bottom:14px}
  details>summary{cursor:pointer;font-weight:700;list-style:none;display:flex;justify-content:space-between;align-items:center}
  details>summary::after{content:"▾";color:var(--mut)}
  details[open]>summary::after{content:"▴"}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px}
  .grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-top:10px}
  label{display:block;font-size:12px;color:var(--mut);margin-bottom:4px}
  input,select{width:100%;padding:11px;border-radius:9px;border:1px solid var(--line);background:#0e141b;color:var(--txt);font-size:15px}
  input:focus,select:focus{outline:2px solid var(--blue);border-color:transparent}
  .chips{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}
  .chip{padding:6px 11px;border-radius:99px;border:1px solid var(--line);background:#0e141b;color:var(--mut);font-size:13px;cursor:pointer}
  .chip:active{background:var(--line)}
  .go{margin-top:14px;width:100%;padding:14px;border:0;border-radius:11px;font-size:16px;font-weight:700;
      background:linear-gradient(135deg,var(--green),#27ae60);color:#05230f;cursor:pointer}
  .err{background:#3b1518;border:1px solid #6b2328;color:#ffb3b3;padding:12px;border-radius:11px;margin-bottom:14px}
  .stats{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
  .stat{background:#0e141b;border:1px solid var(--line);border-radius:11px;padding:10px;text-align:center}
  .stat b{display:block;font-size:17px}
  .stat span{font-size:11px;color:var(--mut)}
  .up{color:var(--green)}.dn{color:var(--red)}.am{color:var(--amber)}
  #chart{height:340px;width:100%;direction:ltr}
  .legend{display:flex;gap:14px;font-size:12px;color:var(--mut);margin-top:8px;flex-wrap:wrap}
  .tabs{display:flex;gap:8px;margin-bottom:10px}
  .tab{flex:1;padding:11px;border-radius:10px;border:1px solid var(--line);background:#0e141b;color:var(--mut);
       font-size:15px;font-weight:700;cursor:pointer}
  .tab.active.buy{background:rgba(46,204,113,.14);color:var(--green);border-color:var(--green)}
  .tab.active.sell{background:rgba(255,92,92,.14);color:var(--red);border-color:var(--red)}
  .toggle{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--mut);margin:4px 0 10px}
  .toggle input{width:auto}
  .rule{border:1px solid var(--line);background:#0e141b;border-radius:12px;padding:12px;margin-bottom:10px}
  .rule .name{font-weight:700;line-height:1.9;margin-bottom:8px}
  .rule .name span{display:inline-block;background:#1b2634;border-radius:7px;padding:2px 8px;margin:2px 0 2px 4px;font-size:13px}
  .cols{display:grid;grid-template-columns:1fr 1fr;gap:8px}
  .box{background:#111a24;border-radius:9px;padding:8px;font-size:12px;color:var(--mut)}
  .box b{display:block;color:var(--txt);font-size:15px;margin-top:2px}
  .dirbox{margin-top:8px}
  .dirbox b{font-size:14px}
  .folds{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px;font-size:12px;color:var(--mut);align-items:center}
  .fold{padding:3px 9px;border-radius:8px;background:#111a24}
  .fold.ok{color:var(--green)}.fold.no{color:var(--red)}
  .badge{float:left;font-size:11px;padding:3px 9px;border-radius:99px;font-weight:700}
  .badge.good{background:rgba(46,204,113,.16);color:var(--green)}
  .badge.vol{background:rgba(245,185,66,.16);color:var(--amber)}
  .badge.weak{background:rgba(255,92,92,.14);color:var(--red)}
  .empty{color:var(--mut);text-align:center;padding:18px}
  .note{color:var(--mut);font-size:12px;line-height:1.8}
  #loader{position:fixed;inset:0;background:rgba(5,8,12,.86);display:none;align-items:center;justify-content:center;
          flex-direction:column;gap:14px;z-index:9;font-weight:700}
  .spin{width:44px;height:44px;border-radius:50%;border:4px solid var(--line);border-top-color:var(--green);animation:s 1s linear infinite}
  @keyframes s{to{transform:rotate(360deg)}}
  @media(max-width:480px){.stats{grid-template-columns:1fr 1fr}.grid3{grid-template-columns:1fr 1fr}}
</style>
</head>
<body>
<div id="loader"><div class="spin"></div><div>جاري تحميل البيانات والتحليل...</div></div>

<header>
  <div class="logo">SM</div>
  <div><h1>Strategy Miner</h1><small>اكتشاف ما يسبق الصعود والهبوط القوي</small></div>
</header>

<form method="post" class="card" id="f">
  <details {{ 'open' if not res else '' }}>
    <summary>الإعدادات</summary>
    <div class="grid">
      <div><label>الزوج</label><input name="symbol" value="{{ f.symbol }}" autocapitalize="characters"></div>
      <div><label>الفريم</label>
        <select name="interval">
          {% for i in intervals %}<option value="{{ i }}" {{ 'selected' if i==f.interval }}>{{ i }}</option>{% endfor %}
        </select></div>
    </div>
    <div class="chips">
      {% for s in ['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT'] %}
      <span class="chip" onclick="document.querySelector('[name=symbol]').value='{{ s }}'">{{ s }}</span>{% endfor %}
    </div>
    <div class="grid3">
      <div><label>عدد الأيام</label><input name="days" type="number" min="1" value="{{ f.days }}"></div>
      <div><label>من تاريخ</label><input name="start" type="date" value="{{ f.start }}"></div>
      <div><label>إلى تاريخ</label><input name="end" type="date" value="{{ f.end }}"></div>
    </div>
    <div class="grid3">
      <div><label>الحركة %</label><input name="pct" type="number" step="0.1" value="{{ f.pct }}"></div>
      <div><label>خلال (شموع)</label><input name="candles" type="number" min="1" value="{{ f.candles }}"></div>
      <div><label>شروط/قاعدة</label>
        <select name="combo">{% for k in [1,2,3] %}<option value="{{ k }}" {{ 'selected' if k|string==f.combo|string }}>{{ k }}</option>{% endfor %}</select></div>
    </div>
    <div class="grid3">
      <div><label>أقل حالات</label><input name="min_samples" type="number" min="5" value="{{ f.min_samples }}"></div>
      <div><label>أقل Lift</label><input name="min_lift" type="number" step="0.05" value="{{ f.min_lift }}"></div>
      <div><label>Lookback</label><input name="lookback" type="number" min="1" value="{{ f.lookback }}"></div>
    </div>
    <div class="grid">
      <div><label>نسبة الاستخراج (الباقي اختبار)</label><input name="train" type="number" step="0.05" min="0.4" max="0.9" value="{{ f.train }}"></div>
    </div>
  </details>
  <button class="go" type="submit">ابدأ التحليل</button>
</form>

{% if error %}<div class="err">{{ error }}</div>{% endif %}

{% if res %}
<div class="card">
  <div class="stats">
    <div class="stat"><b>{{ res.candles }}</b><span>شمعة</span></div>
    <div class="stat"><b class="up">{{ res.ups }}</b><span>أحداث صعود ({{ res.bu }}%)</span></div>
    <div class="stat"><b class="dn">{{ res.dns }}</b><span>أحداث هبوط ({{ res.bd }}%)</span></div>
    <div class="stat"><b>{{ res.event }}</b><span>تعريف الحدث</span></div>
  </div>
</div>

{% if res.chart %}
<div class="card">
  <div id="chart"></div>
  <div class="legend">
    <span><b class="up">▲</b> بداية حركة صعود قوية</span>
    <span><b class="dn">▼</b> بداية حركة هبوط قوية</span>
    <span>آخر {{ res.chart.candles|length }} شمعة</span>
  </div>
</div>
{% endif %}

<div class="card">
  <div class="tabs">
    <button type="button" class="tab buy active" data-t="buy">شراء ({{ res.buy|length }}) · موثوقة {{ res.buy_good }}</button>
    <button type="button" class="tab sell" data-t="sell">بيع ({{ res.sell|length }}) · موثوقة {{ res.sell_good }}</button>
  </div>
  <label class="toggle"><input type="checkbox" id="onlygood"> إظهار الموثوقة فقط (Lift + اتجاه واضح)</label>

  {% for side, rows in [('buy', res.buy), ('sell', res.sell)] %}
  <div class="pane" id="pane-{{ side }}" style="{{ '' if side=='buy' else 'display:none' }}">
    {% for r in rows %}
    <div class="rule" data-good="{{ 1 if r.state=='good' else 0 }}">
      <span class="badge {{ r.state }}">{{ r.label }}</span>
      <div class="name">{% for part in r.parts %}<span>{{ part }}</span>{% endfor %}</div>
      <div class="cols">
        <div class="box">الاستخراج ({{ r.n }} حالة)<b>{{ r.p }} · Lift {{ r.lift }}</b></div>
        <div class="box">الاختبار ({{ r.tn }} حالة)<b>{{ r.tp }} · Lift {{ r.tlift }}</b></div>
      </div>
      <div class="box dirbox">
        الاتجاه في الاختبار: صعود {{ r.pu }} مقابل هبوط {{ r.pd }}
        <b class="{{ 'up' if r.dir_ok else 'am' }}">نسبة {{ r.side_name }} من الحركات: {{ r.share }} (الأساس {{ r.bshare }})</b>
      </div>
      <div class="folds">
        <span>الثبات: {{ r.fold_ok }}/{{ r.folds|length }}</span>
        {% for fo in r.folds %}<span class="fold {{ 'ok' if fo.ok else 'no' }}">فترة {{ loop.index }} · Lift {{ fo.lift }} ({{ fo.n }})</span>{% endfor %}
      </div>
    </div>
    {% else %}
    <div class="empty">لا توجد قواعد تحقق الحد الأدنى. خفّف «أقل Lift» أو «أقل حالات» أو وسّع الفترة.</div>
    {% endfor %}
    <div class="empty pane-empty" style="display:none">لا توجد قواعد موثوقة هنا.</div>
  </div>
  {% endfor %}
  <p class="note">
    <b>Lift</b>: احتمال الحدث عند تحقق الشرط ÷ احتماله العام.<br>
    <b>موثوقة</b>: Lift الاختبار ≥ 1.1 (15 حالة على الأقل) <b>و</b> نسبة الاتجاه أعلى من الأساس بـ 5 نقاط فأكثر.<br>
    <b class="am">تقلب فقط</b>: Lift جيد لكن الصعود والهبوط يزيدان معاً، أي لا ميزة اتجاهية.<br>
    <b>الثبات</b>: الفترة الزمنية مقسومة إلى {{ res.folds_n }} أجزاء متساوية؛ الفترات الأولى تتداخل مع بيانات الاستخراج والأخيرة للاختبار.<br>
    أداة بحث وليست توصية تداول، ولا تشمل الرسوم والانزلاق.
  </p>
</div>

<script>
const tabs=document.querySelectorAll('.tab'), chk=document.getElementById('onlygood');
function refresh(){
  document.querySelectorAll('.pane').forEach(p=>{
    let shown=0;
    p.querySelectorAll('.rule').forEach(r=>{
      const hide=chk.checked && r.dataset.good!=='1';
      r.style.display=hide?'none':''; if(!hide) shown++;
    });
    const hasRules=p.querySelectorAll('.rule').length>0;
    p.querySelector('.pane-empty').style.display=(hasRules&&shown===0)?'block':'none';
  });
}
tabs.forEach(t=>t.onclick=()=>{
  tabs.forEach(x=>x.classList.remove('active')); t.classList.add('active');
  document.getElementById('pane-buy').style.display=t.dataset.t==='buy'?'':'none';
  document.getElementById('pane-sell').style.display=t.dataset.t==='sell'?'':'none';
});
chk.onchange=refresh; refresh();

{% if res.chart %}
(function(){
  const d={{ res.chart|tojson }};
  const el=document.getElementById('chart');
  const chart=LightweightCharts.createChart(el,{
    width:el.clientWidth,height:340,
    layout:{background:{color:'#141b24'},textColor:'#8fa1b5'},
    grid:{vertLines:{color:'#1b2634'},horzLines:{color:'#1b2634'}},
    rightPriceScale:{borderColor:'#223041'},
    timeScale:{borderColor:'#223041',timeVisible:true,secondsVisible:false}
  });
  const s=chart.addCandlestickSeries({upColor:'#2ecc71',downColor:'#ff5c5c',
    borderUpColor:'#2ecc71',borderDownColor:'#ff5c5c',wickUpColor:'#2ecc71',wickDownColor:'#ff5c5c'});
  s.setData(d.candles);
  s.setMarkers(d.markers.map(m=>m.up
    ?{time:m.t,position:'belowBar',color:'#2ecc71',shape:'arrowUp'}
    :{time:m.t,position:'aboveBar',color:'#ff5c5c',shape:'arrowDown'}));
  chart.timeScale().fitContent();
  window.addEventListener('resize',()=>chart.applyOptions({width:el.clientWidth}));
})();
{% endif %}
</script>
{% endif %}

<script>
document.getElementById('f').addEventListener('submit',()=>{document.getElementById('loader').style.display='flex'});
</script>
</body></html>
"""


def defaults():
    c = sm.CONFIG
    return {"symbol": c["SYMBOL"], "interval": c["INTERVAL"], "days": DEFAULT_DAYS,
            "pct": c["EVENT_PCT"], "candles": c["EVENT_CANDLES"], "combo": c["MAX_COMBO"],
            "start": "", "end": "", "min_samples": c["MIN_SAMPLES"], "min_lift": c["MIN_LIFT"],
            "lookback": c["LOOKBACK"], "train": c["TRAIN_RATIO"]}


def fmt_pct(x):
    return "-" if x is None or x != x else f"{x * 100:.0f}%"


def fmt_num(x):
    return "-" if x is None or x != x else f"{x:.2f}"


# ---------------------------------------------------------------------
#                     إحصاءات الاتجاه والثبات لكل قاعدة
# ---------------------------------------------------------------------
def rule_mask(conds, rule):
    return np.logical_and.reduce([conds[c] for c in rule.split(" + ")])


def side_probs(mask, labels, idx):
    """يرجع: عدد الحالات، احتمال الصعود أولاً، احتمال الهبوط أولاً، والأساس لكل منهما (في الفترة idx)."""
    valid = idx & ~np.isnan(labels)
    base = labels[valid]
    bu = float((base == 1).mean()) if len(base) else np.nan
    bd = float((base == -1).mean()) if len(base) else np.nan
    sel = labels[mask & valid]
    n = int(len(sel))
    if n == 0:
        return n, np.nan, np.nan, bu, bd
    return n, float((sel == 1).mean()), float((sel == -1).mean()), bu, bd


def share(pu, pd_, side):
    tot = pu + pd_
    if tot != tot or tot <= 0:
        return np.nan
    return (pu if side == "buy" else pd_) / tot


def to_rows(df, top, side, ctx):
    conds, labels, test, blocks = ctx["conds"], ctx["labels"], ctx["test"], ctx["blocks"]
    rows = []
    for _, r in df.head(top).iterrows():
        mask = rule_mask(conds, r["القاعدة"])
        tl = r.get("test_Lift")
        tn = int(r["test_حالات"])

        _, pu, pd_, bu, bd = side_probs(mask, labels, test)
        d_share, b_share = share(pu, pd_, side), share(bu, bd, side)
        edge = (d_share - b_share) if (d_share == d_share and b_share == b_share) else np.nan
        dir_ok = bool(edge == edge and edge >= 0.05)
        lift_ok = bool(tl == tl and tl >= 1.1 and tn >= 15)

        folds = []
        for blk in blocks:
            n2, pu2, pd2, bu2, bd2 = side_probs(mask, labels, blk)
            p = pu2 if side == "buy" else pd2
            b = bu2 if side == "buy" else bd2
            lift = (p / b) if (n2 > 0 and p == p and b == b and b > 0) else np.nan
            folds.append({"n": n2, "lift": fmt_num(lift),
                          "ok": bool(n2 >= 10 and lift == lift and lift >= 1.1)})

        state = "good" if (lift_ok and dir_ok) else ("vol" if lift_ok else "weak")
        rows.append({
            "parts": r["القاعدة"].split(" + "), "n": int(r["الحالات"]),
            "p": fmt_pct(r["النسبة"]), "lift": fmt_num(r["Lift"]),
            "tn": tn, "tp": fmt_pct(r["test_نسبة"]), "tlift": fmt_num(tl),
            "pu": fmt_pct(pu), "pd": fmt_pct(pd_),
            "share": fmt_pct(d_share), "bshare": fmt_pct(b_share),
            "side_name": "الصعود" if side == "buy" else "الهبوط",
            "dir_ok": dir_ok, "state": state,
            "label": {"good": "موثوقة", "vol": "تقلب فقط", "weak": "ضعيفة"}[state],
            "folds": folds, "fold_ok": sum(1 for f in folds if f["ok"]),
        })
    return rows


def build_chart(df, labels):
    n = len(df)
    start = max(0, n - CHART_CANDLES)
    t = pd.to_datetime(df["time"], utc=True)
    ts = ((t - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(seconds=1)).astype("int64").values
    candles, markers = [], []
    for i in range(start, n):
        candles.append({"time": int(ts[i]), "open": float(df["open"].iat[i]), "high": float(df["high"].iat[i]),
                        "low": float(df["low"].iat[i]), "close": float(df["close"].iat[i])})
        lab = labels[i]
        prev = labels[i - 1] if i > 0 else np.nan
        if lab == 1 and prev != 1:
            markers.append({"t": int(ts[i]), "up": True})
        elif lab == -1 and prev != -1:
            markers.append({"t": int(ts[i]), "up": False})
    return {"candles": candles, "markers": markers[-400:]}


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
    size = len(df)
    split = int(size * cfg["TRAIN_RATIO"])
    train = np.zeros(size, bool)
    train[:split] = True
    test = ~train

    blocks = []
    for part in np.array_split(np.arange(size), FOLDS):
        m = np.zeros(size, bool)
        m[part] = True
        blocks.append(m)
    ctx = {"conds": conds, "labels": labels, "test": test, "blocks": blocks}

    rules, bu, bd = sm.mine(conds, labels, train, cfg)
    res = {"candles": size, "ups": int((labels == 1).sum()), "dns": int((labels == -1).sum()),
           "bu": f"{bu * 100:.1f}", "bd": f"{bd * 100:.1f}", "buy": [], "sell": [],
           "buy_good": 0, "sell_good": 0, "folds_n": FOLDS,
           "event": f"±{cfg['EVENT_PCT']}% / {cfg['EVENT_CANDLES']}",
           "chart": build_chart(df, labels)}
    if not rules.empty:
        rules = sm.validate(rules.sort_values("z", ascending=False), conds, labels, test, cfg)
        res["buy"] = to_rows(rules[rules["الاتجاه"] == "شراء"], 10, "buy", ctx)
        res["sell"] = to_rows(rules[rules["الاتجاه"] == "بيع"], 10, "sell", ctx)
        res["buy_good"] = sum(1 for r in res["buy"] if r["state"] == "good")
        res["sell_good"] = sum(1 for r in res["sell"] if r["state"] == "good")
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
