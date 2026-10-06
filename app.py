"""Trade Radar — مسح تلقائي، 11 مؤشر، أفضل 3 فرص.
المصادر:
  otc  = أسعار Pocket Option OTC من OTCharts (يحتاج OTCHARTS_API_KEY)
  real = أزواج السوق الحقيقي من Yahoo Finance (مجاني، أيام الأسبوع فقط)
في وضع OTC الرادار يوزّع الطلبات المتبقية تلقائيًا عشان ما تخلص قبل التجديد."""
import json
import math
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Lock, Thread, Event

from flask import Flask, jsonify, render_template, request

try:
    import otcharts
except ImportError:
    otcharts = None

app = Flask(__name__)
lock = Lock()
wake = Event()

REAL_PAIRS = {
    "EUR/USD": "EURUSD=X", "GBP/USD": "GBPUSD=X", "USD/JPY": "JPY=X",
    "AUD/USD": "AUDUSD=X", "USD/CAD": "CAD=X", "USD/CHF": "CHF=X",
    "NZD/USD": "NZDUSD=X", "EUR/JPY": "EURJPY=X", "GBP/JPY": "GBPJPY=X",
    "EUR/GBP": "EURGBP=X", "AUD/JPY": "AUDJPY=X", "EUR/AUD": "EURAUD=X",
    "CAD/JPY": "CADJPY=X", "CHF/JPY": "CHFJPY=X", "AUD/CAD": "AUDCAD=X",
    "EUR/CHF": "EURCHF=X",
}
SOURCES = {
    "otc": "Pocket Option OTC — OTCharts",
    "real": "Real market — Yahoo Finance (weekdays only)",
}
MAX_OTC_PAIRS = int(os.getenv("MAX_OTC_PAIRS", "20"))  # سقف الأزواج عشان الطلبات
PO_CLOCK_OFFSET = 7200   # Pocket Option يختم الشموع UTC+2
STALE_SECONDS = 20 * 60
CANDLES = 150

# ---------------- المؤشرات ----------------
def ema_series(values, n):
    k = 2 / (n + 1)
    out = [sum(values[:n]) / n]
    for v in values[n:]:
        out.append(v * k + out[-1] * (1 - k))
    return out  # يبدأ من الشمعة رقم n-1


def ema(values, n):
    return ema_series(values, n)[-1]


def sma(values, n):
    return sum(values[-n:]) / n


def true_ranges(c):
    return [max(c[i]["h"] - c[i]["l"], abs(c[i]["h"] - c[i - 1]["c"]), abs(c[i]["l"] - c[i - 1]["c"]))
            for i in range(1, len(c))]


def wilder(values, n):
    s = sum(values[:n])
    out = [s]
    for v in values[n:]:
        s = s - s / n + v
        out.append(s)
    return out


def ind_ema(c, cl):
    e20, e50, p = ema(cl, 20), ema(cl, 50), cl[-1]
    d = 1 if e20 > e50 and p > e20 else (-1 if e20 < e50 and p < e20 else 0)
    return d, ("EMA20 " + (">" if d > 0 else "<") + " EMA50") if d else None


