"""
ArcGIS MCP Server（五引擎统一调度）

基于 FastMCP 的 GIS MCP 服务器。execute_gis_tool 按引擎开关统一调度五种后端：

  inner  内置纯 Python 工具（geopandas/shapely/rasterio，零外部依赖）      默认开
  wbt    WhiteboxTools 进程内反射执行                                      默认开
  gdal   GDAL 直执行（rasterio/pyogrio 进程内 + 必要时 GDAL CLI）           默认开
  qgis   QGIS 处理算法（进程内 QgsApplication / qgis_process）             默认开
  arcpy  ArcGIS Pro arcgispro-py3 持久 worker（Windows 专属）              默认关

元数据/查询类工具（list_gdb_contents / query_feature_attributes /
get_data_properties / get_field_unique_values）由 shared/gis_io.py 内置实现，
不依赖任何外部引擎；ArcPy 路径仅在显式 arcpy_ 前缀或开关允许时启用。

引擎开关由适配层写入 ${DSH_PLUGIN_ROOT}/.runtime/engine-switches.json
（设置页 volatile 配置实时落盘，每次调用前重新读取，无需重启 MCP）。
依赖在 pyproject.toml 中声明（whitebox / pyogrio / geopandas / rasterio / mcp[cli]<2）。
"""

import asyncio
import difflib
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Annotated, Any

# 关键：whitebox 的 run_tool 内部用 Popen(universal_newlines=True) 读子进程 stdout，
# Windows 默认按 locale(cp936/GBK) 解码。whitebox_tools.exe 的输出含中文路径、进度
# 条等非 GBK 字节（如 0x82），会触发 'gbk' codec can't decode ... Illegal multibyte
# sequence，导致 readline 抛异常、整行丢失甚至 run_tool 中断。
# 通过在进程启动时强制 PYTHONUTF8=1，让 Python 进入 UTF-8 模式，Popen 的
# universal_newlines=True 就会用 UTF-8 解码子进程输出。
os.environ["PYTHONUTF8"] = "1"

# stdio MCP 通信本身也走标准流：客户端以 UTF-8 写入子进程 stdin 的 JSON-RPC
# （含中文路径等参数），但 Windows 默认按 locale(cp936) 解码 stdin，遇到非 GBK 字节
# 会抛 UnicodeDecodeError 让 anyio stdin_reader 崩溃、整条连接被关闭。即便外部未设
# PYTHONUTF8，这里在 mcp 接管前把标准三流显式 reconfigure 成 UTF-8，作为兜底。
for _stream in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from mcp.server.fastmcp import FastMCP
from pydantic import BeforeValidator

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))

# 引擎开关文件：适配层（src/index.ts）随设置页 volatile 写入实时落盘。
# 文件不存在时按 shipped 默认（arcpy 关、其余开）。
_ENGINE_SWITCH_PATH = os.environ.get(
    "LINKTOOL_ENGINE_SWITCHES",
    os.path.join(_THIS_DIR, "..", "..", ".runtime", "engine-switches.json"),
)
_DEFAULT_ENGINE_SWITCHES = {"inner": True, "wbt": True, "gdal": True, "qgis": True, "arcpy": False}


def _engine_switch(engine: str) -> bool:
    """读单个引擎开关；文件缺失/损坏/字段缺失时回落 shipped 默认。"""
    try:
        with open(_ENGINE_SWITCH_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        value = data.get(engine)
        if isinstance(value, bool):
            return value
    except (OSError, ValueError):
        pass
    return _DEFAULT_ENGINE_SWITCHES[engine]


def _path_restrict() -> bool:
    """读「输出路径严格限制」开关（与引擎开关同文件，适配层实时落盘）。

    True = 输入/输出路径限制在 AGENT_WORK_DIR 的 01/02/03 子目录；
    False = 不作任何路径限制（不限于 01/02/03，也不限于工作区内）。
    文件缺失/损坏/字段缺失时回落 True（fail-closed），裸跑/调试不放宽。
    """
    try:
        with open(_ENGINE_SWITCH_PATH, "r", encoding="utf-8") as f:
            value = json.load(f).get("pathRestrict")
        if isinstance(value, bool):
            return value
    except (OSError, ValueError):
        pass
    return True


def _coerce_optional_list(v: Any) -> Any:
    """把空串 / 'null' / None 归一为 None，其余原样返回。

    MCP Inspector 对 `list | None` 型可选参数，用户未填时会发送空串 ""，
    pydantic 校验 `list[str] | None` 会拒绝 ""（既非 list 也非 None）。
    此 BeforeValidator 在校验前把这类「空」值统一归一为 None，使工具对
    Inspector 的序列化行为容错。
    """
    if v is None or (isinstance(v, str) and v.strip() in ("", "null", "None")):
        return None
    return v

# 共享 GIS 读写封装（pyogrio/geopandas/rasterio，无 arcpy）
_SHARED_DIR = os.path.abspath(os.path.join(_THIS_DIR, "..", "shared"))
if _SHARED_DIR not in sys.path:
    sys.path.insert(0, _SHARED_DIR)

# Schema 加载器（从 schema.json 缓存搜索工具列表，避免每次 list_available_tools 调用遍历各引擎）
sys.path.insert(0, _THIS_DIR)
from schema_loader import (  # noqa: E402
    load_schema,
    search_tools,
    is_schema_valid,
    set_schema_path,
)

# 关键：在导入 gis_io 之前，先把 pyogrio / rasterio / geopandas（GDAL/OGR 绑定）import 一次。
# GDAL 的 C 扩展在首次 import 时初始化全局锁与插件注册；若把首次 import 推迟到首个
# tools/call 里（事件循环已启动、anyio stdin_reader 工作线程已在阻塞读 stdin 时），
# 会与 stdio 传输死锁，表现为工具调用永不返回（id:3 永不到达 stdout，进程最终被
# 客户端超时杀掉）。在 mcp.run() 之前完成这些重型 import，可消除该死锁。
import rasterio  # noqa: F401, E402
from gis_io import repair_proj_env  # noqa: E402

# 机器残留的 PROJ_LIB/GDAL_DATA（PostGIS 老库）会让一切 EPSG 查询失败；
# 在 GDAL 栈首次定位 proj.db 前改回 wheel 自带数据目录。
repair_proj_env()
import pyogrio  # noqa: F401, E402
import geopandas  # noqa: F401, E402
# shapely 的 GEOS C 扩展同理：topology.py 在首个 tools/call 里才会用到 make_valid /
# explain_validity，首次 import 必须在 mcp.run() 之前完成。
import shapely  # noqa: F401, E402

from gis_io import (  # noqa: E402
    embed_geojson,
    list_gdb_layers,
    query_attributes,
    data_properties,
    field_unique_values,
    _split_path,
)

# 纯 Python 自定义工具注册表（内置引擎，无外部依赖）。延迟 import：
# native_tools 模块级 import 了 geopandas/rasterio 等（已在顶部预热过 GDAL C 扩展），
# 首次 import 安全（命中 sys.modules，不再触发 C 扩展初始化，避免 stdio 死锁）。
try:
    from native_tools import CUSTOM_TOOL_REGISTRY  # type: ignore  # noqa: E402
except Exception:  # noqa: BLE001  —— 注册表加载失败不应阻断服务启动
    CUSTOM_TOOL_REGISTRY = {}

# GDAL 直执行引擎（进程内 rasterio/pyogrio + 必要时 GDAL CLI）。
# 延迟 import；CLI 不可用时仍可启动（仅 gdal:* 中依赖 CLI 的工具调时返回清晰错误）。
try:
    from gdal_engine import (  # type: ignore  # noqa: E402
        GDAL_TOOL_CATALOG,
        list_gdal_algorithms,
        run_gdal_tool as _run_gdal_tool_native,
        gdal_available,
    )
except Exception:  # noqa: BLE001
    GDAL_TOOL_CATALOG = {}

    def list_gdal_algorithms() -> dict:  # type: ignore[no-redef]
        return {}

    def _run_gdal_tool_native(algo_id: str, parameters: dict) -> dict:  # type: ignore[no-redef]
        return {"success": False, "output": None, "error": "GDAL 引擎未加载。",
                "messages": [], "output_paths": []}

    def gdal_available() -> bool:  # type: ignore[no-redef]
        return False

# QGIS 后备引擎。延迟 import；QGIS 未安装时引擎不可用，
# 但不阻断 MCP 服务启动（调用时返回清晰错误）。
try:
    from qgis_engine import (  # type: ignore  # noqa: E402
        list_qgis_algorithms,
        run_qgis_tool as _run_qgis_tool_native,
        qgis_available,
    )
except Exception:  # noqa: BLE001
    def list_qgis_algorithms() -> dict:  # type: ignore[no-redef]
        return {}

    def _run_qgis_tool_native(algo_id: str, parameters: dict) -> dict:  # type: ignore[no-redef]
        return {"success": False, "output": None, "error": "QGIS 引擎未加载。",
                "messages": [], "output_paths": []}

    def qgis_available() -> bool:  # type: ignore[no-redef]
        return False

# Initialize FastMCP server
mcp = FastMCP("arcgis-mcp-server")

logger = logging.getLogger(__name__)

EXECUTE_GIS_TOOL_TIMEOUT_SECONDS = 900

# 拓扑检查/修复开关与工具：topology.py（shapely 扫描 + shapely make_valid + whitebox clean_vector）。
# PRE/POST 仅对矢量路径生效，best-effort 不阻断执行。详见 execute_gis_tool 注入点。
try:
    from topology import (  # noqa: E402
        TOPO_SKIP_KEY,
        topo_enabled,
        scan_topology,
        repair_topology,
    )
except Exception:  # noqa: BLE001  —— 拓扑模块缺失时不阻断四引擎主路径
    TOPO_SKIP_KEY = "_topo_skip"

    def topo_enabled(parameters: dict | None) -> bool:  # type: ignore[no-redef]
        return False

    def scan_topology(path: str) -> dict:  # type: ignore[no-redef]
        return {"checked": False}

    def repair_topology(path: str, reasons=None) -> dict:  # type: ignore[no-redef]
        return {"repaired": False}

# ─── ArcPy 引擎（ArcGIS Pro 持久 worker，Windows 专属）─────────────────────────
# 延迟 import：find_arcpy / arcpy_worker 均不依赖 GDAL 栈；主进程无 arcpy，
# 所有 ArcPy 执行仍经 arcgispro-py3 子进程。解释器缺失时引擎不可用但不阻断启动。
try:
    from find_arcpy import find_py_interpreter  # type: ignore  # noqa: E402
    from arcpy_worker import ArcPyWorker  # type: ignore  # noqa: E402
except Exception:  # noqa: BLE001
    def find_py_interpreter() -> str | None:  # type: ignore[no-redef]
        return None

    ArcPyWorker = None  # type: ignore[assignment,misc]

_arcpy_workers: dict[str, Any] = {}

DEFAULT_ARCPY_TIMEOUT_SECONDS = 300


def arcpy_available() -> bool:
    """ArcGIS Pro 解释器是否可定位（不实际启动 worker）。"""
    try:
        return find_py_interpreter() is not None
    except Exception:  # noqa: BLE001
        return False


def execute_arcpy_script(script_code: str, input_data: dict | None = None, timeout_seconds: int | None = None) -> dict[str, Any]:
    """经持久 worker 在 ArcGIS Pro Python 环境执行脚本，返回 {success, result, error}。"""
    python_exe = find_py_interpreter()
    if not python_exe:
        return {
            "success": False,
            "result": None,
            "error": "ArcGIS Pro Python interpreter not found. Please set ARCGIS_PRO_PATH environment variable."
        }

    timeout_seconds = timeout_seconds or DEFAULT_ARCPY_TIMEOUT_SECONDS

    try:
        # 强制子进程使用 UTF-8 编码，避免 Windows GBK 无法编码中文或 emoji
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        if python_exe not in _arcpy_workers:
            _arcpy_workers[python_exe] = ArcPyWorker(python_exe)
        worker = _arcpy_workers[python_exe]
        reply = worker.run(script_code, input_data, timeout_seconds)
        from types import SimpleNamespace
        result = SimpleNamespace(**{k: reply[k] for k in ('returncode', 'stdout', 'stderr')})
        diagnostics = reply.get('execution_diagnostics', {})

        if result.returncode != 0:
            return {
                "success": False,
                "result": None,
                "error": f"Script execution failed: {result.stderr}",
                "execution_diagnostics": diagnostics
            }

        # Try to parse JSON output from stdout
        try:
            output = json.loads(result.stdout)
            return {
                "success": True,
                "result": output,
                "error": None,
                "execution_diagnostics": diagnostics
            }
        except json.JSONDecodeError:
            # Return raw stdout if not valid JSON
            return {
                "success": True,
                "result": result.stdout.strip(),
                "error": None,
                "execution_diagnostics": diagnostics
            }

    except Exception as e:  # noqa: BLE001（worker.run 内部已处理超时，这里兜底任意异常）
        return {
            "success": False,
            "result": None,
            "error": f"Execution error: {str(e)}"
        }


_ARCPY_EXEC_SCRIPT = '''
import arcpy
import json
import sys

# Read input parameters from stdin
input_json = sys.stdin.read()
params = json.loads(input_json)

tool_name = params["tool_name"]
tool_params = params["parameters"]

try:
    # Navigate to the tool using getattr
    tool_parts = tool_name.split(".")
    tool_obj = arcpy
    for part in tool_parts[1:]:  # Skip 'arcpy' as we already have it
        tool_obj = getattr(tool_obj, part)

    # Execute the tool with unpacked parameters
    result = tool_obj(**tool_params)

    # Try to get output messages
    messages = []
    if hasattr(result, 'getMessages'):
        messages = [result.getMessage(i) for i in range(result.messageCount)]

    output = {
        "success": True,
        "result": str(result) if result else None,
        "messages": messages
    }
    print(json.dumps(output))

except Exception as e:
    import traceback
    error_output = {
        "success": False,
        "error": str(e),
        "traceback": traceback.format_exc()
    }
    print(json.dumps(error_output))
'''


async def _run_arcpy_tool(tool_name: str, parameters: dict) -> dict[str, Any]:
    """在线程池中执行 ArcPy 工具（持久 worker 同步阻塞，避免卡事件循环）。"""
    result = await asyncio.to_thread(
        execute_arcpy_script,
        _ARCPY_EXEC_SCRIPT,
        {"tool_name": tool_name, "parameters": parameters or {}},
        EXECUTE_GIS_TOOL_TIMEOUT_SECONDS,
    )
    success = bool(result.get("success"))
    payload = result.get("result")
    error = result.get("error")
    messages: list[str] = []
    if isinstance(payload, dict):
        messages = list(payload.get("messages", []) or [])
        if payload.get("success") is False:
            success = False
            error = payload.get("error") or error
        output_text = str(payload.get("result")) if payload.get("result") is not None else None
    else:
        output_text = str(payload) if payload is not None else None
    return {
        "success": success,
        "output": output_text,
        "error": error,
        "messages": messages,
        "output_paths": _compute_output_paths(parameters or {}, []),
        "engine": "arcpy",
    }


def _arcpy_tool_exists(tool_name: str) -> bool:
    """裸名/前缀名是否形如 arcpy.<module>.<Tool>（仅按命名约定，不探测 ArcGIS）。"""
    return isinstance(tool_name, str) and tool_name.strip().lower().startswith("arcpy.")


# 嵌入 tool_result 的 GeoJSON 体积上限（字节）。超阈值不嵌完整 GeoJSON，降级为摘要+路径，
# 防止单条 tool_result 经 SDK stdout JSON Lines 回传时撞读缓冲上限杀死整个 SDK 会话。
# （完整数据由磁盘路径推送，不依赖嵌入。）
_EMBED_GEOJSON_MAX_BYTES = 512 * 1024

# whitebox 单例（首次 import 会下载/解压 Rust 二进制，缓存于 uv cache）。
_WBT: Any = None


def _wbt():
    """惰性取 WhiteboxTools 单例。whitebox 首次 import 触发二进制下载，故延迟到首调。"""
    global _WBT
    if _WBT is None:
        import whitebox  # type: ignore

        _WBT = whitebox.WhiteboxTools()
    return _WBT


# ─── 工具名归一与白名单 ──────────────────────────────────────────────────────
# 进程级缓存：list_tools() 返回 dict{snake_case_name: 简介}，全量工具名快照。
_TOOL_NAME_CACHE: set[str] | None = None


def _tool_names() -> set[str]:
    global _TOOL_NAME_CACHE
    if _TOOL_NAME_CACHE is None:
        try:
            _TOOL_NAME_CACHE = set(_wbt().list_tools().keys())
        except Exception:  # noqa: BLE001
            _TOOL_NAME_CACHE = set()
    return _TOOL_NAME_CACHE


def _camel_to_snake(name: str) -> str:
    """BufferRaster → buffer_raster；ABCDef → ab_c_def（连续大写整体小写）。"""
    s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s2 = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s1)
    return s2.lower()


