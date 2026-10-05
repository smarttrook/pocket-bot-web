"""Trade Radar — يطلع أفضل 3 فرص بناءً على المؤشرات المختارة.
مصدرين للبيانات:
  otc  = أسعار Pocket Option OTC الحقيقية من OTCharts (مسح يدوي لتوفير الطلبات)
  real = أزواج السوق الحقيقي من Yahoo Finance (مسح تلقائي)"""
import json
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Lock, Thread

from flask import Flask, jsonify, render_template, request

try:
    import otcharts
except ImportError:  # المكتبة مو مثبتة
    otcharts = None

app = Flask(__name__)
lock = Lock()

# اسم الزوج في Pocket Option -> رمزه في Yahoo Finance
PAIRS = {
    "EUR/USD": "EURUSD=X", "GBP/USD": "GBPUSD=X", "USD/JPY": "JPY=X",
    "AUD/USD": "AUDUSD=X", "USD/CAD": "CAD=X", "USD/CHF": "CHF=X",
    "NZD/USD": "NZDUSD=X", "EUR/JPY": "EURJPY=X", "GBP/JPY": "GBPJPY=X",
    "EUR/GBP": "EURGBP=X", "AUD/JPY": "AUDJPY=X", "EUR/AUD": "EURAUD=X",
    "CAD/JPY": "CADJPY=X", "CHF/JPY": "CHFJPY=X", "AUD/CAD": "AUDCAD=X",
    "EUR/CHF": "EURCHF=X",
}
STALE_SECONDS = 20 * 60  # إذا آخر شمعة أقدم من 20 دقيقة = السوق مغلق

state = {
    "running": False, "status": "Ready", "timeframe": 300, "min_score": 75,
    "strategies": {"ema": True, "rsi": True, "bollinger": True, "candles": True, "levels": True},
    "last_scan": None, "opportunities": [], "scanned": 0, "failed": 0,
    "mode": "otc", "source": "", "market_open": None,
    "otc_pairs": [], "requests_left": None, "quota_text": None,
}

SOURCES = {
    "otc": "Pocket Option OTC — OTCharts (manual scan)",
    "real": "Real market — Yahoo Finance (auto scan, weekdays only)",
}
state["source"] = SOURCES["otc"]
PO_CLOCK_OFFSET = 7200  # Pocket Option يختم الشموع بتوقيت UTC+2


# ---------------- البيانات ----------------
def fetch_candles(symbol, timeframe):
    interval, rng = ("1m", "1d") if timeframe == 60 else ("5m", "5d")
    last_err = None
    for host in ("query1", "query2"):
        url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{symbol}?interval={interval}&range={rng}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.load(r)
            res = data["chart"]["result"][0]
            q = res["indicators"]["quote"][0]
            candles = [
                {"t": t, "o": o, "h": h, "l": l, "c": c}
                for t, o, h, l, c in zip(res["timestamp"], q["open"], q["high"], q["low"], q["close"])
                if None not in (o, h, l, c)
            ]
            if len(candles) >= 60:
                return candles
            last_err = "not enough candles"
        except Exception as e:  # جرّب السيرفر الثاني
            last_err = str(e)
    raise RuntimeError(last_err)


# ---------------- المؤشرات ----------------
def ema(values, n):
    k = 2 / (n + 1)
    e = sum(values[:n]) / n
    for v in values[n:]:
        e = v * k + e * (1 - k)
    return e


def rsi(closes, n=14):
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    ag, al = gains / n, losses / n
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)


def bollinger(closes, n=20, k=2):
    w = closes[-n:]
    mid = sum(w) / n
    sd = (sum((x - mid) ** 2 for x in w) / n) ** 0.5
    return mid - k * sd, mid, mid + k * sd


