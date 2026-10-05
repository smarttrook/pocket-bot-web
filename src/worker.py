from flask import Flask, Response, jsonify, request
from pyodide.ffi import run_sync
from workers import wsgi

app = Flask(__name__)

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

    for key in allowed:
        if key in data:
            state[key] = data[key]

    return jsonify({
        "ok": True,
        "state": state
    })


@app.post("/api/start")
def start():
    state["running"] = True
    state["status"] = "Running"

    return jsonify({
        "ok": True,
        "state": state
    })


@app.post("/api/stop")
def stop():
    state["running"] = False
    state["status"] = "Stopped"

    return jsonify({
        "ok": True,
        "state": state
    })


@app.get("/health")
def health():
    return jsonify({
        "status": "ok"
    })


@app.get("/")
@app.get("/<path:path>")
def frontend(path=""):
    assets = request.environ["workers.env"].ASSETS

    if not path:
        path = "index.html"

    asset_response = run_sync(
        assets.fetch(f"https://assets.local/{path}")
    )

    body = run_sync(asset_response.bytes())

    return Response(
        body,
        status=asset_response.status,
        headers=asset_response.headers
    )


Default = wsgi.entrypoint(app)
