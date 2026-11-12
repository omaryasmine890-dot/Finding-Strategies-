#!/usr/bin/env python3
"""
Strategy Miner - أداة استخراج الأنماط قبل التحركات السعرية القوية

تشغيل:
    pip install -r requirements.txt
    python strategy_miner.py
    python strategy_miner.py --symbol ETHUSDT --interval 5m --days 14
    python strategy_miner.py --csv my_data.csv
"""
import argparse
import itertools
import sys
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

# =====================================================================
#                         الإعدادات (عدّلها هنا)
# =====================================================================
CONFIG = {
    # --- البيانات ---
    "SYMBOL": "BTCUSDT",        # الزوج (Binance Spot)
    "INTERVAL": "15m",          # 1m 3m 5m 15m 30m 1h 4h 1d
    "DAYS": 30,                 # عدد الأيام الأخيرة (تُتجاهل إذا حددت START)
    "START": None,              # مثال: "2026-09-01"
    "END": None,                # مثال: "2026-10-01"
    "CSV": None,                # مسار ملف CSV بدل التحميل من الإنترنت

    # --- تعريف الحدث السعري ---
    "EVENT_PCT": 1.0,           # نسبة الحركة % (صعود أو هبوط)
    "EVENT_CANDLES": 8,         # خلال كم شمعة؟

    # --- التعدين ---
    "MAX_COMBO": 2,             # أقصى عدد شروط في القاعدة (1 إلى 3)
    "LOOKBACK": 1,              # الشرط محقق إذا ظهر في آخر N شمعة
    "MIN_SAMPLES": 30,          # أقل عدد حالات لقبول القاعدة
    "MIN_LIFT": 1.2,            # أقل Lift مقابل الاحتمال العام
    "TRAIN_RATIO": 0.7,         # نسبة بيانات الاستخراج؛ الباقي للتحقق
    "TOP_N": 10,                # عدد القواعد المعروضة لكل اتجاه

    # --- المؤشرات ---
    "RSI_PERIOD": 14,
    "ATR_PERIOD": 14,
    "BB_PERIOD": 20,
    "VOL_PERIOD": 20,
    "EMA_PERIOD": 50,
    "BREAKOUT_PERIOD": 20,

    # --- المخرجات ---
    "OUTPUT_CSV": "mined_rules.csv",
}

BINANCE_URL = "https://api.binance.com/api/v3/klines"
INTERVAL_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
}


# =====================================================================
#                           تحميل البيانات
# =====================================================================
def fetch_binance(symbol, interval, start_ms, end_ms):
    import requests

    if interval not in INTERVAL_MS:
        sys.exit(f"فريم غير مدعوم: {interval}")
    step = INTERVAL_MS[interval]
    rows, cur = [], start_ms
    while cur < end_ms:
        r = requests.get(
            BINANCE_URL,
            params={"symbol": symbol, "interval": interval,
                    "startTime": cur, "endTime": end_ms, "limit": 1000},
            timeout=20,
        )
        if r.status_code != 200:
            sys.exit(f"خطأ من Binance ({r.status_code}): {r.text[:200]}")
        batch = r.json()
        if not batch:
            break
        rows += batch
        cur = batch[-1][0] + step
        time.sleep(0.15)
    if not rows:
        sys.exit("لم تصل أي بيانات. تحقق من الزوج أو الفترة.")
    df = pd.DataFrame(rows).iloc[:, :6]
    df.columns = ["time", "open", "high", "low", "close", "volume"]
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    return df.astype({c: float for c in ["open", "high", "low", "close", "volume"]})