def analyze(pair, candles, strategies, timeframe):
    closes = [c["c"] for c in candles]
    price = closes[-1]
    votes, reasons = [], []  # (اتجاه -1/0/1, وزن)

    if strategies["ema"]:
        e20, e50 = ema(closes, 20), ema(closes, 50)
        d = 1 if e20 > e50 and price > e20 else (-1 if e20 < e50 and price < e20 else 0)
        votes.append((d, 28))
        if d: reasons.append("EMA20 " + (">" if d > 0 else "<") + " EMA50")

    if strategies["rsi"]:
        r = rsi(closes)
        d = 1 if r < 30 else (-1 if r > 70 else (1 if r < 45 else (-1 if r > 55 else 0)))
        votes.append((d, 20))
        reasons.append(f"RSI {r:.0f}")

    if strategies["bollinger"]:
        lo, mid, up = bollinger(closes)
        d = 1 if price <= lo else (-1 if price >= up else 0)
        votes.append((d, 16))
        if d: reasons.append("Bollinger " + ("lower" if d > 0 else "upper") + " band")

    if strategies["candles"]:
        a, b = candles[-2], candles[-1]
        bull_engulf = a["c"] < a["o"] and b["c"] > b["o"] and b["c"] >= a["o"] and b["o"] <= a["c"]
        bear_engulf = a["c"] > a["o"] and b["c"] < b["o"] and b["c"] <= a["o"] and b["o"] >= a["c"]
        body, rng = abs(b["c"] - b["o"]), max(b["h"] - b["l"], 1e-12)
        lower_wick = min(b["o"], b["c"]) - b["l"]
        upper_wick = b["h"] - max(b["o"], b["c"])
        if bull_engulf: d, name = 1, "Bullish engulfing"
        elif bear_engulf: d, name = -1, "Bearish engulfing"
        elif lower_wick > 2 * body and lower_wick > 0.5 * rng: d, name = 1, "Hammer"
        elif upper_wick > 2 * body and upper_wick > 0.5 * rng: d, name = -1, "Shooting star"
        else: d, name = 0, None
        votes.append((d, 20))
        if name: reasons.append(name)

    if strategies["levels"]:
        window = candles[-50:-1]
        support = min(c["l"] for c in window)
        resist = max(c["h"] for c in window)
        span = max(resist - support, 1e-12)
        pos = (price - support) / span
        d = 1 if pos < 0.15 else (-1 if pos > 0.85 else 0)
        votes.append((d, 16))
        if d: reasons.append("Near " + ("support" if d > 0 else "resistance"))

    total = sum(w for _, w in votes) or 1
    signed = sum(d * w for d, w in votes)
    agree = sum(w for d, w in votes if d != 0 and (d > 0) == (signed > 0))
    score = round(100 * agree / total) if signed else 0
    return {
        "pair": pair, "direction": "UP" if signed > 0 else "DOWN", "score": score,
        "price": round(price, 5), "timeframe": "1 min" if timeframe == 60 else "5 min",
        "reasons": reasons or ["No clear signal"], "data_mode": "LIVE DATA",
        "candle_time": candles[-1]["t"],
    }



# ---------------- Pocket Option OTC (OTCharts) ----------------
_otc_client = None
_otc_cache = {"time": 0, "tf": None, "strategies": None, "results": None}


def otc_client():
    global _otc_client
    if otcharts is None:
        raise RuntimeError("otcharts library not installed")
    if _otc_client is None:
        _otc_client = otcharts.Client(timeout=15)  # يقرأ OTCHARTS_API_KEY
    return _otc_client


def refresh_usage():
    """مجانية — ما تنحسب من الطلبات."""
    try:
        u = otc_client().usage()
        with lock:
            state["requests_left"] = u.remaining
            state["quota_text"] = f"{u.remaining} of {u.quota} requests left ({u.plan_name or u.plan})"
    except Exception:
        with lock:
            state["quota_text"] = ""


def otc_pairs():
    """قائمة الأزواج المفتوحة لمفتاحك. تنطلب مرة وحدة بس (تكلف طلب واحد)."""
    with lock:
        cached = list(state["otc_pairs"])
    if cached:
        return cached
    pairs = [i.symbol for i in otc_client().symbols("otc")]
    with lock:
        state["otc_pairs"] = pairs
    return pairs


def pretty(symbol):
    base = symbol.replace("#", "").replace("_otc", "")
    if len(base) == 6 and base.isalpha():
        base = base[:3] + "/" + base[3:]
    return base + " OTC"


def scan_otc(tf, strategies, min_score):
    now = time.time()
    # نفس الشمعة ما تغيّرت = لا تصرف طلبات على نفس الجواب
    if (_otc_cache["results"] is not None and _otc_cache["tf"] == tf
            and _otc_cache["strategies"] == strategies and now - _otc_cache["time"] < tf):
        results = _otc_cache["results"]
    else:
        client = otc_client()
        results = []
        for sym in otc_pairs():
            try:
                bars = client.candles("otc", sym, tf=tf, limit=120)
                candles = [{"t": b.time - PO_CLOCK_OFFSET, "o": b.open, "h": b.high,
                            "l": b.low, "c": b.close} for b in bars]
                if len(candles) >= 60:
                    r = analyze(pretty(sym), candles, strategies, tf)
                    r["data_mode"] = "POCKET OTC · LIVE"
                    results.append(r)
            except otcharts.QuotaExceeded:
                raise
            except otcharts.AuthError:
                raise
            except Exception:
                continue
        _otc_cache.update(time=now, tf=tf, strategies=strategies, results=results)

    best = sorted((r for r in results if r["score"] >= min_score),
                  key=lambda r: r["score"], reverse=True)[:3]
    with lock:
        state["opportunities"] = best
        state["scanned"] = len(results)
        state["failed"] = max(0, len(state["otc_pairs"]) - len(results))
        state["market_open"] = True
        state["last_scan"] = datetime.now(timezone.utc).isoformat()
        state["status"] = "Scan done — press SCAN again for a fresh read" if results else "No OTC data returned"
    refresh_usage()