def _normalize_tool_name(raw: str) -> str:
    """归一用户传入的 tool_name：去空白、转小写、横杠转下划线。"""
    return raw.strip().lower().replace("-", "_").replace(" ", "_")


def _resolve_tool_name(raw: str) -> str | None:
    """把任意形态的工具名解析为 whitebox 合法 snake_case 名。"""
    names = _tool_names()
    n = _normalize_tool_name(raw)
    if n in names:
        return n
    snake = _camel_to_snake(raw.strip())
    if snake in names:
        return snake
    return None


def _suggest_tool_names(raw: str, limit: int = 10) -> list[str]:
    """对未知工具名给出编辑距离最近的若干建议。"""
    names = sorted(_tool_names())
    target = _normalize_tool_name(raw)
    close = difflib.get_close_matches(target, names, n=limit, cutoff=0.3)
    if not close:
        # fallback：按前缀匹配
        close = [n for n in names if n.startswith(target[:3])][:limit]
    return close


# ─── 五引擎统一调度：内置(inner) > whitebox(wbt) > gdal > qgis > arcpy ──────────
# tool_name 可带前缀强制指定引擎，或用裸名按降级链自动解析：
#   inner_xxx    → 仅内置（不降级）
#   wbt_xxx      → 仅 whitebox（不降级）
#   gdal_xxx     → 仅 gdal（xxx 为 gdal:tool，如 gdal_translate；冒号保留）
#   qgis_xxx     → 仅 qgis（xxx 为 provider:algo，如 qgis_native:buffer）
#   arcpy_xxx    → 仅 arcpy（xxx 为 arcpy.模块.工具名）
#   裸名        → inner 命中 → wbt 命中 → gdal(gdal: 前缀) → qgis(若含 ':') → arcpy(arcpy. 前缀)
# 引擎开关关闭时：裸名降级链跳过该引擎；前缀强制命中关闭引擎则直接拒绝。
_INNER_NAMES: set[str] = set(CUSTOM_TOOL_REGISTRY.keys())
_GDAL_NAMES: set[str] = set(GDAL_TOOL_CATALOG.keys()) if GDAL_TOOL_CATALOG else set()

# 引擎是否启用（每次 execute_gis_tool 调用实时读取开关文件）。
_ENGINE_ENABLED = {
    "inner": lambda: _engine_switch("inner"),
    "wbt": lambda: _engine_switch("wbt"),
    "gdal": lambda: _engine_switch("gdal"),
    "qgis": lambda: _engine_switch("qgis"),
    "arcpy": lambda: _engine_switch("arcpy"),
}