def load_data(cfg):
    if cfg["CSV"]:
        df = pd.read_csv(cfg["CSV"])
        df.columns = [c.strip().lower() for c in df.columns]
        need = {"open", "high", "low", "close", "volume"}
        if not need.issubset(df.columns):
            sys.exit(f"الملف يحتاج الأعمدة: {sorted(need)}")
        if "time" in df.columns:
            df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
        else:
            df["time"] = pd.RangeIndex(len(df))
        return df[["time", "open", "high", "low", "close", "volume"]].reset_index(drop=True)

    end = (datetime.fromisoformat(cfg["END"]).replace(tzinfo=timezone.utc)
           if cfg["END"] else datetime.now(timezone.utc))
    start = (datetime.fromisoformat(cfg["START"]).replace(tzinfo=timezone.utc)
             if cfg["START"] else end - timedelta(days=cfg["DAYS"]))
    print(f"تحميل {cfg['SYMBOL']} {cfg['INTERVAL']} من {start:%Y-%m-%d} إلى {end:%Y-%m-%d} ...")
    return fetch_binance(cfg["SYMBOL"], cfg["INTERVAL"],
                         int(start.timestamp() * 1000), int(end.timestamp() * 1000))


# =====================================================================
#                      تحديد الأحداث (صعود / هبوط)
# =====================================================================
def label_events(df, pct, n):
    """
    لكل شمعة i (الدخول عند إغلاقها):
      +1 إذا لمس السعر +pct% قبل -pct% خلال n شمعة
      -1 إذا لمس -pct% قبل +pct%
       0 إذا لم يحدث شيء أو حدث الاثنان في نفس الشمعة
      NaN لآخر n شمعة
    """
    close, hi, lo = df["close"].values, df["high"].values, df["low"].values
    size = len(df)
    out = np.full(size, np.nan)
    f = pct / 100.0
    for i in range(size - n):
        up = close[i] * (1 + f)
        dn = close[i] * (1 - f)
        wh, wl = hi[i + 1:i + n + 1], lo[i + 1:i + n + 1]
        hit_up, hit_dn = wh >= up, wl <= dn
        iu = hit_up.argmax() if hit_up.any() else n + 1
        idn = hit_dn.argmax() if hit_dn.any() else n + 1
        if iu == idn:
            out[i] = 0
        else:
            out[i] = 1 if iu < idn else -1
    return out


# =====================================================================
#                    المؤشرات والشروط (Features)
# =====================================================================
def rsi(close, period):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def build_conditions(df, cfg):
    o, h, l, c, v = (df[k] for k in ["open", "high", "low", "close", "volume"])
    rng = (h - l).replace(0, np.nan)
    body = (c - o).abs()
    upper = h - np.maximum(o, c)
    lower = np.minimum(o, c) - l

    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / cfg["ATR_PERIOD"], adjust=False).mean()
    atr_pct = atr / c * 100

    vol_ratio = v / v.rolling(cfg["VOL_PERIOD"]).mean()
    r = rsi(c, cfg["RSI_PERIOD"])
    ma = c.rolling(cfg["BB_PERIOD"]).mean()
    sd = c.rolling(cfg["BB_PERIOD"]).std()
    bb_width = (4 * sd) / ma
    squeeze = bb_width < bb_width.rolling(100).quantile(0.2)
    ema = c.ewm(span=cfg["EMA_PERIOD"], adjust=False).mean()
    bp = cfg["BREAKOUT_PERIOD"]
    prev_hi, prev_lo = h.shift().rolling(bp).max(), l.shift().rolling(bp).min()

    bull = c > o
    bear = c < o
    prev_body_hi, prev_body_lo = np.maximum(o, c).shift(), np.minimum(o, c).shift()

    cond = {
        # الحجم
        "حجم > 1.5x المتوسط": vol_ratio > 1.5,
        "حجم > 2x المتوسط": vol_ratio > 2,
        "حجم > 3x المتوسط": vol_ratio > 3,
        "حجم < 0.6x (هدوء)": vol_ratio < 0.6,
        # RSI
        "RSI < 30": r < 30,
        "RSI < 40": r < 40,
        "RSI > 60": r > 60,
        "RSI > 70": r > 70,
        # نماذج الشموع
        "ابتلاع شرائي": bull & bear.shift(fill_value=False) & (c >= prev_body_hi) & (o <= prev_body_lo),
        "ابتلاع بيعي": bear & bull.shift(fill_value=False) & (c <= prev_body_lo) & (o >= prev_body_hi),
        "مطرقة/Pinbar سفلي": (lower > 2 * body) & (upper < body.clip(lower=1e-12)) & (lower / rng > 0.6),
        "نجمة/Pinbar علوي": (upper > 2 * body) & (lower < body.clip(lower=1e-12)) & (upper / rng > 0.6),
        "دوجي": body / rng < 0.1,
        "شمعة صاعدة قوية": bull & (body / c * 100 > 1.0 * atr_pct),
        "شمعة هابطة قوية": bear & (body / c * 100 > 1.0 * atr_pct),
        # التقلب
        "ضغط بولنجر (Squeeze)": squeeze,
        "ATR مرتفع": atr_pct > atr_pct.rolling(100).quantile(0.8),
        "ATR منخفض": atr_pct < atr_pct.rolling(100).quantile(0.2),
        # الاتجاه
        "فوق EMA": c > ema,
        "تحت EMA": c < ema,
        "بعيد فوق EMA (>2 ATR)": (c - ema) > 2 * atr,
        "بعيد تحت EMA (>2 ATR)": (ema - c) > 2 * atr,
        # كسر مستويات
        "كسر قمة سابقة": c > prev_hi,
        "كسر قاع سابق": c < prev_lo,
    }
    L = max(1, int(cfg["LOOKBACK"]))
    out = {}
    for name, s in cond.items():
        s = s.fillna(False).astype(bool)
        if L > 1:
            s = s.rolling(L, min_periods=1).max().astype(bool)
        out[name] = s.values
    return out