# ---------------- المسح (السوق الحقيقي) ----------------
def scan():
    with lock:
        tf, strategies, min_score = state["timeframe"], dict(state["strategies"]), state["min_score"]
        mode = state["mode"]
    if not any(strategies.values()):
        with lock:
            state["opportunities"], state["status"] = [], "Select at least one indicator"
        return
    if mode == "otc":
        try:
            scan_otc(tf, strategies, min_score)
        except Exception as e:
            msg = str(e)
            if otcharts and isinstance(e, otcharts.QuotaExceeded):
                msg = "Free OTCharts requests used up — upgrade to API Lite or switch to Real market"
            elif otcharts and isinstance(e, otcharts.AuthError) or "API key" in msg or "OTCHARTS_API_KEY" in msg:
                msg = "OTCharts key missing or invalid — set OTCHARTS_API_KEY in Railway Variables"
            with lock:
                state["status"], state["running"] = msg, False
        return
    scan_real(tf, strategies, min_score)


def scan_real(tf, strategies, min_score):
    def one(item):
        pair, sym = item
        try:
            return analyze(pair, fetch_candles(sym, tf), strategies, tf)
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(one, PAIRS.items()))

    ok = [r for r in results if r]
    now = time.time()
    fresh = [r for r in ok if now - r["candle_time"] < STALE_SECONDS]
    best = sorted((r for r in fresh if r["score"] >= min_score), key=lambda r: r["score"], reverse=True)[:3]

    with lock:
        state["opportunities"] = best
        state["scanned"] = len(ok)
        state["failed"] = len(results) - len(ok)
        state["market_open"] = bool(fresh) if ok else None
        state["last_scan"] = datetime.now(timezone.utc).isoformat()
        if not ok:
            state["status"] = "Data feed error — retrying"
        elif not fresh:
            state["status"] = "Market closed (weekend / OTC only)"
        elif state["running"]:
            state["status"] = "Scanning"


def loop():
    while True:
        if state["running"] and state["mode"] == "real":
            try:
                scan()
            except Exception as e:
                with lock:
                    state["status"] = f"Scan error: {e}"
        time.sleep(30 if state["timeframe"] == 60 else 60)


Thread(target=loop, daemon=True).start()


# ---------------- الواجهة ----------------
@app.get("/")
def home():
    return render_template("index.html")


@app.get("/api/status")
def status():
    with lock:
        if state["mode"] == "otc" and state["quota_text"] is None and os.getenv("OTCHARTS_API_KEY"):
            need_usage = True
        else:
            need_usage = False
    if need_usage:
        refresh_usage()
    with lock:
        return jsonify(state)


@app.post("/api/config")
def config():
    d = request.get_json(silent=True) or {}
    with lock:
        if "timeframe" in d and int(d["timeframe"]) in (60, 300):
            state["timeframe"] = int(d["timeframe"])
        if "min_score" in d:
            state["min_score"] = max(50, min(100, int(d["min_score"])))
        if d.get("mode") in SOURCES and d["mode"] != state["mode"]:
            state["mode"] = d["mode"]
            state["source"] = SOURCES[d["mode"]]
            state["running"], state["opportunities"], state["last_scan"] = False, [], None
            state["status"] = "Ready"
        if isinstance(d.get("strategies"), dict):
            for k in state["strategies"]:
                if k in d["strategies"]:
                    state["strategies"][k] = bool(d["strategies"][k])
    return jsonify({"ok": True})


@app.post("/api/start")
def start():
    with lock:
        one_shot = state["mode"] == "otc"
        state["running"], state["status"] = (not one_shot), "Scanning"
    scan()
    return jsonify({"ok": True})


@app.post("/api/stop")
def stop():
    with lock:
        state["running"], state["status"] = False, "Stopped"
    return jsonify({"ok": True})


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