def ind_rsi(c, cl, n=14):
    ag = sum(max(cl[i] - cl[i - 1], 0) for i in range(1, n + 1)) / n
    al = sum(max(cl[i - 1] - cl[i], 0) for i in range(1, n + 1)) / n
    for i in range(n + 1, len(cl)):
        d = cl[i] - cl[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
    r = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    d = 1 if r < 30 else (-1 if r > 70 else (1 if r < 45 else (-1 if r > 55 else 0)))
    return d, f"RSI {r:.0f}"


def ind_bollinger(c, cl, n=20, k=2):
    w = cl[-n:]
    mid = sum(w) / n
    sd = (sum((x - mid) ** 2 for x in w) / n) ** 0.5
    p = cl[-1]
    d = 1 if p <= mid - k * sd else (-1 if p >= mid + k * sd else 0)
    return d, ("Bollinger " + ("lower" if d > 0 else "upper")) if d else None


def ind_candles(c, cl):
    a, b = c[-2], c[-1]
    body, rng = abs(b["c"] - b["o"]), max(b["h"] - b["l"], 1e-12)
    lw, uw = min(b["o"], b["c"]) - b["l"], b["h"] - max(b["o"], b["c"])
    if a["c"] < a["o"] and b["c"] > b["o"] and b["c"] >= a["o"] and b["o"] <= a["c"]:
        return 1, "Bullish engulfing"
    if a["c"] > a["o"] and b["c"] < b["o"] and b["c"] <= a["o"] and b["o"] >= a["c"]:
        return -1, "Bearish engulfing"
    if lw > 2 * body and lw > 0.5 * rng:
        return 1, "Hammer"
    if uw > 2 * body and uw > 0.5 * rng:
        return -1, "Shooting star"
    return 0, None


def ind_levels(c, cl):
    w = c[-50:-1]
    lo, hi = min(x["l"] for x in w), max(x["h"] for x in w)
    pos = (cl[-1] - lo) / max(hi - lo, 1e-12)
    d = 1 if pos < 0.15 else (-1 if pos > 0.85 else 0)
    return d, ("Near " + ("support" if d > 0 else "resistance")) if d else None


def ind_macd(c, cl):
    e12, e26 = ema_series(cl, 12), ema_series(cl, 26)
    macd = [a - b for a, b in zip(e12[14:], e26)]
    sig = ema_series(macd, 9)
    m, s = macd[-1], sig[-1]
    d = 1 if m > s and m - s > 0 else (-1 if m < s else 0)
    return d, ("MACD " + ("bullish" if d > 0 else "bearish")) if d else None


def ind_stoch(c, cl, n=14):
    ks = []
    for i in range(len(c) - 3, len(c)):
        w = c[i - n + 1:i + 1]
        lo, hi = min(x["l"] for x in w), max(x["h"] for x in w)
        ks.append(100 * (c[i]["c"] - lo) / max(hi - lo, 1e-12))
    k, dl = ks[-1], sum(ks) / 3
    d = 1 if k < 20 and k > dl else (-1 if k > 80 and k < dl else (1 if k < 20 else (-1 if k > 80 else 0)))
    return d, f"Stoch {k:.0f}"


def ind_adx(c, cl, n=14):
    pdm, ndm = [], []
    for i in range(1, len(c)):
        up, dn = c[i]["h"] - c[i - 1]["h"], c[i - 1]["l"] - c[i]["l"]
        pdm.append(up if up > dn and up > 0 else 0)
        ndm.append(dn if dn > up and dn > 0 else 0)
    tr, p, m = wilder(true_ranges(c), n), wilder(pdm, n), wilder(ndm, n)
    pdi = [100 * a / max(t, 1e-12) for a, t in zip(p, tr)]
    ndi = [100 * a / max(t, 1e-12) for a, t in zip(m, tr)]
    dx = [100 * abs(a - b) / max(a + b, 1e-12) for a, b in zip(pdi, ndi)]
    adx = sum(dx[:n]) / n
    for v in dx[n:]:
        adx = (adx * (n - 1) + v) / n
    if adx < 20:
        return 0, None
    d = 1 if pdi[-1] > ndi[-1] else -1
    return d, f"ADX {adx:.0f} " + ("+DI" if d > 0 else "-DI")


def ind_cci(c, cl, n=20):
    tp = [(x["h"] + x["l"] + x["c"]) / 3 for x in c[-n:]]
    m = sum(tp) / n
    md = sum(abs(x - m) for x in tp) / n
    v = (tp[-1] - m) / max(0.015 * md, 1e-12)
    d = 1 if v < -100 else (-1 if v > 100 else 0)
    return d, f"CCI {v:.0f}" if d else None


def ind_williams(c, cl, n=14):
    w = c[-n:]
    lo, hi = min(x["l"] for x in w), max(x["h"] for x in w)
    r = -100 * (hi - cl[-1]) / max(hi - lo, 1e-12)
    d = 1 if r < -80 else (-1 if r > -20 else 0)
    return d, f"W%R {r:.0f}" if d else None


def ind_supertrend(c, cl, n=10, mult=3):
    tr = true_ranges(c)
    atr = sum(tr[:n]) / n
    up_band = dn_band = None
    trend = 1
    for i in range(n, len(c)):
        atr = (atr * (n - 1) + tr[i - 1]) / n
        hl2 = (c[i]["h"] + c[i]["l"]) / 2
        bu, bl = hl2 + mult * atr, hl2 - mult * atr
        if up_band is None:
            up_band, dn_band = bu, bl
        else:
            up_band = bu if bu < up_band or c[i - 1]["c"] > up_band else up_band
            dn_band = bl if bl > dn_band or c[i - 1]["c"] < dn_band else dn_band
        if c[i]["c"] > up_band:
            trend = 1
        elif c[i]["c"] < dn_band:
            trend = -1
    return trend, "Supertrend " + ("up" if trend > 0 else "down")


INDICATORS = {  # key: (الاسم, الوزن, الدالة)
    "ema": ("EMA 20/50", 12, ind_ema),
    "macd": ("MACD", 10, ind_macd),
    "adx": ("ADX / DMI", 10, ind_adx),
    "supertrend": ("Supertrend", 10, ind_supertrend),
    "rsi": ("RSI", 9, ind_rsi),
    "stoch": ("Stochastic", 9, ind_stoch),
    "cci": ("CCI", 8, ind_cci),
    "williams": ("Williams %R", 8, ind_williams),
    "bollinger": ("Bollinger", 8, ind_bollinger),
    "candles": ("Candles", 8, ind_candles),
    "levels": ("Support / Resistance", 8, ind_levels),
}


def analyze(pair, candles, strategies, tf, mode_label):
    cl = [x["c"] for x in candles]
    votes, reasons = [], []
    for key, (_, weight, fn) in INDICATORS.items():
        if not strategies.get(key):
            continue
        try:
            d, why = fn(candles, cl)
        except Exception:
            d, why = 0, None
        votes.append((d, weight))
        reasons.append((d, why))
    total = sum(w for _, w in votes) or 1
    signed = sum(d * w for d, w in votes) or 1e-9  # تعادل = بدون اتجاه، السكور يطلع منخفض
    reasons = [why for d, why in reasons if why and d and (d > 0) == (signed > 0)]
    agree = sum(w for d, w in votes if d and (d > 0) == (signed > 0))
    agreeing = sum(1 for d, _ in votes if d and (d > 0) == (signed > 0))
    return {
        "pair": pair, "direction": "UP" if signed > 0 else "DOWN",
        "score": round(100 * agree / total), "agree": f"{agreeing}/{len(votes)}",
        "price": round(cl[-1], 5), "timeframe": "1 min" if tf == 60 else "5 min",
        "reasons": reasons[:6], "data_mode": mode_label, "candle_time": candles[-1]["t"],
    }


# ---------------- الحالة ----------------
state = {
    "running": False, "status": "Ready", "mode": "otc", "source": SOURCES["otc"],
    "timeframe": 300, "min_score": 65,
    "strategies": {k: True for k in INDICATORS},
    "indicator_names": {k: v[0] for k, v in INDICATORS.items()},
    "last_scan": None, "next_scan": None, "opportunities": [], "closest": [],
    "scanned": 0, "failed": 0, "market_open": None,
    "otc_pairs": [], "quota_text": None, "budget_note": None,
}

# ---------------- مصدر OTC ----------------
_otc_client = None
_usage = {"remaining": None, "quota": None, "resets": 0, "plan": ""}


def otc_client():
    global _otc_client
    if otcharts is None:
        raise RuntimeError("otcharts library not installed")
    if _otc_client is None:
        _otc_client = otcharts.Client(timeout=15)
    return _otc_client


def refresh_usage():
    """مجانية — ما تنحسب من الطلبات."""
    try:
        u = otc_client().usage()
        _usage.update(remaining=u.remaining, quota=u.quota, resets=u.resets, plan=u.plan_name or u.plan)
        with lock:
            state["quota_text"] = f"{u.remaining} of {u.quota} requests left ({_usage['plan']})"
    except Exception:
        with lock:
            state["quota_text"] = ""


def pretty(sym):
    base = sym.replace("#", "").replace("_otc", "")
    if len(base) == 6 and base.isalpha():
        base = base[:3] + "/" + base[3:]
    return base + " OTC"


def otc_pairs():
    with lock:
        if state["otc_pairs"]:
            return list(state["otc_pairs"])
    syms = [i.symbol for i in otc_client().symbols("otc")]
    fx = [s for s in syms if not s.startswith("#")]  # العملات أول، بعدها الباقي
    pairs = (fx + [s for s in syms if s.startswith("#")])[:MAX_OTC_PAIRS]
    with lock:
        state["otc_pairs"] = pairs
    return pairs


def fetch_otc(sym, tf):
    bars = otc_client().candles("otc", sym, tf=tf, limit=CANDLES)
    return [{"t": b.time - PO_CLOCK_OFFSET, "o": b.open, "h": b.high, "l": b.low, "c": b.close} for b in bars]


# ---------------- مصدر السوق الحقيقي ----------------
def fetch_real(symbol, tf):
    interval, rng = ("1m", "1d") if tf == 60 else ("5m", "5d")
    err = None
    for host in ("query1", "query2"):
        url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{symbol}?interval={interval}&range={rng}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                res = json.load(r)["chart"]["result"][0]
            q = res["indicators"]["quote"][0]
            return [{"t": t, "o": o, "h": h, "l": l, "c": c}
                    for t, o, h, l, c in zip(res["timestamp"], q["open"], q["high"], q["low"], q["close"])
                    if None not in (o, h, l, c)]
        except Exception as e:
            err = e
    raise RuntimeError(err)


# ---------------- المسح ----------------
def scan():
    with lock:
        tf, strategies, min_score, mode = state["timeframe"], dict(state["strategies"]), state["min_score"], state["mode"]
    if not any(strategies.values()):
        with lock:
            state["opportunities"], state["status"] = [], "Select at least one indicator"
        return

    if mode == "otc":
        items = [(pretty(s), s) for s in otc_pairs()]
        fetch, label, workers = fetch_otc, "POCKET OTC · LIVE", 3
    else:
        items = list(REAL_PAIRS.items())
        fetch, label, workers = fetch_real, "REAL MARKET · LIVE", 6

    fatal = []

    def one(item):
        name, sym = item
        try:
            candles = fetch(sym, tf)
            if len(candles) < 60:
                return None
            return analyze(name, candles, strategies, tf, label)
        except Exception as e:
            if otcharts and isinstance(e, (otcharts.QuotaExceeded, otcharts.AuthError)):
                fatal.append(e)
            return None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(one, items))
    if fatal:
        raise fatal[0]

    ok = [r for r in results if r]
    now = time.time()
    fresh = [r for r in ok if now - r["candle_time"] < STALE_SECONDS] if mode == "real" else ok
    ranked = sorted(fresh, key=lambda r: r["score"], reverse=True)
    best = [r for r in ranked if r["score"] >= min_score][:3]
    with lock:
        state["opportunities"] = best
        state["closest"] = [] if best else ranked[:3]
        state["scanned"] = len(ok)
        state["failed"] = results.count(None)
        state["market_open"] = (bool(fresh) if ok else None) if mode == "real" else True
        state["last_scan"] = datetime.now(timezone.utc).isoformat()
        if mode == "real" and ok and not fresh:
            state["status"] = "Market closed — switch to Pocket Option OTC"
        elif not ok:
            state["status"] = "No data returned — retrying next scan"
        else:
            state["status"] = f"Scanning automatically — {len(ok)}/{len(items)} pairs read"


