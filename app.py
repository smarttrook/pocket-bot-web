from flask import Flask, jsonify, render_template, request
from threading import Lock
from datetime import datetime, timezone
import os

from pocket_adapter import pocket

app = Flask(__name__)
lock = Lock()

state = {
    "running": False,
    "connected": False,
    "mode": "demo",
    "asset": "EURUSD_otc",
    "timeframe": 60,
    "amount": 1.0,
    "min_payout": 80,
    "take_profit": 10.0,
    "stop_loss": 10.0,
    "martingale": "1,2,4,8",
    "wins": 0,
    "losses": 0,
    "profit": 0.0,
    "status": "Ready - Demo safety lock",
    "price": None,
    "balance": None,
    "payout": None,
    "error": None,
}


def current_state():
    live = pocket.status()
    with lock:
        state["running"] = live["running"]
        state["connected"] = live["connected"]
        state["price"] = live["price"]
        state["balance"] = live["balance"]
        state["payout"] = live["payout"]
        state["error"] = live["error"]
        if live["connected"]:
            state["status"] = "Connected to Pocket Option DEMO"
        elif live["running"]:
            state["status"] = "Connecting to Pocket Option..."
        elif live["error"]:
            state["status"] = "Connection error"
        return dict(state)


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/api/status")
def status():
    return jsonify(current_state())


@app.post("/api/config")
def config():
    data = request.get_json(silent=True) or {}
    if data.get("mode", "demo") != "demo":
        return jsonify({"ok": False, "error": "This build is locked to Demo mode"}), 400

    allowed = {"asset", "timeframe", "amount", "min_payout", "take_profit", "stop_loss", "martingale"}
    with lock:
        state["mode"] = "demo"
        for key in allowed:
            if key in data:
                state[key] = data[key]
    return jsonify({"ok": True, "state": current_state()})


@app.post("/api/start")
def start():
    with lock:
        asset = state["asset"]
        timeframe = int(state["timeframe"])
    try:
        pocket.start(asset, timeframe)
        return jsonify({"ok": True, "state": current_state()})
    except Exception as exc:
        with lock:
            state["error"] = str(exc)
            state["status"] = "Configuration error"
        return jsonify({"ok": False, "error": str(exc), "state": current_state()}), 400


@app.post("/api/stop")
def stop():
    pocket.stop()
    with lock:
        state["status"] = "Stopped"
    return jsonify({"ok": True, "state": current_state()})


@app.get("/health")
def health():
    return jsonify({"status": "ok", "time": datetime.now(timezone.utc).isoformat()})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