def _resolve_engine(raw: str) -> tuple[str, str] | None:
    """把任意形态的 tool_name 解析为 (engine, canon)，未命中任一引擎返回 None。

    前缀形式严格走指定引擎（不降级）；裸名按 inner→wbt→gdal→qgis→arcpy 降级。
    关闭的引擎不参与裸名降级，也不接受前缀强制（返回 None 由调用方报错）。
    """
    if not raw or not isinstance(raw, str):
        return None
    n = _normalize_tool_name(raw)  # lower / dash->_ / 冒号保留

    # 前缀：inner_
    if n.startswith("inner_"):
        canon = _normalize_tool_name(raw[len("inner_"):])
        return ("inner", canon) if canon in _INNER_NAMES and _ENGINE_ENABLED["inner"]() else None
    # 前缀：wbt_
    if n.startswith("wbt_"):
        if not _ENGINE_ENABLED["wbt"]():
            return None
        rest = raw[len("wbt_"):]
        resolved = _resolve_tool_name(rest)
        return ("wbt", resolved) if resolved else None
    # 前缀：gdal_  （其后保留 gdal:tool 形态，如 gdal_gdal:translate 或 gdal_translate）
    if n.startswith("gdal_"):
        algo = raw[len("gdal_"):]
        # 既支持 gdal_gdal:translate 也支持 gdal_translate
        canon = algo.strip().lower()
        if not canon.startswith("gdal:"):
            canon = f"gdal:{canon}"
        return ("gdal", canon) if canon in _GDAL_NAMES and _ENGINE_ENABLED["gdal"]() else None
    # 前缀：qgis_  （其后保留 provider:algo 冒号形态）
    if n.startswith("qgis_"):
        algo = raw[len("qgis_"):].strip().lower()
        return ("qgis", algo) if algo in list_qgis_algorithms() and _ENGINE_ENABLED["qgis"]() else None
    # 前缀：arcpy_ / arcpy.（ArcGIS Pro 引擎，Windows 专属）
    if n.startswith("arcpy_"):
        if not _ENGINE_ENABLED["arcpy"]():
            return None
        tool = raw[len("arcpy_"):].strip()
        if not tool.startswith("arcpy."):
            tool = "arcpy." + tool
        return ("arcpy", tool) if _arcpy_tool_exists(tool) and arcpy_available() else None

    # 裸名降级：inner → wbt → gdal → qgis → arcpy
    if _ENGINE_ENABLED["inner"]() and n in _INNER_NAMES:
        return ("inner", n)
    if _ENGINE_ENABLED["wbt"]():
        resolved = _resolve_tool_name(raw)
        if resolved:
            return ("wbt", resolved)
    # gdal：含冒号的裸名（如 gdal:translate）
    if _ENGINE_ENABLED["gdal"]() and n.startswith("gdal:") and n in _GDAL_NAMES:
        return ("gdal", n)
    # qgis：含冒号的裸名（如 native:buffer）
    if _ENGINE_ENABLED["qgis"]() and ":" in n and n in list_qgis_algorithms():
        return ("qgis", n)
    # arcpy：arcpy.模块.工具名 形态
    if _ENGINE_ENABLED["arcpy"]() and _arcpy_tool_exists(raw) and arcpy_available():
        return ("arcpy", raw.strip())
    return None


def _engine_disabled_reason(engine: str) -> str:
    labels = {
        "inner": "内置(inner)", "wbt": "WhiteboxTools(wbt)", "gdal": "GDAL",
        "qgis": "QGIS", "arcpy": "ArcGIS Pro(arcpy)",
    }
    return f"{labels.get(engine, engine)} 引擎已在设置页关闭（engine.{engine}=false）。可在 LinkTool-GIS 设置中重新启用。"


def _suggest_all(raw: str, limit: int = 8) -> dict[str, list[str]]:
    """对未知名给出各引擎的编辑距离建议，供报错提示。"""
    target = _normalize_tool_name(raw)
    result: dict[str, list[str]] = {}

    inner = sorted(_INNER_NAMES)
    wbt = sorted(_tool_names())
    gdal = sorted(_GDAL_NAMES)

    inner_hits = difflib.get_close_matches(target, inner, n=limit, cutoff=0.3)
    wbt_hits = difflib.get_close_matches(target, wbt, n=limit, cutoff=0.3)
    gdal_hits = difflib.get_close_matches(target, gdal, n=limit, cutoff=0.3)
    result["inner"] = inner_hits or [x for x in inner if x.startswith(target[:3])][:limit]
    result["wbt"] = wbt_hits or [x for x in wbt if x.startswith(target[:3])][:limit]
    result["gdal"] = gdal_hits or [x for x in gdal if x.startswith(target[:3])][:limit]

    qalgos = sorted(list_qgis_algorithms().keys())
    qgis_hits = difflib.get_close_matches(target, qalgos, n=limit, cutoff=0.3)
    result["qgis"] = qgis_hits or [x for x in qalgos if x.startswith(target[:3])][:limit]
    return result


def _dispatch_custom_tool(name: str, parameters: dict) -> dict[str, Any]:
    """执行一个内置纯 Python 工具，返回 {success, output, error, output_paths, ...}。"""
    func, _desc = CUSTOM_TOOL_REGISTRY[name]
    return func(parameters or {})


async def _dispatch_qgis_tool(algo_id: str, parameters: dict) -> dict[str, Any]:
    """在线程池中执行 QGIS 算法（同步子进程，避免阻塞事件循环）。"""
    return await asyncio.to_thread(_run_qgis_tool_native, algo_id, parameters or {})


async def _dispatch_gdal_tool(algo_id: str, parameters: dict) -> dict[str, Any]:
    """在线程池中执行 GDAL 引擎工具（rasterio/pyogrio/CLI，避免阻塞事件循环）。"""
    return await asyncio.to_thread(_run_gdal_tool_native, algo_id, parameters or {})


# ─── 参数映射：关键字字典 → whitebox --flag 列表 ────────────────────────────────
# 进程级缓存：{tool_name: tool_parameters() 解析后的 [{...}, ...]}。
_PARAM_CACHE: dict[str, list[dict[str, Any]]] = {}


def _tool_params(tool_name: str) -> list[dict[str, Any]]:
    """取某工具的参数定义（来自 wbt.tool_parameters，JSON 解析）。"""
    if tool_name in _PARAM_CACHE:
        return _PARAM_CACHE[tool_name]
    try:
        raw = _wbt().tool_parameters(tool_name)
        parsed = json.loads(raw)
        params = parsed.get("parameters", []) if isinstance(parsed, dict) else []
    except Exception as e:  # noqa: BLE001
        logger.warning("[execute_gis_tool] tool_parameters(%s) failed: %s", tool_name, e)
        params = []
    _PARAM_CACHE[tool_name] = params
    return params


def _build_arg_list(tool_name: str, parameters: dict[str, Any]) -> tuple[list[str] | None, dict[str, Any]]:
    """把 parameters 关键字字典映射为 whitebox 的 ["--flag=value", ...] 列表。

    返回 (args, error)。args 为 None 表示有错误（缺必填 / 未知关键字），error 含详情。
    """
    params = _tool_params(tool_name)

    # name(lower, 去空格) → 参数定义；flag(去前缀 --/-, lower) → 参数定义
    by_name: dict[str, dict[str, Any]] = {}
    by_flag: dict[str, dict[str, Any]] = {}
    for p in params:
        nm = (p.get("name") or "").strip().lower().replace(" ", "_")
        if nm:
            by_name.setdefault(nm, p)
        for fl in p.get("flags") or []:
            f = fl.lstrip("-").lower()
            if f:
                by_flag.setdefault(f, p)

    if not params:
        # 该工具无参数定义（极少见），退化为把每个键当裸 --key=value 直接透传
        args: list[str] = []
        for k, v in parameters.items():
            if v is None or isinstance(v, bool) and not v:
                continue
            flag = "--" + k.strip().lower().replace(" ", "_")
            args.append(flag if isinstance(v, bool) else f"{flag}={v}")
        return args, {}

    args = []
    used_params: set[int] = set()
    unknown_keys: list[str] = []
    for key, value in parameters.items():
        k = key.strip().lower().replace(" ", "_")
        pdef = by_name.get(k) or by_flag.get(k)
        if pdef is None:
            unknown_keys.append(key)
            continue
        used_params.add(id(pdef))
        flag = _pick_flag(pdef)
        if flag is None:
            unknown_keys.append(key)
            continue
        # 布尔/Flag 型
        if _is_flag_param(pdef) or isinstance(value, bool):
            if value:
                args.append(flag)  # 裸 flag
            continue
        if value is None:
            continue
        args.append(f"{flag}={value}")

    if unknown_keys:
        avail = ", ".join(
            f"{(p.get('flags') or ['?'])[0]} ({p.get('name', '')})"
            for p in params
        )
        return None, {
            "success": False,
            "error": f"未知参数关键字 {unknown_keys}。工具 '{tool_name}' 可用参数：{avail}",
        }

    # 缺必填检查
    missing = []
    for p in params:
        if p.get("optional", False):
            continue
        if id(p) in used_params:
            continue
        missing.append((p.get("flags") or ["?"])[0])
    if missing:
        avail = ", ".join(
            f"{(p.get('flags') or ['?'])[0]} ({p.get('name', '')}, "
            f"{'可选' if p.get('optional') else '必填'})"
            for p in params
        )
        return None, {
            "success": False,
            "error": f"缺少必填参数 {missing}。工具 '{tool_name}' 参数清单：{avail}",
        }

    return args, {}


def _pick_flag(pdef: dict[str, Any]) -> str | None:
    """取参数定义的长 flag（优先 --xxx，否则 -x）。"""
    flags = pdef.get("flags") or []
    longs = [f for f in flags if f.startswith("--")]
    if longs:
        return longs[0]
    for f in flags:
        if f.startswith("-"):
            return f
    return None


def _is_flag_param(pdef: dict[str, Any]) -> bool:
    """该参数是否为「无值 flag」（布尔开关）。"""
    pt = pdef.get("parameter_type")
    if isinstance(pt, str) and pt.lower() == "flag":
        return True
    if isinstance(pt, dict) and "flag" in {str(k).lower() for k in pt}:
        return True
    return False


# ─── 执行 ────────────────────────────────────────────────────────────────────


def _clean_whitebox_messages(raw_lines: list[str]) -> list[str]:
    """精简 whitebox 回吐的执行日志，只保留对 Agent/用户有信息量的行。"""
    out: list[str] = []
    for ln in raw_lines:
        s = ln.strip()
        if not s:
            continue
        if s.startswith(".") and "whitebox_tools" in s and "--run=" in s:
            continue
        if s.startswith("*") and set(s) <= {"*", " "}:
            continue
        if s.startswith("* Welcome to ") or s.startswith("* Powered by") or s.startswith("* www."):
            continue
        if s.startswith("Progress:") and s.endswith("%"):
            continue
        out.append(s)
    return out


def _tail_output_lines(messages: list[str], n: int = 3) -> list[str]:
    """取清理后 messages 的最后 n 行作为 output 摘要。"""
    tail = messages[-n:] if len(messages) >= n else messages[:]
    return tail


class _CallbackCollector:
    """收集 whitebox run_tool 经 callback 回吐的 stdout/stderr 文本。"""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, msg: Any) -> None:
        try:
            if isinstance(msg, bytes):
                msg = msg.decode("utf-8", errors="replace")
            elif not isinstance(msg, str):
                msg = str(msg)
            self.lines.append(msg)
        except Exception:  # noqa: BLE001 —— 收集器永不抛，避免 run_tool 中断
            self.lines.append("<undecodable line>")