def next_interval(mode, tf, now):
    """متى المسح الجاي. بعد إغلاق الشمعة مباشرة، ومع OTC يوزّع الطلبات الباقية."""
    next_bar = (math.floor(now / tf) + 1) * tf + 3
    if mode != "otc":
        return next_bar, None
    refresh_usage()
    n = max(1, len(state["otc_pairs"]) or 5)
    remaining, resets = _usage["remaining"], _usage["resets"]
    if remaining is None:
        return next_bar, None
    window = max(resets - now, 3600) if resets else 86400
    scans_left = remaining // n
    if scans_left < 1:
        return resets or now + 3600, "Requests used up — resumes when the quota resets"
    spacing = window / scans_left
    if spacing <= tf:
        return next_bar, None
    note = f"Quota allows one scan every {format_gap(spacing)} — upgrade the plan for faster scans"
    return now + spacing, note


def format_gap(sec):
    sec = int(sec)
    if sec >= 3600:
        return f"{sec // 3600}h {sec % 3600 // 60}m"
    return f"{sec // 60}m"


def loop():
    while True:
        with lock:
            running, mode, tf = state["running"], state["mode"], state["timeframe"]
            due = state["next_scan"]
        now = time.time()
        if running and (due is None or now >= due):
            try:
                scan()
            except Exception as e:
                msg = str(e)
                if otcharts and isinstance(e, otcharts.QuotaExceeded):
                    msg = "Requests used up — upgrade to API Lite or switch to Real market"
                elif (otcharts and isinstance(e, otcharts.AuthError)) or "API key" in msg:
                    msg = "OTCharts key missing or invalid — set OTCHARTS_API_KEY in Railway"
                with lock:
                    state["status"] = msg
            nxt, note = next_interval(mode, tf, time.time())
            with lock:
                state["next_scan"], state["budget_note"] = nxt, note
        wake.wait(2)
        wake.clear()


