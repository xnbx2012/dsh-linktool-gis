"""
Color-Style MCP Server

ArcGIS地图制图MCP服务器，仅暴露两个工具：
- create_map: 通过 new_draw_map.py 实现多图层制图与PNG导出（subprocess调用）
- get_basemap_names: 返回可用的底图名称列表

所有 ArcPy 操作均在 ArcGIS Pro Python 解释器中通过 subprocess 执行。
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

# 将 scripts/shared 加入 import 路径，以便复用 find_arcpy 公共模块
_SHARED_DIR = Path(__file__).resolve().parent.parent / "shared"
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from find_arcpy import find_py_interpreter  # noqa: E402

# 初始化FastMCP服务器
mcp = FastMCP("color-style-server")

# ── 路径常量 ──
_SCRIPT_DIR = Path(__file__).resolve().parent
_NEW_DRAW_MAP = _SCRIPT_DIR / "new_draw_map.py"
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
        # 强制子进程 stdin/stdout/stderr 使用 UTF-8，避免 Windows 中文环境下默认 GBK 导致乱码
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run(
            [python_exe, script_path],
            input=json.dumps(input_data, ensure_ascii=False).encode('utf-8') if input_data else None,
            capture_output=True,
            timeout=480,  # 8分钟超时（arcpy 加载最长需要 50s，制图逻辑额外需要时间）
            env=env,
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


@mcp.tool()
async def create_map(map_json: str) -> str:
    """
    创建 ArcGIS 地图并导出为 300dpi PNG。

    接收完整 JSON 配置，支持多图层、多种符号系统、标注控制和地图要素配置。
    内部通过 subprocess 在 ArcGIS Pro Python 解释器中执行 new_draw_map.py。

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

    # 注入 aprx 路径
    params["aprx_path"] = str(_APRX_PATH)

    # 通过 subprocess 调用 new_draw_map.py
    result = execute_arcpy_script(_NEW_DRAW_MAP, params)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_basemap_names() -> str:
    """
    返回 color-style-mcp 支持的底图（basemap）名称列表。

    调用方在 map_elements.basemap_name 中传入这些名称之一即可启用对应底图；
    传入空字符串或不匹配的值时，new_draw_map.py 会自动移除已有底图图层。

    Returns:
        JSON 字符串，包含 success 标志和 basemap_names 数组
    """
    return json.dumps({
        "success": True,
        "basemap_names": VALID_BASEMAPS,
        "count": len(VALID_BASEMAPS),
        "note": "将名称传入 create_map 的 layout.basemap_name 即可启用底图；空值或不匹配名称将自动移除底图"
    }, ensure_ascii=False, indent=2)


def main():
    """运行 MCP 服务器"""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