# =====================================================================
#                         تعدين القواعد
# =====================================================================
def eval_mask(mask, labels, target):
    sel = labels[mask]
    sel = sel[~np.isnan(sel)]
    n = len(sel)
    if n == 0:
        return 0, np.nan
    return n, float((sel == target).mean())


def mine(conds, labels, idx, cfg):
    names = list(conds)
    valid = idx & ~np.isnan(labels)
    base_up = float((labels[valid] == 1).mean())
    base_dn = float((labels[valid] == -1).mean())
    results = []
    for k in range(1, cfg["MAX_COMBO"] + 1):
        for combo in itertools.combinations(names, k):
            mask = np.logical_and.reduce([conds[c] for c in combo]) & idx
            n_all = int((mask & valid).sum())
            if n_all < cfg["MIN_SAMPLES"]:
                continue
            for side, target, base in (("شراء", 1, base_up), ("بيع", -1, base_dn)):
                n, p = eval_mask(mask, labels, target)
                if base <= 0 or p != p:
                    continue
                lift = p / base
                z = (p - base) / np.sqrt(base * (1 - base) / n)
                if lift >= cfg["MIN_LIFT"]:
                    results.append({"الاتجاه": side, "القاعدة": " + ".join(combo),
                                    "الحالات": n, "النسبة": p, "الأساس": base,
                                    "Lift": lift, "z": z})
    return pd.DataFrame(results), base_up, base_dn


def validate(rules, conds, labels, idx, cfg):
    valid = idx & ~np.isnan(labels)
    rows = []
    for _, r in rules.iterrows():
        mask = np.logical_and.reduce([conds[c] for c in r["القاعدة"].split(" + ")]) & idx
        target = 1 if r["الاتجاه"] == "شراء" else -1
        base = float((labels[valid] == target).mean())
        n, p = eval_mask(mask, labels, target)
        rows.append({"test_حالات": n,
                     "test_نسبة": p,
                     "test_Lift": (p / base) if (base > 0 and p == p) else np.nan})
    return pd.concat([rules.reset_index(drop=True), pd.DataFrame(rows)], axis=1)


