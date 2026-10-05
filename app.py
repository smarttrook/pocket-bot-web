from flask import Flask, jsonify, render_template, request
from threading import Lock, Thread
from datetime import datetime, timezone
import os, time, random
app=Flask(__name__); lock=Lock()
PAIRS=["EUR/USD","GBP/USD","USD/JPY","AUD/USD","USD/CAD","EUR/JPY","GBP/JPY","EUR/GBP"]
state={"running":False,"status":"Ready","timeframe":300,"min_score":75,"strategies":{"ema":True,"rsi":True,"bollinger":True,"candles":True,"levels":True},"last_scan":None,"opportunities":[],"scanned":0,"source":"Scanner ready — live market feed not connected yet"}
def score(pair):
 r=random.Random(sum(map(ord,pair))+int(time.time()//300)); a,b,rsi,bb,candle,level=[r.uniform(-1,1),r.uniform(-1,1),r.uniform(25,75),r.uniform(-1,1),r.uniform(-1,1),r.uniform(-1,1)]; v=[]; reasons=[]; s=state["strategies"]
 if s["ema"]: v.append((1 if a>b else -1,28)); reasons.append("EMA trend")
 if s["rsi"]: v.append((1 if rsi<48 else (-1 if rsi>52 else 0),20)); reasons.append(f"RSI {rsi:.0f}")
 if s["bollinger"]: v.append((1 if bb<-.15 else (-1 if bb>.15 else 0),16)); reasons.append("Bollinger")
 if s["candles"]: v.append((1 if candle>.12 else (-1 if candle<-.12 else 0),20)); reasons.append("Candles")
 if s["levels"]: v.append((1 if level>.15 else (-1 if level<-.15 else 0),16)); reasons.append("S/R levels")
 signed=sum(x*w for x,w in v); total=max(1,sum(w for _,w in v))
 return {"pair":pair,"direction":"UP" if signed>=0 else "DOWN","score":round(50+50*abs(signed)/total),"timeframe":"5 min" if state["timeframe"]==300 else "1 min","reasons":reasons[:3],"data_mode":"SIMULATION"}
def scan():
 x=sorted([score(p) for p in PAIRS],key=lambda q:q["score"],reverse=True)
 with lock: state["opportunities"]=[q for q in x if q["score"]>=state["min_score"]][:3]; state["scanned"]=len(x); state["last_scan"]=datetime.now(timezone.utc).isoformat()
def loop():
 while True:
  if state["running"]: scan()
  time.sleep(15)
Thread(target=loop,daemon=True).start()
@app.get("/")
def home(): return render_template("index.html")
@app.get("/api/status")
def status(): return jsonify(state)
@app.post("/api/config")
def config():
 d=request.get_json(silent=True) or {}
 with lock:
  if "timeframe" in d: state["timeframe"]=int(d["timeframe"])
  if "min_score" in d: state["min_score"]=max(50,min(100,int(d["min_score"])))
  if isinstance(d.get("strategies"),dict):
   for k in state["strategies"]:
    if k in d["strategies"]: state["strategies"][k]=bool(d["strategies"][k])
 return jsonify({"ok":True,"state":state})
@app.post("/api/start")
def start(): state["running"]=True; state["status"]="Scanning"; scan(); return jsonify({"ok":True,"state":state})
@app.post("/api/stop")
def stop(): state["running"]=False; state["status"]="Stopped"; return jsonify({"ok":True,"state":state})
@app.get("/health")
def health(): return jsonify({"status":"ok"})
if __name__=="__main__": app.run(host="0.0.0.0",port=int(os.getenv("PORT","8080")))
