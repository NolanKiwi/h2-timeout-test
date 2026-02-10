# backend/app/main.py
from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
import time
import sys
import os

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
    h2_proc: asyncio.subprocess.Process = None # Changed to async process
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
    interface: str = "any"

# --- API ---

@app.post("/api/run")
async def start_run(config: RunConfig):
    if state.running:
        raise HTTPException(status_code=400, detail="Experiment already running")
    
    state.running = True
    state.run_id = str(int(time.time()))
    state.start_time = time.time()
    
    try:
        # Start H2 Client using asyncio
        # -u: Force stdout and stderr to be unbuffered
        cmd_h2 = [
            sys.executable, "-u", "app/h2_simulate.py",
            "--host", config.host,
            "--port", str(config.port),
            "--path", config.path,
            "--delay", str(config.delay),
            "--start-after-bytes", str(config.start_after_bytes),
            "--ping-interval", str(config.ping_interval)
        ]
        if config.ip:
            cmd_h2.extend(["--ip", config.ip])
            
        state.h2_proc = await asyncio.create_subprocess_exec(
            *cmd_h2,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )
        
        return {"run_id": state.run_id, "status": "started"}
        
    except Exception as e:
        state.running = False
        await stop_processes()
        raise HTTPException(status_code=500, detail=str(e))

async def stop_processes():
    if state.h2_proc:
        try:
            state.h2_proc.terminate()
            try:
                await asyncio.wait_for(state.h2_proc.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                state.h2_proc.kill()
        except Exception:
            pass # Already dead or error
    state.h2_proc = None

@app.post("/api/stop")
async def stop_run():
    if not state.running:
        return {"status": "not_running"}
    
    await stop_processes()
    state.running = False
    return {"status": "stopped", "run_id": state.run_id}

@app.get("/api/status")
async def get_status():
    return {
        "running": state.running,
        "run_id": state.run_id,
        "elapsed": time.time() - state.start_time if state.running else 0
    }

# --- WebSockets for Logs ---

@app.websocket("/ws/h2")
async def websocket_h2_logs(websocket: WebSocket):
    await websocket.accept()
    if not state.h2_proc:
        await websocket.close()
        return

    try:
        # Read line by line asynchronously
        while True:
            if state.h2_proc.stdout.at_eof():
                break
                
            line = await state.h2_proc.stdout.readline()
            if line:
                await websocket.send_text(line.decode('utf-8'))
            else:
                break
    except Exception as e:
        print(f"WS H2 Error: {e}")
    finally:
        await websocket.close()
