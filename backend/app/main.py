# backend/app/main.py (continued)

# ... (Previous imports and setup)

# Add PCAP download endpoint
from fastapi.responses import FileResponse

@app.get("/api/pcap")
async def get_pcap(run_id: str):
    pcap_path = f"/app/captures/{run_id}.pcap"
    if not os.path.exists(pcap_path):
        raise HTTPException(status_code=404, detail="PCAP not found")
    return FileResponse(pcap_path, media_type="application/vnd.tcpdump.pcap", filename=f"run_{run_id}.pcap")

# Add Status endpoint
@app.get("/api/status")
async def get_status():
    return {
        "running": state.running,
        "run_id": state.run_id,
        "elapsed": time.time() - state.start_time if state.running else 0
    }

# Implement WebSocket streaming for tcpdump
@app.websocket("/ws/tcpdump")
async def websocket_tcpdump_logs(websocket: WebSocket):
    await websocket.accept()
    if not state.tcpdump_proc:
        await websocket.close()
        return

    try:
        # Stream tcpdump stdout
        # Note: tcpdump with -l buffers line by line
        for line in iter(state.tcpdump_proc.stdout.readline, ''):
            if line:
                await websocket.send_text(line)
            else:
                break
    except Exception as e:
        print(f"WS TCP Error: {e}")
    finally:
        await websocket.close()
