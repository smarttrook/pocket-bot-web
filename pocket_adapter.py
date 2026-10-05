import os
import threading
import time
from typing import Optional


class PocketAdapter:
    def __init__(self):
        self._lock = threading.RLock()
        self.api = None
        self.thread = None
        self.stop_event = threading.Event()
        self.running = False
        self.connected = False
        self.asset = None
        self.price = None
        self.balance = None
        self.payout = None
        self.last_tick_at = None
        self.error = None

    def _ssid(self) -> str:
        return os.getenv("PO_SSID", "").strip()

    def start(self, asset: str, period: int = 60):
        with self._lock:
            if self.running:
                return
            ssid = self._ssid()
            if not ssid:
                raise RuntimeError("PO_SSID is not configured in Railway Variables")
            # Safety gate: this build is demo-only.
            compact = ssid.replace(" ", "").lower()
            if '"isdemo":1' not in compact and '"isdemo":true' not in compact:
                raise RuntimeError("Demo-only safety lock: PO_SSID must be from a Demo account")
            self.running = True
            self.connected = False
            self.asset = asset
            self.error = None
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._run, args=(asset, int(period)), daemon=True)
            self.thread.start()

    def stop(self):
        with self._lock:
            self.running = False
            self.stop_event.set()
            api = self.api
            self.connected = False
        if api:
            try:
                api.disconnect_websocket()
            except Exception:
                pass

    def _run(self, asset: str, period: int):
        try:
            from pocketoptionapi import PocketOption

            ssid = self._ssid()
            api = PocketOption(ssid)
            with self._lock:
                self.api = api

            ok, err = api.connect()
            if not ok:
                raise RuntimeError(err or "Pocket Option connection failed")

            deadline = time.time() + 35
            while time.time() < deadline and not self.stop_event.is_set():
                if api.check_connect():
                    break
                time.sleep(0.25)
            if not api.check_connect():
                raise RuntimeError("Pocket Option WebSocket did not become ready")

            api.subscribe(asset, period=period)
            with self._lock:
                self.connected = True

            while not self.stop_event.wait(1.0):
                if not api.check_connect():
                    with self._lock:
                        self.connected = False
                        self.error = "Pocket Option WebSocket disconnected"
                    break

                ticks = api.get_realtime_ticks(asset, limit=1) or []
                price: Optional[float] = None
                if ticks:
                    tick = ticks[-1]
                    if isinstance(tick, (list, tuple)) and len(tick) >= 2:
                        price = float(tick[1])
                    elif isinstance(tick, dict):
                        raw = tick.get("price", tick.get("value"))
                        if raw is not None:
                            price = float(raw)

                balance = api.get_balance()
                payout = api.get_payout(asset)

                with self._lock:
                    self.connected = True
                    if price is not None:
                        self.price = price
                        self.last_tick_at = time.time()
                    if balance is not None:
                        self.balance = float(balance)
                    if payout is not None:
                        self.payout = float(payout)

        except Exception as exc:
            with self._lock:
                self.error = str(exc)
                self.connected = False
        finally:
            with self._lock:
                self.running = False
                self.connected = False

    def status(self):
        with self._lock:
            tick_age = None
            if self.last_tick_at:
                tick_age = round(time.time() - self.last_tick_at, 1)
            return {
                "running": self.running,
                "connected": self.connected,
                "asset": self.asset,
                "price": self.price,
                "balance": self.balance,
                "payout": self.payout,
                "tick_age": tick_age,
                "error": self.error,
                "demo_locked": True,
            }


pocket = PocketAdapter()