async def _run_whitebox_tool(tool_name: str, args: list[str], timeout: int) -> dict[str, Any]:
    """在线程池中执行 wbt.run_tool，收集输出。

    whitebox 的 run_tool 是同步阻塞调用（Rust 子进程），用 asyncio.to_thread 下放，
    事件循环保持响应。超时则取消并返回超时错误。
    """
    wbt = _wbt()
    work_dir = os.environ.get("AGENT_WORK_DIR", os.getcwd())
    try:
        wbt.set_working_dir(work_dir)
    except Exception:  # noqa: BLE001
        pass
    wbt.verbose = True  # 让 callback 收到执行日志

    collector = _CallbackCollector()

    def _call() -> int:
        return wbt.run_tool(tool_name, args, callback=collector)

    try:
        ret = await asyncio.wait_for(asyncio.to_thread(_call), timeout=timeout)
    except asyncio.TimeoutError:
        return {
            "success": False,
            "result": None,
            "error": f"工具执行超时（上限 {timeout} 秒）",
        }

    success = int(ret) == 0
    messages = _clean_whitebox_messages(collector.lines)
    tail = _tail_output_lines(messages, n=3)
    return {
        "success": success,
        "result": None,
        "messages": messages,
        "returncode": int(ret),
        "output": "\n".join(tail),
        "error": None if success else f"工具 '{tool_name}' 执行失败（退出码 {ret}）。\n" + "\n".join(tail or messages[-5:]),
    }


# ─── GDB 路径识别与矢量/栅格判定 ──────────────────────────────────────────────
def _is_gdb_logical_path(path: str) -> bool:
    """判断路径是否为 GDB 内逻辑图层（如 'xxx.gdb/图层名'）。"""
    p = path.replace("\\", "/")
    low = p.lower()
    idx = low.find(".gdb/")
    if idx < 0:
        return False
    suffix = p[idx + 5:]  # .gdb/ 之后的部分
    # .shp / .tif 等文件扩展名 -> 不是 GDB 逻辑图层（是 .gdb 目录下的普通文件）
    if suffix.lower().endswith((".shp", ".tif", ".tiff", ".csv", ".txt", ".geojson")):
        return False
    # 纯图层名（无扩展名）-> GDB 逻辑图层（矢量要素类或栅格数据集）
    return bool(suffix.strip())


# 旧名兼容（语义不变：GDB 逻辑路径即要素类候选）
_is_gdb_feature_class = _is_gdb_logical_path


def _kind_from_ptype(pt: Any) -> str | None:
    """从 whitebox 参数的 parameter_type 解析数据类型：'Vector' / 'Raster' / None。"""
    if not isinstance(pt, dict):
        return None
    for _top, sub in pt.items():
        if isinstance(sub, dict):
            for kk in sub:
                kl = str(kk).lower()
                if kl == "vector":
                    return "Vector"
                if kl == "raster":
                    return "Raster"
        elif isinstance(sub, str):
            sl = sub.lower()
            if sl == "vector":
                return "Vector"
            if sl == "raster":
                return "Raster"
    return None


def _param_kind(tool_name: str, key: str) -> str | None:
    """取某参数的矢量/栅格类型（按参数名或 flag 匹配，大小写不敏感）。"""
    params = _tool_params(tool_name)
    k = key.strip().lower().replace(" ", "_")
    for p in params:
        nm = (p.get("name") or "").strip().lower().replace(" ", "_")
        flags = [f.lstrip("-").lower() for f in (p.get("flags") or [])]
        if k == nm or k in flags:
            return _kind_from_ptype(p.get("parameter_type"))
    return None


def _gdb_fc_to_temp_shp(gdb_fc_path: str) -> tuple[str, str | None]:
    """把 GDB 要素类转为临时 .shp 供 whitebox 使用（矢量输入桥接）。"""
    import tempfile

    datasource, layer = _split_path(gdb_fc_path)
    if not layer:
        return "", f"无法解析 GDB 要素类路径: {gdb_fc_path}"
    try:
        import pyogrio  # type: ignore

        df = pyogrio.read_dataframe(datasource, layer=layer)
    except Exception as e:  # noqa: BLE001
        return "", f"读取 GDB 要素类 '{gdb_fc_path}' 失败: {e}"
    if df is None or df.empty:
        return "", f"GDB 要素类 '{gdb_fc_path}' 为空或无数据"

    tmp_dir = tempfile.mkdtemp(prefix="gdb2shp_")
    # 用安全的 ASCII 文件名，避免 whitebox/Windows 对中文路径的问题
    safe_name = "gdb_input.shp"
    shp_path = os.path.join(tmp_dir, safe_name)
    try:
        import pyogrio  # type: ignore

        pyogrio.write_dataframe(df, shp_path)
    except Exception as e:  # noqa: BLE001
        return "", f"写出临时 .shp 失败: {e}"
    return shp_path, None


def _gdb_raster_to_temp_tif(gdb_raster_path: str) -> tuple[str, str | None]:
    """把 GDB 栅格数据集转为临时 .tif 供 whitebox 使用。

    GDAL OpenFileGDB 驱动仅支持矢量，无法读取 GDB 内栅格数据集。
    """
    return (
        "",
        f"无法读取 GDB 内栅格数据集 '{gdb_raster_path}'：GDAL OpenFileGDB 驱动"
        f"仅支持矢量，不支持 GDB 栅格。请先用 ArcGIS 将该栅格导出为 .tif 后以 .tif 路径传入。",
    )


def _convert_gdb_inputs(
    parameters: dict[str, Any], tool_name: str
) -> tuple[dict[str, Any], list[str], str | None]:
    """扫描 parameters 中的输入路径，把 GDB 逻辑图层（xxx.gdb/图层名）桥接为临时文件。"""
    new_params = dict(parameters)
    temp_paths: list[str] = []
    # 输入路径参数的常见 key（whitebox 的 --input/-i/--dem 以及多输入）
    input_keys = {
        "input", "i", "inputs", "input1", "input2",
        "overlay", "clip", "overlay1", "overlay2",
        "in_features", "in_raster", "in_table", "in_dataset", "in_data",
        "dem", "dems", "dem1", "dem2",
    }
    for key, val in list(parameters.items()):
        if key.lower() not in input_keys:
            continue
        candidates = val if isinstance(val, list) else [val]
        converted: list[str] = []
        for c in candidates:
            if not isinstance(c, str) or not _is_gdb_logical_path(c):
                converted.append(c)
                continue
            kind = _param_kind(tool_name, key)
            if kind == "Raster":
                tif_path, err = _gdb_raster_to_temp_tif(c)
                if err:
                    return new_params, temp_paths, f"GDB 栅格输入转换失败 ({c}): {err}"
                converted.append(tif_path)
                temp_paths.append(tif_path)
            else:
                # Vector 或未知：先按矢量尝试
                shp_path, err = _gdb_fc_to_temp_shp(c)
                if err and kind is None:
                    # 未知类型且矢量失败，按栅格再试（同样会失败，但给出栅格语境错误）
                    tif_path, rerr = _gdb_raster_to_temp_tif(c)
                    if rerr:
                        return new_params, temp_paths, f"GDB 输入转换失败 ({c}): {rerr}"
                    converted.append(tif_path)
                    temp_paths.append(tif_path)
                elif err:
                    return new_params, temp_paths, f"GDB 矢量输入转换失败 ({c}): {err}"
                else:
                    converted.append(shp_path)
                    temp_paths.append(shp_path)
        new_params[key] = converted if isinstance(val, list) else converted[0]
    return new_params, temp_paths, None


# ─── GDB 输出桥接 ──────────────────────────────────────────────────────────────
# 输出参数的常见 key（whitebox --output/-o 及旧 out_*/output_* 命名）
_OUTPUT_KEYS = {
    "output", "out", "o",
    "out_feature_class", "out_raster", "out_table", "out_dataset",
    "output_features", "output_raster", "output_table", "output_dataset",
    "out_path", "out_location", "out_name",
}


