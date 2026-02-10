# backend/app/main.py (FastAPI skeleton)
from fastapi import FastAPI, WebSocket, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
import subprocess
import os
import signal
import time
import logging

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- State ---
class ExperimentState:
    running: bool = False
    run_id: str = None
    h2_proc: subprocess.Popen = None
    tcpdump_proc: subprocess.Popen = None
    start_time: float = 0
    
state = ExperimentState()

# --- Models ---
class RunConfig(BaseModel):
    host: str
    ip: str = None
    port: int = 443
    path: str = "/"
    delay: float = 0.0
    start_after_bytes: int = 0
    ping_interval: float = 0.0
    interface: str = "eth0"

# --- Utils ---
def resolve_ip(host: str):
    try:
        return socket.gethostbyname(host)
    except:
        return None

# --- API ---

@app.post("/api/run")
async def start_run(config: RunConfig):
    if state.running:
        raise HTTPException(status_code=400, detail="Experiment already running")
    
    state.running = True
    state.run_id = str(int(time.time()))
    state.start_time = time.time()
    
    # 1. Start tcpdump
    pcap_file = f"/app/captures/{state.run_id}.pcap"
    bpf = f"host {config.ip or config.host} and port {config.port}"
    
    # Text output tcpdump
    cmd_tcpdump_text = [
        "tcpdump", "-i", config.interface, "-n", "-tt", "-vv", "-l",
        bpf
    ]
    # PCAP capture tcpdump (background)
    cmd_tcpdump_pcap = [
        "tcpdump", "-i", config.interface, "-n", "-U", "-w", pcap_file,
        bpf
    ]
    
    try:
        # Start PCAP process
        state.tcpdump_proc = subprocess.Popen(cmd_tcpdump_pcap)
        
        # Start H2 Client
        cmd_h2 = [
            "python3", "app/h2_simulate.py",
            "--host", config.host,
            "--port", str(config.port),
            "--path", config.path,
            "--delay", str(config.delay),
            "--start-after-bytes", str(config.start_after_bytes),
            "--ping-interval", str(config.ping_interval)
        ]
        if config.ip:
            cmd_h2.extend(["--ip", config.ip])
            
        state.h2_proc = subprocess.Popen(
            cmd_h2,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1 # Line buffered
        )
        
        return {"run_id": state.run_id, "status": "started"}
        
    except Exception as e:
        state.running = False
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/stop")
async def stop_run():
    if not state.running:
        return {"status": "not_running"}
    
    if state.h2_proc:
        state.h2_proc.terminate()
        try:
            state.h2_proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            state.h2_proc.kill()
            
    if state.tcpdump_proc:
         state.tcpdump_proc.terminate()
         try:
            state.tcpdump_proc.wait(timeout=2)
         except:
            state.tcpdump_proc.kill()

    state.running = False
    return {"status": "stopped", "run_id": state.run_id}

# --- WebSockets for Logs ---

@app.websocket("/ws/h2")
async def websocket_h2_logs(websocket: WebSocket):
    await websocket.accept()
    if not state.h2_proc:
        await websocket.close()
        return

    try:
        # Simple loop to read stdout line by line
        # In production, use asyncio.create_subprocess_exec for better async streaming
        for line in iter(state.h2_proc.stdout.readline, ''):
            if line:
                await websocket.send_text(line)
            else:
                break
    except Exception as e:
        print(f"WS Error: {e}")
    finally:
        await websocket.close()

# Note: This is a simplified, synchronous implementation sketch. 
# Real-time streaming requires async subprocess handling or threads.