# =====================================================================
#                              التشغيل
# =====================================================================
def print_table(df, title, top):
    print(f"\n=== {title} ===")
    if df.empty:
        print("لا توجد قواعد تحقق الحد الأدنى (خفّف MIN_LIFT أو MIN_SAMPLES أو زد الفترة).")
        return
    for _, r in df.head(top).iterrows():
        t = ""
        if "test_حالات" in r and r["test_حالات"] == r["test_حالات"]:
            t = (f" | اختبار: {int(r['test_حالات'])} حالة، "
                 f"{r['test_نسبة'] * 100:.0f}%، Lift {r['test_Lift']:.2f}")
        print(f"- {r['القاعدة']}\n    استخراج: {int(r['الحالات'])} حالة، "
              f"{r['النسبة'] * 100:.0f}% (الأساس {r['الأساس'] * 100:.0f}%)، "
              f"Lift {r['Lift']:.2f}{t}")


def parse_args():
    p = argparse.ArgumentParser(description="Strategy Miner")
    p.add_argument("--symbol"); p.add_argument("--interval")
    p.add_argument("--days", type=int); p.add_argument("--start"); p.add_argument("--end")
    p.add_argument("--csv"); p.add_argument("--pct", type=float); p.add_argument("--candles", type=int)
    p.add_argument("--combo", type=int); p.add_argument("--lookback", type=int)
    p.add_argument("--min-samples", type=int); p.add_argument("--min-lift", type=float)
    p.add_argument("--train", type=float); p.add_argument("--top", type=int)
    p.add_argument("--out")
    return p.parse_args()


def main():
    cfg = dict(CONFIG)
    a = parse_args()
    mapping = {"symbol": "SYMBOL", "interval": "INTERVAL", "days": "DAYS", "start": "START",
               "end": "END", "csv": "CSV", "pct": "EVENT_PCT", "candles": "EVENT_CANDLES",
               "combo": "MAX_COMBO", "lookback": "LOOKBACK", "min_samples": "MIN_SAMPLES",
               "min_lift": "MIN_LIFT", "train": "TRAIN_RATIO", "top": "TOP_N", "out": "OUTPUT_CSV"}
    for arg, key in mapping.items():
        if getattr(a, arg) is not None:
            cfg[key] = getattr(a, arg)

    df = load_data(cfg)
    print(f"عدد الشموع: {len(df)}")
    if len(df) < 300:
        sys.exit("بيانات قليلة جداً (أقل من 300 شمعة). وسّع الفترة.")

    labels = label_events(df, cfg["EVENT_PCT"], cfg["EVENT_CANDLES"])
    conds = build_conditions(df, cfg)

    split = int(len(df) * cfg["TRAIN_RATIO"])
    train = np.zeros(len(df), bool); train[:split] = True
    test = ~train

    ups = int((labels == 1).sum()); dns = int((labels == -1).sum())
    print(f"أحداث صعود: {ups} | أحداث هبوط: {dns} "
          f"(±{cfg['EVENT_PCT']}% خلال {cfg['EVENT_CANDLES']} شمعة)")

    rules, bu, bd = mine(conds, labels, train, cfg)
    print(f"الاحتمال العام في فترة الاستخراج: صعود {bu * 100:.1f}% | هبوط {bd * 100:.1f}%")
    if rules.empty:
        print_table(rules, "النتائج", cfg["TOP_N"])
        return
    rules = rules.sort_values("z", ascending=False)
    rules = validate(rules, conds, labels, test, cfg)

    for side in ("شراء", "بيع"):
        print_table(rules[rules["الاتجاه"] == side], f"أفضل قواعد {side}", cfg["TOP_N"])

    rules.to_csv(cfg["OUTPUT_CSV"], index=False, encoding="utf-8-sig")
    print(f"\nتم حفظ كل القواعد في: {cfg['OUTPUT_CSV']}")
    print("تنبيه: القاعدة المفيدة هي التي يبقى Lift الاختبار فيها قريباً من Lift الاستخراج وفوق 1.")


if __name__ == "__main__":
    main()