def _redirect_gdb_outputs(
    parameters: dict[str, Any], tool_name: str, temp_dir: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """把 GDB 逻辑输出路径（xxx.gdb/图层名）重定向到临时文件，供 whitebox 写出。"""
    new_params = dict(parameters)
    redirects: list[dict[str, Any]] = []
    for key, val in list(parameters.items()):
        if key.lower() not in _OUTPUT_KEYS:
            continue
        if not isinstance(val, str) or not _is_gdb_logical_path(val):
            continue
        kind = _param_kind(tool_name, key) or "Vector"
        target = val
        idx = len(redirects)
        # 临时文件用 ASCII 名，规避 whitebox/Windows 中文路径问题
        ext = ".tif" if kind == "Raster" else ".shp"
        temp_path = os.path.join(temp_dir, f"out{idx}{ext}")
        new_params[key] = temp_path
        redirects.append({"temp": temp_path, "target": target, "kind": kind, "key": key})
    return new_params, redirects


def _shp_to_gdb_fc(shp_path: str, gdb_fc_path: str) -> tuple[bool, str | None]:
    """把 .shp 写入 GDB 要素类（矢量输出桥接，无 arcpy）。"""
    datasource, layer = _split_path(gdb_fc_path)
    if not layer:
        return False, f"无法解析 GDB 要素类输出路径: {gdb_fc_path}"
    try:
        import pyogrio  # type: ignore

        df = pyogrio.read_dataframe(shp_path)
    except Exception as e:  # noqa: BLE001
        return False, f"读取临时 .shp '{shp_path}' 失败: {e}"
    if df is None or df.empty:
        return False, f"临时 .shp '{shp_path}' 为空，无可写入要素"
    try:
        import pyogrio  # type: ignore

        # 写入前确保 .gdb 父目录存在（write_dataframe 不会自建目录层级）
        gdb_parent = os.path.dirname(datasource)
        if gdb_parent:
            os.makedirs(gdb_parent, exist_ok=True)
        pyogrio.write_dataframe(
            df,
            datasource,
            layer=layer,
            driver="OpenFileGDB",
            layer_options={"TARGET_ARCGIS_VERSION": "ARCGIS_PRO_3_2_OR_LATER"},
        )
    except Exception as e:  # noqa: BLE001
        return False, f"写入 GDB 要素类 '{gdb_fc_path}' 失败: {e}"
    return True, None


def _tif_to_gdb_raster(
    tif_path: str, gdb_raster_path: str
) -> tuple[bool, str | None, str | None]:
    """把 .tif 写入 GDB 栅格数据集（栅格输出桥接，无 arcpy）。

    GDAL OpenFileGDB 驱动明确不支持栅格写入。
    故采用降级：将 .tif 复制为 GDB 目录旁的同名 .tif，保留计算结果。
    """
    import shutil

    datasource, layer = _split_path(gdb_raster_path)
    if not layer:
        return False, f"无法解析 GDB 栅格输出路径: {gdb_raster_path}", None
    # 先尝试直接写入 GDB 栅格（预期失败，但保留以适配未来 GDAL 支持）
    try:
        import rasterio  # type: ignore

        with rasterio.open(tif_path) as src:
            profile = src.profile.copy()
            data = src.read()
        profile.update(driver="OpenFileGDB")
        with rasterio.open(datasource, "w", **profile) as dst:
            dst.write(data)
        return True, None, gdb_raster_path
    except Exception as e:  # noqa: BLE001
        # 降级：复制 tif 到 GDB 目录旁
        gdb_dir = datasource
        fallback = os.path.join(gdb_dir, f"{layer}.tif")
        try:
            os.makedirs(gdb_dir, exist_ok=True)
            shutil.copy2(tif_path, fallback)
        except Exception as ce:  # noqa: BLE001
            return False, f"GDAL 不支持写 GDB 栅格，且降级复制失败: {e} / {ce}", None
        return False, (
            f"GDAL OpenFileGDB 不支持写入 GDB 栅格数据集（{e}）。"
            f"已降级保留为 .tif：{fallback}"
        ), fallback


def _finalize_gdb_outputs(redirects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """whitebox 执行后，把临时输出文件转入 GDB 目标。"""
    results: list[dict[str, Any]] = []
    for r in redirects:
        temp, target, kind = r["temp"], r["target"], r["kind"]
        if not os.path.exists(temp):
            results.append({
                "target": target, "final_path": target, "kind": kind,
                "success": False, "error": f"whitebox 未生成预期输出文件: {temp}",
            })
            continue
        if kind == "Raster":
            ok, err, fb = _tif_to_gdb_raster(temp, target)
            results.append({
                "target": target, "final_path": fb or target, "kind": kind,
                "success": ok, "error": err,
            })
        else:
            ok, err = _shp_to_gdb_fc(temp, target)
            results.append({
                "target": target, "final_path": target, "kind": kind,
                "success": ok, "error": err,
            })
    return results


# 工作区路径底线：MCP 进程自身的 fail-closed 校验（Hook 是附加层，不是安全边界）。
# 受设置页「输出路径严格限制」（pathRestrict）实时控制：关闭时输入/输出路径
# 不作任何限制（不限于 01/02/03 子目录，也不限于 AGENT_WORK_DIR）。
_PATH_KEY_MARKERS = ("path", "file", "folder", "workspace", "input", "output", "raster", "vector", "features", "dataset", "clip")
_OUTPUT_KEY_MARKERS = ("out", "output", "target", "destination", "result")


def _require_workspace_path(path: str, *, writable: bool = False) -> str:
    """Resolve *path* and, when 严格限制 is on, fail closed unless it is inside
    this conversation's workspace (writable keys additionally restricted to
    02_WorkSpace/03_Result).

    This check lives in the MCP process itself. Hooks and prompts are additional
    policy layers, not the security boundary. The switch is re-read per call so
    settings-page flips apply to live sessions without restarting the server.
    """
    if not isinstance(path, str) or not path.strip():
        raise PermissionError("empty path is not allowed")
    root = os.path.realpath(os.environ.get("AGENT_WORK_DIR", os.getcwd()))
    raw = os.path.expanduser(path.strip())
    target = os.path.realpath(raw if os.path.isabs(raw) else os.path.join(root, raw))
    if not _path_restrict():
        return target
    try:
        if os.path.commonpath([root, target]) != root:
            raise PermissionError("path is outside the current conversation workspace")
    except ValueError as exc:
        raise PermissionError("path is on a different filesystem") from exc
    relative = os.path.relpath(target, root)
    top = relative.split(os.sep, 1)[0].lower()
    allowed = {"02_workspace", "03_result"} if writable else {"01_databackup", "02_workspace", "03_result"}
    if top not in allowed:
        raise PermissionError("path is outside the authorized workspace subdirectories")
    return target


def _validate_tool_paths(value: Any, key: str = "") -> None:
    if isinstance(value, dict):
        for child_key, child in value.items():
            _validate_tool_paths(child, str(child_key))
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            _validate_tool_paths(child, key)
        return
    if not isinstance(value, str):
        return
    lower_key = key.lower()
    looks_like_path = any(marker in lower_key for marker in _PATH_KEY_MARKERS)
    looks_like_path = looks_like_path or os.path.isabs(value) or ".." in value.replace("\\", "/").split("/")
    if not looks_like_path:
        return
    writable = any(lower_key.startswith(marker) or marker in lower_key for marker in _OUTPUT_KEY_MARKERS)
    _require_workspace_path(value, writable=writable)


@mcp.tool()
async def execute_gis_tool(tool_name: str, parameters: dict) -> str:
    """
    执行 GIS 工具（五类引擎统一入口，降级链：内置(inner) → whitebox(wbt) → gdal → qgis → arcpy）。

    tool_name 可：
      - 裸名：按 inner→wbt→gdal→qgis→arcpy 自动降级
        （如 `clip`→whitebox、`buffer`→内置、`gdal:translate`→gdal、`native:buffer`→qgis、
        `arcpy.analysis.Clip`→arcpy）。
      - 加前缀强制引擎：`inner_<name>`、`wbt_<name>`、`gdal_<gdal:tool>`、`qgis_<provider:algo>`、
        `arcpy_<arcpy.模块.工具名>`（如 `gdal_gdal:translate`、`qgis_native:buffer`）。
        带前缀时仅在该引擎内解析，不降级。

    Args:
        tool_name: 工具名（裸名降级，或带 inner_/wbt_/gdal_/qgis_/arcpy_ 前缀强制）。
        parameters: 工具参数关键字字典，key 大小写不敏感。
            whitebox 示例（clip）：{"input": ".../a.shp", "clip": ".../b.shp", "output": ".../out.shp"}
            内置示例（buffer）：{"input": ".../admin.shp", "distance": 100, "output": ".../buf.shp"}
            gdal 示例（gdal:translate）：{"input": ".../in.tif", "output": ".../out.tif"}
            qgis 示例（native:buffer）：{"INPUT": ".../in.shp", "DISTANCE": 50, "OUTPUT": ".../out.shp"}
            arcpy 示例：{"tool_name": "arcpy.analysis.Buffer", "parameters": {"in_features": "...", "out_feature_class": "..."}}

    Returns:
        JSON 字符串，含 success / result / messages / output / error / engine，
        以及 output_summary（空间输出经 GDAL 转 WGS84 GeoJSON 嵌入，超阈值降级为摘要）。
    """
    try:
        _validate_tool_paths(parameters or {})
    except PermissionError as exc:
        return json.dumps({"success": False, "error": f"workspace policy denied tool parameters: {exc}"}, ensure_ascii=False)

    # 0. 五引擎统一解析（每次调用实时读取引擎开关）
    resolved_engine = _resolve_engine(tool_name)
    if resolved_engine is None:
        # 区分「开关关闭」与「未知名」两种失败，给出不同的修复指引。
        n = _normalize_tool_name(tool_name)
        disabled_hit = None
        if n.startswith("inner_") and _normalize_tool_name(tool_name[6:]) in _INNER_NAMES:
            disabled_hit = "inner"
        elif n.startswith("wbt_") and _resolve_tool_name(tool_name[4:]):
            disabled_hit = "wbt"
        elif n.startswith("gdal_"):
            algo = tool_name[5:].strip().lower()
            algo = algo if algo.startswith("gdal:") else f"gdal:{algo}"
            if algo in _GDAL_NAMES:
                disabled_hit = "gdal"
        elif n.startswith("qgis_") and tool_name[5:].strip().lower() in list_qgis_algorithms():
            disabled_hit = "qgis"
        elif n.startswith("arcpy") and _arcpy_tool_exists(tool_name.replace("arcpy_", "arcpy.")):
            disabled_hit = "arcpy"
        else:
            for engine, probe in (
                ("inner", lambda: _normalize_tool_name(tool_name) in _INNER_NAMES),
                ("wbt", lambda: bool(_resolve_tool_name(tool_name))),
                ("gdal", lambda: _normalize_tool_name(tool_name).startswith("gdal:") and _normalize_tool_name(tool_name) in _GDAL_NAMES),
                ("qgis", lambda: ":" in _normalize_tool_name(tool_name) and _normalize_tool_name(tool_name) in list_qgis_algorithms()),
                ("arcpy", lambda: _arcpy_tool_exists(tool_name) and arcpy_available()),
            ):
                try:
                    if probe():
                        disabled_hit = engine
                        break
                except Exception:  # noqa: BLE001
                    continue
        if disabled_hit and not _ENGINE_ENABLED[disabled_hit]():
            return json.dumps({
                "success": False, "result": None, "engine": disabled_hit, "tool_name": tool_name,
                "error": _engine_disabled_reason(disabled_hit),
            }, ensure_ascii=False, indent=2)

        suggestions = _suggest_all(tool_name)
        result = {
            "success": False,
            "result": None,
            "error": (
                f"未知工具名 '{tool_name}'：不属于 内置(inner)/whitebox/gdal/qgis/arcpy 任一引擎。\n"
                f"可用 list_available_tools(source='all', keyword=...) 查询。\n"
                f"建议——内置: {suggestions['inner'] or '（无）'}\n"
                f"      whitebox: {suggestions['wbt'] or '（无）'}\n"
                f"      gdal: {suggestions['gdal'] or '（无）'}\n"
                f"      qgis: {suggestions['qgis'] or '（无）'}"
            ),
            "suggestions": suggestions,
        }
        return json.dumps(result, ensure_ascii=False, indent=2)

    engine, canon = resolved_engine

    # ── 引擎：inner（内置纯 Python）──────────────────────────────────────────
    if engine == "inner":
        try:
            result = await asyncio.to_thread(_dispatch_custom_tool, canon, parameters or {})
        except Exception as e:  # noqa: BLE001
            result = {"success": False, "output": None, "error": f"内置工具 '{canon}' 执行异常: {e}",
                      "messages": [], "output_paths": []}
        result.setdefault("success", False)
        result.setdefault("tool_name", canon)
        result.setdefault("engine", "inner")
        output_paths = list(result.pop("output_paths", []) or [])
        return await _postprocess_and_serialize(result, output_paths, canon, parameters)

    # ── 引擎：gdal（直执行：rasterio/pyogrio + 必要时 GDAL CLI）──────────────
    if engine == "gdal":
        try:
            result = await _dispatch_gdal_tool(canon, parameters or {})
        except Exception as e:  # noqa: BLE001
            result = {"success": False, "output": None, "error": f"GDAL 工具 '{canon}' 执行异常: {e}",
                      "messages": [], "output_paths": []}
        result.setdefault("success", False)
        result.setdefault("tool_name", canon)
        result.setdefault("engine", "gdal")
        output_paths = list(result.pop("output_paths", []) or [])
        return await _postprocess_and_serialize(result, output_paths, canon, parameters)

    # ── 引擎：qgis（后备）─────────────────────────────────────────────────────
    if engine == "qgis":
        request_started = time.perf_counter()
        dispatch_started = time.perf_counter()
        try:
            result = await _dispatch_qgis_tool(canon, parameters or {})
        except Exception as e:  # noqa: BLE001
            result = {"success": False, "output": None, "error": f"QGIS 算法 '{canon}' 执行异常: {e}",
                      "messages": [], "output_paths": []}
        dispatch_seconds = time.perf_counter() - dispatch_started
        result.setdefault("success", False)
        result.setdefault("tool_name", canon)
        result.setdefault("engine", "qgis")
        output_paths = list(result.pop("output_paths", []) or [])
        audit = result.setdefault("audit", {})
        if isinstance(audit, dict):
            audit["server_dispatch_seconds"] = dispatch_seconds
            audit["server_before_postprocess_seconds"] = time.perf_counter() - request_started
        serialized = await _postprocess_and_serialize(result, output_paths, canon, parameters)
        if isinstance(audit, dict):
            audit["server_total_seconds"] = time.perf_counter() - request_started
            logger.info("[qgis-audit] server_completed algo=%s audit=%s", canon, audit)
            # Serialize one final time so server_total_seconds is visible to the
            # caller and to the PostToolUse audit hook.
            serialized = json.dumps(result, ensure_ascii=False, indent=2)
        return serialized

    # ── 引擎：arcpy（ArcGIS Pro 持久 worker）──────────────────────────────────
    if engine == "arcpy":
        try:
            result = await _run_arcpy_tool(canon, parameters or {})
        except Exception as e:  # noqa: BLE001
            result = {"success": False, "output": None, "error": f"ArcPy 工具 '{canon}' 执行异常: {e}",
                      "messages": [], "output_paths": []}
        result.setdefault("success", False)
        result.setdefault("tool_name", canon)
        result.setdefault("engine", "arcpy")
        output_paths = list(result.pop("output_paths", []) or [])
        return await _postprocess_and_serialize(result, output_paths, canon, parameters)

    # ── 引擎：wbt（WhiteboxTools）─────────────────────────────────────────────
    resolved = canon
    # 2. GDB 输入桥接：whitebox 不支持 xxx.gdb/图层名，按矢量/栅格桥接为临时 .shp/.tif。
    effective_params, temp_shps, gdb_err = _convert_gdb_inputs(parameters or {}, resolved)
    if gdb_err:
        return json.dumps({"success": False, "result": None, "engine": "wbt",
                           "tool_name": resolved, "error": gdb_err}, ensure_ascii=False, indent=2)

    # 拓扑兼容性：剔除 _topo_skip 控制键（不透传给 whitebox 当未知参数）。
    topo_log: dict[str, Any] = {"enabled": topo_enabled(parameters or {})}
    if TOPO_SKIP_KEY in effective_params:
        effective_params.pop(TOPO_SKIP_KEY, None)

    # 3. GDB 输出桥接：把 xxx.gdb/图层名 重定向到临时 .shp(矢量)/.tif(栅格)，
    #    whitebox 写临时文件，执行后由 _finalize_gdb_outputs 转入 GDB。
    import tempfile

    out_temp_dir = tempfile.mkdtemp(prefix="gdbout_")
    effective_params, redirects = _redirect_gdb_outputs(effective_params, resolved, out_temp_dir)

    # 3.5 PRE 拓扑检查/修复（best-effort，永不阻断）
    if topo_log["enabled"]:
        try:
            topo_log["pre"] = await _topo_pre_pass(effective_params, resolved, out_temp_dir)
        except Exception as topo_err:  # noqa: BLE001
            topo_log["pre"] = {"error": str(topo_err)}
            logger.warning("[execute_gis_tool] topology PRE pass failed: %s", topo_err)

    # 4. 参数映射
    args, err = _build_arg_list(resolved, effective_params)
    if err:
        _cleanup_temp_dirs(temp_shps, out_temp_dir)
        err.setdefault("engine", "wbt")
        err.setdefault("tool_name", resolved)
        return json.dumps(err, ensure_ascii=False, indent=2)

    # 5. 执行
    result = await _run_whitebox_tool(resolved, args, EXECUTE_GIS_TOOL_TIMEOUT_SECONDS)

    # 6. 清理输入侧临时 .shp（best-effort，失败不阻塞）
    for tmp_shp in temp_shps:
        try:
            import shutil

            shutil.rmtree(os.path.dirname(tmp_shp), ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass

    # 7. GDB 输出收尾：临时文件 -> GDB 目标（矢量写 FC；栅格降级保留同名 .tif）
    finalize_results: list[dict[str, Any]] = []
    if redirects:
        finalize_results = _finalize_gdb_outputs(redirects)
        fin_errors = [f["error"] for f in finalize_results if f.get("error")]
        if fin_errors:
            note = "GDB 输出收尾：" + " | ".join(fin_errors)
            existing = result.get("error") or ""
            result["error"] = (existing + "\n" + note).strip() if existing else note
            result["gdb_output_finalize"] = finalize_results

    # 8. 计算最终输出路径（GDB 目标，或栅格降级后的 .tif）
    output_paths = _compute_output_paths(parameters or {}, finalize_results)

    # 8.5 POST 拓扑检查/修复（best-effort，永不阻断）
    if topo_log["enabled"]:
        try:
            topo_log["post"] = await _topo_post_pass(effective_params, resolved, output_paths)
        except Exception as topo_err:  # noqa: BLE001
            topo_log["post"] = {"error": str(topo_err)}
            logger.warning("[execute_gis_tool] topology POST pass failed: %s", topo_err)

    # 把拓扑日志挂到结果（无论 enabled 与否，都回传以利可观测；关闭时仅含 enabled:False）
    result["topology"] = topo_log
    _summarize_topology_into(result, topo_log)

    # 清理输出侧临时文件（收尾已完成，临时 .shp/.tif 不再需要）+ PRE 拓扑修复副本目录。
    try:
        import shutil

        shutil.rmtree(out_temp_dir, ignore_errors=True)
        work_dir = os.environ.get("AGENT_WORK_DIR", os.getcwd())
        shutil.rmtree(os.path.join(work_dir, "02_WorkSpace", ".topo_tmp"), ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass

    result.setdefault("tool_name", resolved)
    result.setdefault("engine", "wbt")
    # 9–11. 统一后处理（写 .gis-result.json + 嵌入 GeoJSON + 序列化）。
    return await _postprocess_and_serialize(result, output_paths, resolved, parameters)


async def _postprocess_and_serialize(
    result: dict[str, Any], output_paths: list[str], tool_name: str,
    parameters: dict[str, Any] | None = None,
) -> str:
    """各引擎共用的后处理 + JSON 序列化。

    - 写 <work_dir>/02_WorkSpace/.gis-result.json（auto-push-hook 主信号源，失败静默）；
    - 对矢量输出嵌入首份 GeoJSON 摘要；栅格输出只写路径摘要（embed_geojson 仅支持矢量）；
    - 返回 json.dumps(result)。
    """
    # .gis-result.json 信号源（auto-push-hook 读取）
    try:
        work_dir = os.environ.get("AGENT_WORK_DIR", os.getcwd())
        result_meta_dir = os.path.join(work_dir, "02_WorkSpace")
        os.makedirs(result_meta_dir, exist_ok=True)
        result_meta_path = os.path.join(result_meta_dir, ".gis-result.json")
        with open(result_meta_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "tool_name": tool_name,
                    "output_paths": output_paths,
                    "parameters": parameters or {},
                },
                f,
                ensure_ascii=False,
            )
    except Exception:  # noqa: BLE001
        pass

    # 嵌入第一个空间输出的 GeoJSON（矢量）；栅格仅设路径摘要
    if result.get("success") and output_paths:
        first = output_paths[0]
        if _is_vector_output(first):
            try:
                conv = embed_geojson(first, max_records=5000)
                if conv.get("success"):
                    feat_count = conv.get("count", 0)
                    result["output_summary"] = (
                        f"输出 {feat_count} 个要素，GeoJSON 已生成（{first}）"
                    )
                    logger.info(
                        "[execute_gis_tool] GeoJSON ready: %d features for %s",
                        feat_count, first,
                    )
                else:
                    result["output_summary"] = "输出已生成，GeoJSON 转换跳过"
                    logger.warning("[execute_gis_tool] GeoJSON conversion skipped: %s", conv.get("error"))
            except Exception as geo_err:  # noqa: BLE001
                result["output_summary"] = "输出已生成"
                logger.warning("[execute_gis_tool] GeoJSON embedding failed: %s", geo_err)
        else:
            result["output_summary"] = f"栅格输出已生成（{first}）"

    return json.dumps(result, ensure_ascii=False, indent=2)


def _is_vector_output(path: str) -> bool:
    """输出首路径是否为矢量（.shp 或 GDB 逻辑图层）；栅格扩展名返回 False。"""
    p = str(path).replace("\\", "/").lower()
    if p.endswith((".tif", ".tiff", ".vrt", ".img", ".asc", ".grd")):
        return False
    return p.endswith(".shp") or _is_gdb_logical_path(p)


def _cleanup_temp_dirs(temp_shps: list[str], out_temp_dir: str) -> None:
    """best-effort 清理输入/输出临时目录（参数校验失败时调用，失败不阻塞）。"""
    import shutil

    for tmp_shp in temp_shps:
        try:
            shutil.rmtree(os.path.dirname(tmp_shp), ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass
    try:
        shutil.rmtree(out_temp_dir, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass
    try:
        work_dir = os.environ.get("AGENT_WORK_DIR", os.getcwd())
        shutil.rmtree(os.path.join(work_dir, "02_WorkSpace", ".topo_tmp"), ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass


def _compute_output_paths(
    parameters: dict[str, Any], finalize_results: list[dict[str, Any]]
) -> list[str]:
    """从 parameters 提取输出路径，GDB 逻辑路径替换为收尾后的最终可用路径。"""
    by_target = {f["target"]: f for f in finalize_results}
    candidates: list[str] = []
    for key, val in parameters.items():
        if key.lower() not in _OUTPUT_KEYS:
            continue
        if not val:
            continue
        vals = val if isinstance(val, list) else [val]
        for v in vals:
            if not isinstance(v, str) or not v:
                continue
            if v in by_target:
                candidates.append(by_target[v]["final_path"])
            else:
                candidates.append(v)
    return candidates


# ─── 拓扑检查/修复：输入/输出路径枚举与 PRE/POST 编排 ──────────────────────────
# 输入路径参数的常见 key（与 _convert_gdb_inputs 同源，保持一致）。
_TOPO_INPUT_KEYS = {
    "input", "i", "inputs", "input1", "input2",
    "overlay", "clip", "overlay1", "overlay2",
    "in_features", "in_raster", "in_table", "in_dataset", "in_data",
    "dem", "dems", "dem1", "dem2",
}


def _topo_collect_vector_paths(
    parameters: dict[str, Any], tool_name: str, keys: set[str]
) -> list[tuple[str, str]]:
    """从 parameters 收集矢量输入/输出路径及其 key。"""
    collected: list[tuple[str, str]] = []
    for key, val in (parameters or {}).items():
        if key.lower() not in keys:
            continue
        candidates = val if isinstance(val, list) else [val]
        for c in candidates:
            if not isinstance(c, str) or not c.strip():
                continue
            if _param_kind(tool_name, key) == "Raster":
                continue
            collected.append((key, c))
    return collected


def _is_temp_shp(path: str, temp_dirs: tuple[str, ...]) -> bool:
    """路径是否落在某个临时目录内（GDB 桥接产物或本次 out_temp_dir）。"""
    try:
        norm = os.path.abspath(path)
        for d in temp_dirs:
            if d and os.path.abspath(d) in norm:
                return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _copy_to_workspace_temp(src: str, temp_dir: str) -> str:
    """把用户直传的 .shp 拷贝到工作区临时副本，返回副本路径（保护源数据）。"""
    import shutil

    os.makedirs(temp_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(src))[0]
    dst = os.path.join(temp_dir, f"{base}_topo.shp")
    src_noext, _ = os.path.splitext(src)
    dst_noext, _ = os.path.splitext(dst)
    for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
        s = src_noext + ext
        d = dst_noext + ext
        if os.path.exists(s):
            shutil.copy2(s, d)
    return dst


async def _topo_pre_pass(
    effective_params: dict[str, Any], tool_name: str, out_temp_dir: str | None
) -> dict[str, Any]:
    """PRE：扫描+修复矢量输入。best-effort，永不阻断。"""
    log: dict[str, Any] = {"inputs": []}
    work_dir = os.environ.get("AGENT_WORK_DIR", os.getcwd())
    topo_temp_root = os.path.join(work_dir, "02_WorkSpace", ".topo_tmp")
    # out_temp_dir 尚未创建时（本函数在 GDB 输出桥接前调用）用独立目录
    pre_temp_dir = os.path.join(topo_temp_root, "pre")
    temp_dirs = tuple([d for d in [pre_temp_dir] if d])

    vec_inputs = _topo_collect_vector_paths(effective_params, tool_name, _TOPO_INPUT_KEYS)
    for key, path in vec_inputs:
        entry: dict[str, Any] = {"key": key, "path": path}
        scan = scan_topology(path)
        entry["scan"] = {k: scan.get(k) for k in ("checked", "issues", "invalid", "empty", "null_geom")}
        if not scan.get("checked") or not scan.get("issues"):
            log["inputs"].append(entry)
            continue
        # 决定修复目标：临时 .shp 原地修；用户源 .shp 拷贝后修
        target = path
        if _is_gdb_logical_path(path):
            # GDB 逻辑路径经桥接已是 temp_shps；effective_params 里已是临时 .shp 路径
            target = path
        elif _is_temp_shp(path, (out_temp_dir or "",)):
            target = path
        else:
            try:
                target = _copy_to_workspace_temp(path, pre_temp_dir)
                # 把参数指向修复后的副本（值可能是 str 或 list）
                cur = effective_params.get(key)
                if isinstance(cur, list):
                    effective_params[key] = [target if v == path else v for v in cur]
                else:
                    effective_params[key] = target
                entry["repaired_in"] = target
            except Exception as copy_err:  # noqa: BLE001
                entry["repair_error"] = f"copy failed: {copy_err}"
                log["inputs"].append(entry)
                continue
        rep = await asyncio.to_thread(repair_topology, target, scan.get("reasons"))
        entry["repair"] = rep
        log["inputs"].append(entry)
    return log


async def _topo_post_pass(
    effective_params: dict[str, Any], tool_name: str, output_paths: list[str]
) -> dict[str, Any]:
    """POST：扫描+修复最终矢量输出。best-effort，永不阻断。"""
    log: dict[str, Any] = {"outputs": []}
    for path in output_paths:
        entry: dict[str, Any] = {"path": path}
        if _is_gdb_logical_path(path) or path.lower().endswith(".shp"):
            scan = scan_topology(path)
            entry["scan"] = {k: scan.get(k) for k in ("checked", "issues", "invalid", "empty", "null_geom")}
            if scan.get("checked") and scan.get("issues"):
                rep = await asyncio.to_thread(repair_topology, path, scan.get("reasons"))
                entry["repair"] = rep
        else:
            entry["scan"] = {"checked": False, "reason": "non-vector"}
        log["outputs"].append(entry)
    return log


def _summarize_topology_into(result: dict[str, Any], topo_log: dict[str, Any]) -> None:
    """若 PRE/POST 发生了修复，在 output_summary 追加一句中文提示，让 Agent 感知。"""
    if not topo_log.get("enabled"):
        return
    pre_repaired = post_repaired = 0
    for inp in (topo_log.get("pre") or {}).get("inputs", []):
        if (inp.get("repair") or {}).get("repaired"):
            pre_repaired += 1
    for outp in (topo_log.get("post") or {}).get("outputs", []):
        if (outp.get("repair") or {}).get("repaired"):
            post_repaired += 1
    if pre_repaired or post_repaired:
        note = f"已自动修复拓扑问题：输入 {pre_repaired} 处 / 输出 {post_repaired} 处"
        existing = result.get("output_summary")
        result["output_summary"] = (existing + " | " + note) if existing else note


# ─── 工具目录（list_tools + toolbox 分类）──────────────────────────────────────
# 进程级缓存：{snake_case_name: 分类}，来自 wbt.toolbox() 的 'CamelName:Category' 文本。
_TOOL_CATEGORY_CACHE: dict[str, str] | None = None


def _tool_categories() -> dict[str, str]:
    """取 {snake_case_name: 分类} 映射（来自 wbt.toolbox()，进程级缓存）。"""
    global _TOOL_CATEGORY_CACHE
    if _TOOL_CATEGORY_CACHE is None:
        try:
            raw = _wbt().toolbox()
            cat: dict[str, str] = {}
            for line in raw.splitlines():
                if ":" not in line:
                    continue
                camel, c = line.split(":", 1)
                snake = _camel_to_snake(camel.strip())
                if snake:
                    cat[snake] = c.strip()
            _TOOL_CATEGORY_CACHE = cat
        except Exception:  # noqa: BLE001
            _TOOL_CATEGORY_CACHE = {}
    return _TOOL_CATEGORY_CACHE


@mcp.tool()
async def list_available_tools(keyword: str = "", source: str = "all") -> str:
    """
    列出可用 GIS 工具，按引擎分类：内置(inner/纯Python) / whitebox(wbt) / gdal / qgis。

    **优先从 schema.json 缓存搜索**（启动时预生成），避免每次调用各引擎的 list 函数开销。
    若 schema.json 不存在或无效，降级为动态查询（首次调用触发生成）。

    Args:
        keyword: 可选过滤关键字（大小写不敏感，匹配 name 或 description）。为空则返回全部。
        source: 引擎筛选，取值：
            'all'      → 五类全列（默认）
            'inner'    → 仅内置纯 Python 工具（如 buffer/near/project）
            'wbt'      → 仅 WhiteboxTools 工具（whitebox snake_case，如 clip/intersect）
            'whitebox' → 同 'wbt'
            'gdal'     → 仅 GDAL 工具（gdal:前缀，如 gdal:translate/gdal:rasterize）
            'qgis'     → 仅 QGIS 处理算法（provider:algo，如 native:buffer）
        建议先按 keyword + 精确 source 聚焦，避免一次性灌入过大的列表。

    Returns:
        JSON 字符串，含 success / keyword / source / total / count / tools[]。
        每项含 name / engine / category / description。
    """
    kw = (keyword or "").strip().lower()
    src = (source or "all").strip().lower()
    if src == "whitebox":
        src = "wbt"
    valid = {"all", "inner", "wbt", "gdal", "qgis"}
    if src not in valid:
        src = "all"

    # 优先从 schema 缓存搜索（无 I/O，开销极低）
    schema = load_schema()
    if is_schema_valid(schema):
        items, totals = search_tools(schema, kw, src)
        # ArcPy 引擎不进 schema 缓存（工具集来自 ArcGIS Pro 安装，数量巨大）；
        # arcpy 查询提示走引擎探测。
        result = {
            "success": True,
            "keyword": kw or None,
            "source": src,
            "totals_by_engine": totals,
            "total": sum(totals.values()) if src == "all" else totals.get(src, 0),
            "count": len(items),
            "tools": items,
            "from_cache": True,
            "note": (
                "调用 execute_gis_tool 时：裸名按 inner→wbt→gdal→qgis→arcpy 自动降级；"
                "可用 inner_/wbt_/gdal_/qgis_/arcpy_ 前缀强制指定引擎。"
                "arcpy 工具不在此列表（按 ArcGIS Pro 工具箱命名直接调用，如 arcpy.analysis.Clip）。"
            ) if src == "all" else None,
        }
        return json.dumps(result, ensure_ascii=False, indent=2)

    # 降级：schema 无效时走旧逻辑（动态查询，首次触发生成 schema.json）
    items: list[dict[str, Any]] = []
    totals: dict[str, int] = {}

    # ── inner：内置纯 Python ──
    if src in ("all", "inner"):
        for cname, (_cfunc, cdesc) in CUSTOM_TOOL_REGISTRY.items():
            totals["inner"] = totals.get("inner", 0) + 1
            if kw and kw not in cname.lower() and kw not in (cdesc or "").lower():
                continue
            items.append({
                "name": cname,
                "engine": "inner",
                "category": "内置(纯Python)",
                "description": cdesc,
            })

    # ── wbt：WhiteboxTools ──
    if src in ("all", "wbt"):
        try:
            all_tools = _wbt().list_tools()
            categories = _tool_categories()
        except Exception as e:  # noqa: BLE001
            return json.dumps(
                {"success": False, "error": f"获取 whitebox 工具列表失败: {e}"},
                ensure_ascii=False, indent=2,
            )
        for name, desc in all_tools.items():
            totals["wbt"] = totals.get("wbt", 0) + 1
            if kw and kw not in name.lower() and kw not in (desc or "").lower():
                continue
            items.append({
                "name": name,
                "engine": "wbt",
                "category": categories.get(name, ""),
                "description": desc,
            })

    # ── gdal：GDAL 直执行 ──
    if src in ("all", "gdal"):
        galgos = list_gdal_algorithms()
        totals["gdal"] = len(galgos)
        for algo_id, info in galgos.items():
            desc = info.get("description", "") or info.get("name", "")
            if kw and kw not in algo_id.lower() and kw not in (desc or "").lower():
                continue
            items.append({
                "name": algo_id,
                "engine": "gdal",
                "category": f"GDAL/{info.get('group', '')}",
                "description": desc,
            })

    # ── qgis：QGIS 处理算法 ──
    if src in ("all", "qgis"):
        qalgos = list_qgis_algorithms()
        totals["qgis"] = len(qalgos)
        for algo_id, info in qalgos.items():
            desc = info.get("description", "") or info.get("name", "")
            if kw and kw not in algo_id.lower() and kw not in (desc or "").lower():
                continue
            items.append({
                "name": algo_id,
                "engine": "qgis",
                "category": f"QGIS/{info.get('provider', '')}",
                "description": desc,
            })

    result = {
        "success": True,
        "keyword": kw or None,
        "source": src,
        "totals_by_engine": totals,
        "total": sum(totals.values()) if src == "all" else totals.get(src, 0),
        "count": len(items),
        "tools": items,
        "from_cache": False,
        "note": (
            "调用 execute_gis_tool 时：裸名按 inner→wbt→gdal→qgis→arcpy 自动降级；"
            "可用 inner_/wbt_/gdal_/qgis_/arcpy_ 前缀强制指定引擎。"
        ) if src == "all" else None,
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_engine_status() -> str:
    """
    查询五个 GIS 引擎（inner / whitebox / gdal / qgis / arcpy）的开关与可用状态。

    引擎开关由设置页（LinkTool-GIS 引擎分组）实时写入开关文件；availability 为
    当前机器环境的探测结果（环境缺失时即使开关打开，调用也会返回清晰错误）。

    Returns:
        JSON 字符串：{success, engines: {inner: {enabled, available}, ...}, switch_file}
    """
    engines: dict[str, dict[str, Any]] = {}
    probes = (
        ("inner", lambda: bool(CUSTOM_TOOL_REGISTRY)),
        ("wbt", lambda: bool(_tool_names())),
        ("gdal", lambda: bool(GDAL_TOOL_CATALOG) and bool(gdal_available())),
        ("qgis", lambda: bool(qgis_available())),
        ("arcpy", lambda: bool(arcpy_available())),
    )
    for name, probe in probes:
        try:
            available = bool(probe())
        except Exception as probe_err:  # noqa: BLE001
            available = False
            logger.warning("[get_engine_status] %s probe failed: %s", name, probe_err)
        engines[name] = {"enabled": _engine_switch(name), "available": available}
    return json.dumps({
        "success": True,
        "engines": engines,
        "switch_file": _ENGINE_SWITCH_PATH,
    }, ensure_ascii=False, indent=2)


@mcp.tool()
async def list_gdb_contents(gdb_path: str) -> str:
    """
    列出 File Geodatabase（.gdb）或目录内的所有图层/表。

    通过内置 GDAL/OGR（OpenFileGDB 驱动）读取，不依赖任何外部引擎，
    返回字段形状与旧 arcpy 版本兼容：
    feature_classes / raster_datasets / tables / feature_datasets / other。

    Args:
        gdb_path: .gdb 目录的完整路径

    Returns:
        JSON 字符串，含 success / gdb_path / contents
    """
    try:
        gdb_path = _require_workspace_path(gdb_path)
    except PermissionError as exc:
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)
    result = list_gdb_layers(gdb_path)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def query_feature_attributes(
    feature_path: str,
    sql_where: str = "",
    max_records: int = 100,
    fields: Annotated[list[str] | None, BeforeValidator(_coerce_optional_list)] = None,
) -> str:
    """
    查询要素类/shapefile 的属性表（内置 GDAL/OGR 实现，不依赖外部引擎）。

    Args:
        feature_path: GDB 要素类路径（'<gdb>/图层名'）或 .shp 路径
        sql_where: 可选 SQL WHERE（不含 'WHERE' 关键字），如 "ZONE = 'R1' AND AREA > 1000"
        max_records: 最大返回记录数（默认 100，服务端硬上限 500）
        fields: 可选字段名子集（大小写不敏感匹配），省略则返回全部字段

    Returns:
        JSON 字符串，含 success / fields / data / total_records / returned_records
    """
    try:
        feature_path = _require_workspace_path(feature_path)
    except PermissionError as exc:
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)
    max_records = max(1, min(max_records, 500))
    result = query_attributes(feature_path, sql_where, max_records, fields)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_data_properties(data_path: str) -> str:
    """
    获取 GIS 数据集的元信息（内置 GDAL/OGR + rasterio 实现，不依赖外部引擎）。

    支持矢量（要素类/.shp）与栅格（.tif 等）。返回字段形状与旧 arcpy 版本兼容：
    data_type / extent / coordinate_system / fields / shape_type / feature_count /
    raster_properties / value_range。

    Args:
        data_path: 数据路径（GDB 要素类 / .shp / .tif）

    Returns:
        JSON 字符串，含数据元信息
    """
    try:
        data_path = _require_workspace_path(data_path)
    except PermissionError as exc:
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)
    result = data_properties(data_path)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_field_unique_values(
    feature_path: str, field_name: str, max_unique_values: int = 50
) -> str:
    """
    获取某字段的唯一值及计数（内置 GDAL/OGR 实现，不依赖外部引擎）。

    当唯一值数超过 max_unique_values 时，只返回计数（防上下文爆炸）；否则返回按计数降序的
    完整分解。

    Args:
        feature_path: 要素类 / .shp 路径
        field_name: 字段名（大小写不敏感）
        max_unique_values: 超阈值则跳过值分解（默认 50）

    Returns:
        JSON 字符串，含 unique_count / value_counts / field_info / total_records
    """
    try:
        feature_path = _require_workspace_path(feature_path)
    except PermissionError as exc:
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)
    max_unique_values = max(1, min(max_unique_values, 200))
    result = field_unique_values(feature_path, field_name, max_unique_values)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def create_gdb_database(gdb_path: str) -> str:
    """
    在指定路径创建空的 File Geodatabase（.gdb）（内置 GDAL OpenFileGDB 写支持，无外部引擎）。

    用于为后续 execute_gis_tool 的 'xxx.gdb/要素类' 输出预备容器；也可独立创建空库。
    实现以一个空占位要素类 _placeholder 引导建库（pyogrio 0.13 无法创建零图层 GDB、
    亦无图层删除 API）；该占位类为空（0 要素），不影响后续写入真实要素类。

    Args:
        gdb_path: 目标 .gdb 目录完整路径（须以 .gdb 结尾）。若已存在则跳过创建。

    Returns:
        JSON 字符串，含 success / gdb_path / created / note
    """
    try:
        gdb_path = _require_workspace_path(gdb_path, writable=True)
    except PermissionError as exc:
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)
    p = gdb_path.replace("\\", "/").strip()
    if not p.lower().endswith(".gdb"):
        return json.dumps(
            {"success": False, "error": f"路径须以 .gdb 结尾: {gdb_path}"},
            ensure_ascii=False, indent=2,
        )
    if os.path.exists(p):
        return json.dumps(
            {"success": True, "gdb_path": p, "created": False,
             "note": "GDB 已存在，跳过创建。"},
            ensure_ascii=False, indent=2,
        )
    parent = os.path.dirname(p)
    try:
        if parent:
            os.makedirs(parent, exist_ok=True)
    except Exception as e:  # noqa: BLE001
        return json.dumps(
            {"success": False, "error": f"创建父目录失败: {e}"},
            ensure_ascii=False, indent=2,
        )
    try:
        import geopandas as gpd  # type: ignore
        import pyogrio  # type: ignore

        # 空 GeoDataFrame + 显式 geometry_type 才能写出零要素图层，借此建立 .gdb 结构
        empty = gpd.GeoDataFrame(geometry=gpd.GeoSeries([], crs="EPSG:4326"))
        pyogrio.write_dataframe(
            empty, p, layer="_placeholder", driver="OpenFileGDB",
            geometry_type="Point",
            layer_options={"TARGET_ARCGIS_VERSION": "ARCGIS_PRO_3_2_OR_LATER"},
        )
    except Exception as e:  # noqa: BLE001
        return json.dumps(
            {"success": False, "error": f"创建 GDB 失败: {e}"},
            ensure_ascii=False, indent=2,
        )
    return json.dumps({
        "success": True, "gdb_path": p, "created": True,
        "note": "GDB 已创建（含空占位要素类 _placeholder，可忽略；"
                "后续 execute_gis_tool 写入 'xxx.gdb/要素类' 将自动新增真实要素类）。",
    }, ensure_ascii=False, indent=2)


def main():
    """Run the MCP server."""
    # 预生成 schema.json（各引擎工具列表缓存）。后台线程执行，不阻塞 stdio 与 mcp.run()。
    # schema_loader 在首次 list_available_tools 调用时若发现 schema 无效，会触发降级动态查询，
    # 同时此线程在后台完成 schema.json 生成，下次调用即从缓存直接搜索。
    schema_path = os.path.join(_THIS_DIR, "schema.json")
    set_schema_path(schema_path)

    def _generate_schema() -> None:
        try:
            from generate_schema import generate_schema as _gen  # type: ignore
            _gen(schema_path, force=False)
        except Exception as e:  # noqa: BLE001
            logger.warning("[arcgis-mcp-server] schema.json 生成失败: %s", e)

    # 预热 whitebox_tools.exe：Windows Defender 首次扫描 28MB Rust 二进制需 ~30-60s，
    # 在后台线程提前触发该扫描，使 MCP 连接等待期吸收这个一次性开销，首个
    # execute_gis_tool 调用时即热。仅触发 exe 启动+退出（run_tool 一个极轻量工具 list_tools）。
    def _prewarm() -> None:
        try:
            wbt = _wbt()
            wbt.list_tools()  # 触发 exe 首次启动，让 Defender 扫描在后台完成
        except Exception as e:  # noqa: BLE001
            logger.warning("[arcgis-mcp-server] prewarm failed: %s", e)
        # prewarm 完成后顺带生成 schema（whitebox 已热，generate_schema 可直接取 list_tools）
        _generate_schema()

    import threading

    if os.environ.get("ARCGIS_MCP_NO_PREWARM") != "1":
        threading.Thread(target=_prewarm, daemon=True).start()
    else:
        # 即使禁用 prewarm，也尝试生成 schema（复用既有 .venv 的 whitebox）
        threading.Thread(target=_generate_schema, daemon=True).start()

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
