"""استراتيجية F-INVEST (إعادة بناء من إعدادات المؤشر في الفيديو).

القواعد (لكل شمعة مغلقة i):
  1) الاتجاه (Impulse): المتوسط السريع (RMA 50) فوق البطيء (RMA 112) = صاعد، والعكس = هابط.
  2) الإشارة (نوع الدخول entry):
       - "fast"  : الإغلاق يقطع المتوسط السريع في اتجاه الترند (افتراضي)
       - "cross" : المتوسط السريع يقطع البطيء
     والشمعة يجب أن تُغلق في اتجاه الصفقة (خضراء للشراء، حمراء للبيع).
  3) فلتر الحجم الذكي: حجم الشمعة > المستوى × متوسط حجم آخر N شمعة.
  4) تأكيد الزخم (اختياري، مطفأ افتراضياً): لا شراء إذا RSI فوق التشبع الشرائي، ولا بيع إذا RSI تحت التشبع البيعي.

كل الحسابات تُجرى مرة واحدة على السلسلة كاملة، فيستعملها البوت والباكتيست بنفس الطريقة.
"""

DEFAULTS = {
    "vol_on": 1, "vol_level": 1.0, "vol_n": 10,
    "imp_on": 1, "fast": 50, "slow": 112, "ma_mode": "rma", "src": "close", "entry": "fast",
    "mom_on": 0, "rsi_n": 11, "ob": 65.0, "os": 38.0,
    "sl": 10.0, "tp": 5.0,
}


def _src(c, kind):
    if kind == "hl2":
        return (c["h"] + c["l"]) / 2
    if kind == "hlc3":
        return (c["h"] + c["l"] + c["c"]) / 3
    if kind == "ohlc4":
        return (c["o"] + c["h"] + c["l"] + c["c"]) / 4
    return c["c"]


def ma(xs, n, mode="rma"):
    """RMA / EMA / SMA بنفس طريقة TradingView (البداية بمتوسط بسيط). القيم قبل n = None."""
    n = max(1, int(n))
    out = [None] * len(xs)
    if len(xs) < n:
        return out
    if mode == "sma":
        s = sum(xs[:n])
        out[n - 1] = s / n
        for i in range(n, len(xs)):
            s += xs[i] - xs[i - n]
            out[i] = s / n
        return out
    a = 1.0 / n if mode == "rma" else 2.0 / (n + 1)
    v = sum(xs[:n]) / n
    out[n - 1] = v
    for i in range(n, len(xs)):
        v = a * xs[i] + (1 - a) * v
        out[i] = v
    return out


def rsi(cl, n):
    out = [None] * len(cl)
    if len(cl) <= n:
        return out
    g = l = 0.0
    for i in range(1, n + 1):
        d = cl[i] - cl[i - 1]
        g += max(d, 0); l += max(-d, 0)
    g /= n; l /= n
    out[n] = 100.0 if l == 0 else 100 - 100 / (1 + g / l)
    for i in range(n + 1, len(cl)):
        d = cl[i] - cl[i - 1]
        g = (g * (n - 1) + max(d, 0)) / n
        l = (l * (n - 1) + max(-d, 0)) / n
        out[i] = 100.0 if l == 0 else 100 - 100 / (1 + g / l)
    return out


def compute(cs, cfg):
    """cs: شموع مغلقة من الأقدم للأحدث. يرجع السلاسل والإشارات (sig[i] = 'BUY' / 'SELL' / None)."""
    p = dict(DEFAULTS); p.update({k: v for k, v in (cfg or {}).items() if k in DEFAULTS})
    src = [_src(c, p["src"]) for c in cs]
    fast = ma(src, p["fast"], p["ma_mode"])
    slow = ma(src, p["slow"], p["ma_mode"])
    R = rsi([c["c"] for c in cs], int(p["rsi_n"]))
    vn = max(1, int(p["vol_n"]))
    vol = [float(c.get("v") or 0) for c in cs]
    sig = [None] * len(cs)
    vs = 0.0
    for i in range(len(cs)):
        vs += vol[i]
        if i >= vn:
            vs -= vol[i - vn]
        if i < 1 or fast[i] is None or slow[i] is None or fast[i - 1] is None or slow[i - 1] is None:
            continue
        c = cs[i]
        # 3) الحجم
        if int(p["vol_on"]):
            if i < vn - 1:
                continue
            if vol[i] <= float(p["vol_level"]) * (vs / vn):
                continue
        # 1) + 2) الاتجاه والإشارة
        up, dn = fast[i] > slow[i], fast[i] < slow[i]
        if p["entry"] == "cross":
            b = fast[i - 1] <= slow[i - 1] and fast[i] > slow[i]
            s = fast[i - 1] >= slow[i - 1] and fast[i] < slow[i]
        else:
            b = src[i - 1] <= fast[i - 1] and src[i] > fast[i]
            s = src[i - 1] >= fast[i - 1] and src[i] < fast[i]
        if int(p["imp_on"]):
            b, s = b and up, s and dn
        b = b and c["c"] > c["o"]
        s = s and c["c"] < c["o"]
        # 4) الزخم
        if int(p["mom_on"]) and R[i] is not None:
            b = b and R[i] < float(p["ob"])
            s = s and R[i] > float(p["os"])
        sig[i] = "BUY" if b else ("SELL" if s else None)
    return {"sig": sig, "fast": fast, "slow": slow, "rsi": R}
