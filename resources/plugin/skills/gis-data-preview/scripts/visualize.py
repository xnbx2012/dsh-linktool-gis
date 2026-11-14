import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

# 脚本所在目录（scripts/）
SCRIPTS_DIR = Path(__file__).resolve().parent                                                                    
VISUAL_ROOT = Path.cwd()                                                                         
                                                                                                                        
                                                                                                                        
# Claude Code 启动时所在目录
PROJECT_ROOT = Path.cwd()
GEOJSON_OUTPUT_DIR = PROJECT_ROOT / "02_WorkSpace" / "geojson"
GEOJSON_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SERVICE_URL = "http://localhost:3003"                                                                                 
PID_FILE = SCRIPTS_DIR / ".visual-web.pid"


def is_port_in_use(port):
      with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
          return s.connect_ex(("127.0.0.1", port)) == 0


def is_service_running():
      """检查服务是否在运行。"""
      if not is_port_in_use(3003):
          return False
      try:
          import urllib.request
          req = urllib.request.Request(SERVICE_URL, method="HEAD")
          with urllib.request.urlopen(req, timeout=2):
              return True
      except Exception:
          return False


def start_service():
      """启动可视化网页服务。"""
      if is_service_running():
          print("可视化服务已在运行中 (http://localhost:3003)")
          return


      # 启动 uvicorn 子进程
      proc = subprocess.Popen(
          [
              sys.executable, "-m", "uvicorn",
              "backend.main:app",
              "--host", "0.0.0.0",
              "--port", "3003",
              "--ws-ping-interval", "20",
              "--ws-ping-timeout", "60",
          ],
          cwd=str(VISUAL_ROOT),
          stdout=subprocess.DEVNULL,
          stderr=subprocess.DEVNULL,
          creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
      )

      # 记录 PID
      PID_FILE.write_text(str(proc.pid))

      # 等待服务就绪
      for _ in range(30):
          time.sleep(0.5)
          if is_service_running():
              print(f"可视化服务已启动 (PID: {proc.pid}) → http://localhost:3003")
              # 打开浏览器
              import webbrowser
              webbrowser.open(SERVICE_URL)
              return

      print("警告：服务启动超时，请手动检查")


def stop_service():
      """停止可视化网页服务。"""
      if not PID_FILE.exists():
          print("未找到服务进程记录")
          return

      pid = int(PID_FILE.read_text())
      try:
          os.kill(pid, signal.SIGTERM)
          PID_FILE.unlink()
          print(f"可视化服务已停止 (PID: {pid})")
      except ProcessLookupError:
          PID_FILE.unlink()
          print("服务进程已不存在")
      except Exception as e:
          print(f"停止服务失败: {e}")


def push_layer(args):                                                                                                 
      """推送 GeoJSON 图层到可视化服务。"""                                                                             
      source_path = Path(args.path).resolve()                                                                           
      layer_name = args.name                                                                                            
      color = args.color or "#e53935"                                                                                   
      geo_type = args.type or "auto"                                                                                    
                                                                                                                        
      if not source_path.exists():                                                                                      
          print(f"错误：文件不存在 - {source_path}")                                                                    
          sys.exit(1)                                                                                                   
                                                                                                                        
      # 只接收 GeoJSON 格式，转换工作由智能体通过 MCP 工具调用 arcpy 完成                                               
      if source_path.suffix.lower() not in (".geojson", ".json"):                                                       
          print(f"错误：仅支持 GeoJSON 格式，请先将数据转换为 GeoJSON。输入文件: {source_path}")                        
          sys.exit(1)                                                                                                   
                                                                                                                        
      # GeoJSON 文件拷贝到项目统一输出目录                                                                              
      dest_path = GEOJSON_OUTPUT_DIR / f"{layer_name}.geojson"                                                          
      shutil.copy2(source_path, dest_path)                                                                              
                                                                                                                        
      # 相对于项目根目录的路径                                                                                          
      rel_path = str(dest_path.relative_to(PROJECT_ROOT)).replace("\\", "/")                                            
                                                                                                                        
      # 确定 renderer：优先使用传入的 renderer JSON，否则自动构建
      if args.renderer:
            import json as _json
            renderer = _json.loads(args.renderer)
      else:
            renderer = build_renderer(geo_type, color, dest_path)

      # POST 推送
      import requests
      try:
          resp = requests.post(
              f"{SERVICE_URL}/api/layers",
              json={
                  "geojson_path": rel_path,
                  "layer_name": layer_name,
                  "renderer": renderer,
              },
              timeout=10,
          )
          result = resp.json()
          if result.get("ok"):
              print(f"图层已推送: \"{layer_name}\"")
          else:
              print(f"推送失败: {result.get('error', '未知错误')}")
      except requests.ConnectionError:
          print("错误：可视化服务未运行，请先执行 start")
          sys.exit(1)


def build_renderer(geo_type, color, geojson_path):
      """根据几何类型构建渲染参数。"""
      if geo_type != "auto":
          geom_map = {
              "point": {"radius": 7, "weight": 2, "fillOpacity": 0.7},
              "line": {"weight": 3, "fillOpacity": 0.8},
              "polygon": {"weight": 2, "fillOpacity": 0.3},
          }
          symbol = {"color": color, "radius": 5, "weight": 2, "fillOpacity": 0.6}
          symbol.update(geom_map.get(geo_type, {}))
          return {"type": "simple", "symbol": symbol}

      # auto 模式：读取 GeoJSON 检测几何类型
      try:
          with open(geojson_path, "r", encoding="utf-8") as f:
              data = json.load(f)
          features = data.get("features", [])
          if features:
              geom_type = features[0].get("geometry", {}).get("type", "")
              if "Point" in geom_type or "MultiPoint" in geom_type:
                  return {"type": "simple", "symbol": {"color": color, "radius": 7, "weight": 2, "fillOpacity": 0.7}}
              elif "Line" in geom_type or "MultiLine" in geom_type:
                  return {"type": "simple", "symbol": {"color": color, "weight": 3, "fillOpacity": 0.8}}
              elif "Polygon" in geom_type or "MultiPolygon" in geom_type:
                  return {"type": "simple", "symbol": {"color": color, "weight": 2, "fillOpacity": 0.3}}
      except Exception:
          pass

      return {"type": "simple", "symbol": {"color": color, "radius": 5, "weight": 2, "fillOpacity": 0.6}}


def main():
      parser = argparse.ArgumentParser(description="可视化服务管理工具")
      sub = parser.add_subparsers(dest="command")

      sub.add_parser("start", help="启动可视化服务")
      sub.add_parser("stop", help="停止可视化服务")

      push_parser = sub.add_parser("push", help="推送图层到可视化服务")
      push_parser.add_argument("--path", required=True, help="GeoJSON 文件路径（.geojson / .json）")
      push_parser.add_argument("--name", required=True, help="图层显示名称")
      push_parser.add_argument("--color", default=None, help="符号颜色 (如 #e53935)")
      push_parser.add_argument("--type", default="auto", help="几何类型 auto/point/line/polygon")
      push_parser.add_argument("--renderer", default=None, help="符号系统 JSON 字符串（覆盖 --color 和 --type）")

      args = parser.parse_args()

      if args.command == "start":
          start_service()
      elif args.command == "stop":
          stop_service()
      elif args.command == "push":
          push_layer(args)
      else:
          parser.print_help()


if __name__ == "__main__":
      main()