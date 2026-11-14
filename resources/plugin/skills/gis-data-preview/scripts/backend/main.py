import json
import os
import sys
import webbrowser
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# 脚本目录（scripts/），用于 static 文件和 sibling imports
SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


# Claude Code 启动时所在目录（cwd），前后端统一以此作为路径基准
PROJECT_ROOT = Path.cwd()


from backend.schemas import LayerLoadRequest
from backend.ws_manager import ws_manager

app = FastAPI(title="LinkTool GIS Visualizer")

# --- Static files -----------------------------------------------------------
static_dir = SCRIPTS_DIR / "static"
if not static_dir.exists():
    static_dir.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# SPA fallback: serve index.html for root
@app.get("/")
async def serve_index():
    return FileResponse(str(static_dir / "index.html"))


# --- POST endpoint: agent pushes GeoJSON path --------------------------------
@app.post("/api/layers")
async def load_layer(req: LayerLoadRequest):
    # Resolve path relative to project root and prevent path traversal
    geojson_path = (req.geojson_path).resolve()
    if not geojson_path.exists():
        return {"ok": False, "error": f"File not found: {geojson_path}"}

    try:
        raw = geojson_path.read_text(encoding="utf-8")
        geojson = json.loads(raw)
    except Exception as e:
        return {"ok": False, "error": f"Failed to read/parse GeoJSON: {e}"}

    # Build broadcast payload
    payload = {
        **geojson,
        "_layer_name": req.layer_name,
        "_renderer": req.renderer.model_dump(),
    }

    # Push to all connected browsers
    await ws_manager.broadcast(payload)

    return {"ok": True, "layer_name": req.layer_name, "connections": ws_manager.connection_count}


# --- WebSocket endpoint: browsers listen here --------------------------------
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)
    except Exception:
        ws_manager.disconnect(ws)


# --- Launch browser after startup --------------------------------------------
@app.on_event("startup")
def open_browser():
    url = "http://localhost:3003"
    # Delay slightly so the server is ready
    import threading
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()


# --- Entry point -------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=3003,
        reload=False,
        ws_ping_interval=20,   # 服务端每20秒发送一次 WebSocket ping
        ws_ping_timeout=60,    # 60秒内没收到pong才断开
    )
