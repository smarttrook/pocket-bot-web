from flask import Flask, jsonify, render_template, request
from threading import Lock
from datetime import datetime, timezone
import os

app = Flask(__name__)
lock = Lock()

state = {
    "running": False,
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
    "status": "Ready"
}


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/api/status")
def status():
    return jsonify(state)


@app.post("/api/config")
def config():
    data = request.get_json(silent=True) or {}

    allowed = {
        "mode",
        "asset",
        "timeframe",
        "amount",
        "min_payout",
        "take_profit",
        "stop_loss",
        "martingale"
    }

    with lock:
        for key in allowed:
            if key in data:
                state[key] = data[key]

    return jsonify({
        "ok": True,
        "state": state
    })


@app.post("/api/start")
def start():
    with lock:
        state["running"] = True
        state["status"] = "Running (execution adapter not connected)"

    return jsonify({
        "ok": True,
        "state": state
    })


@app.post("/api/stop")
def stop():
    with lock:
        state["running"] = False
        state["status"] = "Stopped"

    return jsonify({
        "ok": True,
        "state": state
    })


@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "time": datetime.now(timezone.utc).isoformat()
    })


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080"))
    )