Thread(target=loop, daemon=True).start()


# ---------------- الواجهة ----------------
@app.get("/")
def home():
    return render_template("index.html")


@app.get("/api/status")
def status():
    with lock:
        need = state["mode"] == "otc" and state["quota_text"] is None and bool(os.getenv("OTCHARTS_API_KEY"))
    if need:
        refresh_usage()
    with lock:
        return jsonify(state)


@app.post("/api/config")
def config():
    d = request.get_json(silent=True) or {}
    with lock:
        if d.get("mode") in SOURCES and d["mode"] != state["mode"]:
            state.update(mode=d["mode"], source=SOURCES[d["mode"]], opportunities=[], closest=[], last_scan=None,
                         next_scan=None, budget_note=None)
        if "timeframe" in d and int(d["timeframe"]) in (60, 300) and int(d["timeframe"]) != state["timeframe"]:
            state["timeframe"], state["next_scan"] = int(d["timeframe"]), None
        if "min_score" in d:
            state["min_score"] = max(40, min(100, int(d["min_score"])))
        if isinstance(d.get("strategies"), dict):
            for k in state["strategies"]:
                if k in d["strategies"]:
                    state["strategies"][k] = bool(d["strategies"][k])
    return jsonify({"ok": True})


@app.post("/api/start")
def start():
    with lock:
        state.update(running=True, status="Starting…", next_scan=None)
    wake.set()
    return jsonify({"ok": True})


@app.post("/api/stop")
def stop():
    with lock:
        state.update(running=False, status="Stopped", next_scan=None, budget_note=None)
    return jsonify({"ok": True})


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
