"""
Color-Style MCP Server

地图制图MCP服务器，仅暴露两个工具：
- create_map: 制图与 300dpi PNG 导出（ArcPy 或 QGIS 后端，subprocess调用）
- get_basemap_names: 返回可用的底图名称列表

双后端（对 MCP 工具名/参数规范/LLM 调用方式完全透明）：
- arcpy：new_draw_map.py 在 ArcGIS Pro Python 解释器中执行（原有能力保留）
- qgis ：qgis_draw_map.py 在 QGIS 自带 Python（python-qgis*.bat）中执行，
  底图转 XYZ 瓦片、符号/标注/整饰要素转 PyQGIS 等价实现

后端选择尊重宿主设置页的引擎开关（LINKTOOL_ENGINE_SWITCHES → engine-switches.json）：
ArcGIS Pro 开关打开且解释器可用时优先 ArcPy，否则用 QGIS；两者都不可用时报错。
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

# 将 scripts/shared 加入 import 路径，以便复用 find_arcpy/qgis_engine 公共模块
_SHARED_DIR = Path(__file__).resolve().parent.parent / "shared"
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from find_arcpy import find_py_interpreter  # noqa: E402
from qgis_engine import qgis_python_launcher  # noqa: E402

# 初始化FastMCP服务器
mcp = FastMCP("color-style-server")

# ── 路径常量 ──
_SCRIPT_DIR = Path(__file__).resolve().parent
_NEW_DRAW_MAP = _SCRIPT_DIR / "new_draw_map.py"
_QGIS_DRAW_MAP = _SCRIPT_DIR / "qgis_draw_map.py"
_APRX_PATH = _SCRIPT_DIR / "catagraphy_project" / "LinkTool.aprx"

# 与 new_draw_map.py 中保持一致的可选底图名称列表
VALID_BASEMAPS = [
    'Imagery', 'Imagery Hybrid', 'Streets', 'Topographic',
    'Navigation', 'Streets (Night)', 'Terrain with Labels',
    'Light Gray Canvas', 'Dark Gray Canvas', 'Outdoor',
    'Oceans', 'National Geographic Style Map',
    'OpenStreetMap Style', 'Topographic (Vector)',
    'Outline Map', 'NAIP Imagery Hybrid',
    'USGS National Map', 'USA Topo Maps',
    'Charted Territory Map', 'Community Map',
    'Navigation (Dark)', 'Newspaper Map',
    'Human Geography Map', 'Human Geography Dark Map',
    'Modern Antique Map', 'Mid-Century Map', 'Nova Map',
    'Colored Pencil Map', 'Firefly Imagery Hybrid',
    'Blueprint', 'Environment Map',
    'Enhanced Contrast Map', 'Enhanced Contrast Dark Map',
    'Navigation (Places)', 'Navigation (Dark - Places)',
]


def execute_arcpy_script(script_path: str | os.PathLike, input_data: dict | None = None) -> dict[str, Any]:
    """
    使用 ArcGIS Pro Python 解释器执行 Python 脚本文件（不是 -c 字符串）。

    通过 subprocess 传 JSON 数据到目标脚本的 stdin。

    Args:
        script_path: 要执行的 .py 脚本绝对路径
        input_data: 通过 stdin 传递给脚本的 JSON 数据

    Returns:
        包含 'success'、'result'、'error' 键的字典
    """
    python_exe = find_py_interpreter()
    if not python_exe:
        return {
            "success": False,
            "result": None,
            "error": "未找到 ArcGIS Pro Python 解释器。请设置 ARCGIS_PRO_PATH 环境变量。"
        }

    script_path = str(script_path)
    if not os.path.isfile(script_path):
        return {
            "success": False,
            "result": None,
            "error": f"脚本文件不存在: {script_path}"
        }

    try:
        # 不显式传 env：构造新环境块会破坏 arcpy 子进程（实测挂起/ModuleNotFoundError），
        # 直接继承父环境；脚本内部已自行 reconfigure stdout 为 UTF-8
        result = subprocess.run(
            [python_exe, script_path],
            input=json.dumps(input_data, ensure_ascii=False).encode('utf-8') if input_data else None,
            capture_output=True,
            timeout=480,  # 8分钟超时（arcpy 加载最长需要 50s，制图逻辑额外需要时间）
        )
        stdout_text = result.stdout.decode('utf-8', errors='replace') if result.stdout else ''
        stderr_text = result.stderr.decode('utf-8', errors='replace') if result.stderr else ''

        if result.returncode != 0:
            return {
                "success": False,
                "result": None,
                "error": f"脚本执行失败 (returncode={result.returncode}): {stderr_text.strip()}"
            }

        # 尝试从 stdout 最后一行解析 JSON 输出
        stdout = stdout_text.strip()
        if not stdout:
            return {
                "success": False,
                "result": None,
                "error": f"脚本未产生任何输出。stderr: {stderr_text.strip()[-300:]}"
            }

        # 找出最后一行以 { 开头的 JSON 行（new_draw_map 通过 print 输出 JSON）
        json_line = None
        for line in reversed(stdout.splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                json_line = line
                break

        if json_line is None:
            # 兜底：直接返回原始 stdout
            return {
                "success": True,
                "result": stdout,
                "error": None
            }

        try:
            output = json.loads(json_line)
            return {
                "success": True,
                "result": output,
                "error": None
            }
        except json.JSONDecodeError:
            return {
                "success": True,
                "result": json_line,
                "error": None
            }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "result": None,
            "error": "脚本执行超时（5分钟）"
        }
    except Exception as e:
        return {
            "success": False,
            "result": None,
            "error": f"执行错误: {str(e)}"
        }


def validate_map_json(params: dict) -> list[str]:
    """
    校验地图 JSON 配置是否符合要求。

    Args:
        params: 已解析的 JSON 字典

    Returns:
        错误信息列表，空列表表示校验通过
    """
    errors = []

    if not isinstance(params, dict):
        return ["JSON 根节点必须是对象"]

    layout = params.get("layout")
    if not isinstance(layout, dict):
        errors.append("缺少 layout 配置或格式不正确")
    else:
        output_path = layout.get("output_path", "")
        if not output_path or not isinstance(output_path, str):
            errors.append("layout.output_path 不能为空")

    layers = params.get("layers")
    if not isinstance(layers, list) or len(layers) == 0:
        errors.append("layers 不能为空，至少需要一个图层配置")
    else:
        valid_renderer_types = {"simple", "unique_value", "graduated_colors", "classed"}
        for i, layer in enumerate(layers):
            prefix = f"layers[{i}]"
            if not isinstance(layer, dict):
                errors.append(f"{prefix}: 图层配置必须是对象")
                continue

            fc = layer.get("feature_class", "")
            if not fc or not isinstance(fc, str):
                errors.append(f"{prefix}.feature_class 不能为空")

            renderer = layer.get("renderer")
            if not isinstance(renderer, dict):
                errors.append(f"{prefix}.renderer: 缺少符号系统配置")
            else:
                rtype = renderer.get("type", "")
                if rtype not in valid_renderer_types:
                    errors.append(
                        f"{prefix}.renderer.type 无效: '{rtype}'，"
                        f"支持: {', '.join(sorted(valid_renderer_types))}"
                    )
                elif rtype in ("unique_value", "graduated_colors", "classed"):
                    field = renderer.get("field", "")
                    if not field or not isinstance(field, str):
                        errors.append(
                            f"{prefix}.renderer.field 不能为空"
                            f"（{rtype} 类型必须指定符号化字段）"
                        )

    return errors


def _read_engine_switches() -> dict[str, bool]:
    """读取宿主引擎开关（env LINKTOOL_ENGINE_SWITCHES → JSON 文件）；缺失时按全部可用处理。"""
    path = os.environ.get("LINKTOOL_ENGINE_SWITCHES", "").strip()
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {k: bool(v) for k, v in data.items() if isinstance(k, str)}
    except Exception:  # noqa: BLE001 —— 开关读不到按默认处理，不阻断制图
        return {}


def select_backend() -> tuple[str, str | None, str | None]:
    """选择制图后端。返回 (backend, 执行体路径, 错误信息)。

    规则（尊重设置页引擎开关；无开关文件时按全部可用处理，保持旧行为）：
      1. ArcGIS Pro 开关开且解释器可用 → ('arcpy', new_draw_map.py)
      2. QGIS 开关开且 python-qgis*.bat 可用 → ('qgis', qgis_draw_map.py)
      3. 已开启的引擎缺失/另一引擎被关闭 → 返回明确错误
    """
    switches = _read_engine_switches()
    arcpy_on = switches.get("arcpy", True)
    qgis_on = switches.get("qgis", True)
    arcpy_exe = find_py_interpreter()
    qgis_launcher = qgis_python_launcher()

    if arcpy_on and arcpy_exe:
        return "arcpy", str(_NEW_DRAW_MAP), None
    if qgis_on and qgis_launcher:
        return "qgis", str(_QGIS_DRAW_MAP), None

    reasons = []
    if not arcpy_on and not qgis_on:
        reasons.append("设置页中 ArcGIS Pro 与 QGIS 引擎开关均为关闭")
    if arcpy_on and not arcpy_exe:
        reasons.append("ArcGIS Pro 引擎已开启，但未找到 arcgispro-py3 解释器（设置 ARCGIS_PRO_PATH 或安装 ArcGIS Pro；arcpy 为 Windows 专属引擎，Linux/macOS 不可用）")
    if qgis_on and not qgis_launcher:
        if os.name == "nt":
            reasons.append("QGIS 引擎已开启，但未找到 python-qgis*.bat 启动器（需安装 QGIS 3.x）")
        else:
            reasons.append(
                "QGIS 引擎已开启，但 QGIS Python 后端不可用：POSIX 上需要系统能 import qgis，"
                "即 Debian/Ubuntu 需安装 python3-qgis（sudo apt install python3-qgis）。"
                "排查：python3 -c \"import qgis\" 看是否报 ModuleNotFoundError；"
                "同时确认 qgis_process 在 PATH 上。"
            )
    return "", None, "无可用制图后端：" + "；".join(reasons)


def execute_qgis_script(script_path: str | os.PathLike, input_data: dict | None = None) -> dict[str, Any]:
    """经 QGIS 自带 Python 启动器执行制图脚本（stdin JSON 进、stdout JSON 行出）。"""
    launcher = qgis_python_launcher()
    if not launcher:
        tip = (
            "未找到 QGIS python-qgis*.bat 启动器（需安装 QGIS 3.x）"
            if os.name == "nt"
            else (
                "QGIS Python 后端不可用：POSIX 上需系统 python3 能 import qgis，"
                "Debian/Ubuntu 请执行 sudo apt install python3-qgis；"
                "排查：python3 -c \"import qgis\"；并确认 qgis_process 在 PATH 上"
            )
        )
        return {"success": False, "result": None, "error": tip}
    script_path = str(script_path)
    if not os.path.isfile(script_path):
        return {"success": False, "result": None, "error": f"脚本文件不存在: {script_path}"}
    try:
        # 与 execute_arcpy_script 一致：继承父环境（脚本内部自行 reconfigure UTF-8）
        result = subprocess.run(
            [launcher, script_path],
            input=json.dumps(input_data, ensure_ascii=False).encode("utf-8") if input_data else None,
            capture_output=True,
            timeout=480,
        )
        stdout_text = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
        stderr_text = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""

        if result.returncode != 0:
            return {
                "success": False,
                "result": None,
                "error": f"脚本执行失败 (returncode={result.returncode}): {stderr_text.strip()[-300:]}",
            }

        stdout = stdout_text.strip()
        if not stdout:
            return {"success": False, "result": None, "error": f"脚本未产生任何输出。stderr: {stderr_text.strip()[-300:]}"}

        json_line = None
        for line in reversed(stdout.splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                json_line = line
                break
        if json_line is None:
            return {"success": True, "result": stdout, "error": None}
        try:
            return {"success": True, "result": json.loads(json_line), "error": None}
        except json.JSONDecodeError:
            return {"success": True, "result": json_line, "error": None}
    except subprocess.TimeoutExpired:
        return {"success": False, "result": None, "error": "脚本执行超时（8分钟）"}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "result": None, "error": f"执行错误: {e}"}


@mcp.tool()
async def create_map(map_json: str) -> str:
    """
    创建地图并导出为 300dpi PNG。

    接收完整 JSON 配置，支持多图层、多种符号系统、标注控制和地图要素配置。
    后端按设置页引擎开关自动选择（ArcGIS Pro 优先，QGIS 兜底；JSON 契约两者一致）。

    Args:
        map_json: JSON 格式的地图配置字符串，包含 layout、layers、map_elements 等字段

    Returns:
        JSON 字符串，包含执行结果或错误信息
    """
    try:
        params = json.loads(map_json)
    except json.JSONDecodeError as e:
        return json.dumps({
            "success": False,
            "error": f"JSON 解析失败: {str(e)}"
        }, ensure_ascii=False, indent=2)

    # JSON schema 校验
    validation_errors = validate_map_json(params)
    if validation_errors:
        return json.dumps({
            "success": False,
            "error": "JSON 配置校验失败",
            "details": validation_errors
        }, ensure_ascii=False, indent=2)

    backend, executable, error = select_backend()
    if error:
        return json.dumps({"success": False, "error": error}, ensure_ascii=False, indent=2)

    if backend == "arcpy":
        # 注入 aprx 路径（仅 ArcPy 后端使用；QGIS 后端忽略该字段）
        params["aprx_path"] = str(_APRX_PATH)
        result = execute_arcpy_script(executable, params)
    else:
        result = execute_qgis_script(executable, params)

    if isinstance(result.get("result"), dict):
        result["result"].setdefault("backend", backend)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_basemap_names() -> str:
    """
    返回 color-style-mcp 支持的底图（basemap）名称列表。

    调用方在 layout.basemap_name 中传入这些名称之一即可启用对应底图；
    传入空字符串时无底图。ArcGIS Pro 后端使用同名 Esri 底图；QGIS 后端将
    名称映射为 XYZ 瓦片（无同名瓦片的名称以 Topographic 近似并在结果中记 warning）。

    Returns:
        JSON 字符串，包含 success 标志、basemap_names 数组与当前后端
    """
    backend, _, error = select_backend()
    return json.dumps({
        "success": True,
        "basemap_names": VALID_BASEMAPS,
        "count": len(VALID_BASEMAPS),
        "backend": backend or "unavailable",
        "note": "将名称传入 create_map 的 layout.basemap_name 即可启用底图；空值将不添加底图"
                + ("；QGIS 后端将名称映射为 XYZ 瓦片，无同名瓦片时以 Topographic 近似" if backend == "qgis" else ""),
        **({"error": error} if error else {}),
    }, ensure_ascii=False, indent=2)


def main():
    """运行 MCP 服务器"""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
