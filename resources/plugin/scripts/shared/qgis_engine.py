# -*- coding: utf-8 -*-
"""QGIS 处理算法引擎（后备引擎，无 arcpy / 无 whitebox）。

以**进程内**方式（QgsApplication + processing 注册表）调用 QGIS 的 processing
算法（native / 3d / grass / saga / ...），作为 `execute_gis_tool` 在
「内置工具 -> whitebox -> gdal -> qgis」降级链的最后一环。算法列表与执行复用
同一个进程内 QGIS 运行时（进程级缓存），避免每次调用都付 QGIS 冷启动（~5-10s）。

设计要点：
- 兼容 QGIS 3.x LTR（Qt5/PyQt5，如 `QGIS 3.44.12`）与 4.x（Qt6/PyQt6）：
  `_find_qgis_bat` 探测任意安装根下的 `qgis_process*.bat`（正式版 / LTR 均可），
  `_configure_qgis_environment` 动态定位 `apps/qgis(-ltr)` 前缀与 `apps/qt5|qt6`。
- 关键：Python import `qgis._core` 前必须先预加载 `qgis_core.dll` 与 Qt 核心 DLL
  （否则 DLL load failed）；并把安装根下所有含 DLL 的目录加入 `add_dll_directory`。
- GDB 路径约定：项目内部用 `xxx.gdb/图层名`；QGIS 用 URI `xxx.gdb|layername=图层名`。
  本引擎在调用前双向转换，对外仍统一 `xxx.gdb/图层名` 约定。
- 进程级缓存算法列表与 help，避免重复初始化。
- QGIS 未安装时 `qgis_available()=False`，调用返回清晰错误，不阻断 MCP 服务启动。

模块级导入：本模块在 main.py 顶部已 import 过 geopandas/rasterio（GDAL C 扩展预热）
后才被延迟 import；`_configure_qgis_environment` 才加载 QGIS/Qt DLL。
"""

from __future__ import annotations

import ctypes
import glob
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 单次 qgis_process run 超时（秒）。与 execute_gis_tool 900s 对齐。
QGIS_RUN_TIMEOUT = 900

# 启动器探测：优先 QGIS_PROCESS_BAT 环境变量，其次任意 QGIS 安装根下的
# qgis_process*.bat（正式版 qgis_process-qgis.bat 或 LTR 版 qgis_process-qgis-ltr.bat 均可）。
_QGIS_GLOB = r"C:\Program Files\QGIS *\bin\qgis_process*.bat"

_QGIS_BAT: str | None = None
_QGIS_BAT_PROBED = False
_QGIS_APP: Any | None = None
_QGIS_PROCESSING: Any | None = None
_QGIS_INIT_LOCK = threading.Lock()

# 进程级缓存：{algo_id: {name, group, provider, description}}
_ALGO_CACHE: dict[str, dict[str, Any]] | None = None
# 进程级缓存：{algo_id: help_dict}
_HELP_CACHE: dict[str, dict[str, Any]] = {}


def _find_qgis_bat() -> str | None:
    """定位 qgis_process*.bat；找不到返回 None。进程级只探测一次。"""
    global _QGIS_BAT, _QGIS_BAT_PROBED
    if _QGIS_BAT_PROBED:
        return _QGIS_BAT
    _QGIS_BAT_PROBED = True

    env_path = os.environ.get("QGIS_PROCESS_BAT", "").strip()
    if env_path and os.path.isfile(env_path):
        _QGIS_BAT = env_path
        return _QGIS_BAT

    for c in glob.glob(_QGIS_GLOB):
        if os.path.isfile(c):
            _QGIS_BAT = c
            return _QGIS_BAT

    return None


def _find_qgis_prefix(root: Path) -> Path:
    """定位 QGIS Python 前缀目录：apps/qgis（正式版）或 apps/qgis-ltr（LTR 版）。"""
    for name in ("qgis", "qgis-ltr"):
        p = root / "apps" / name
        if p.is_dir() and (p / "python").is_dir():
            return p
    raise RuntimeError(f"未找到 QGIS Python 目录（apps/qgis 或 apps/qgis-ltr）：{root}")


def qgis_available() -> bool:
    """QGIS 是否可用（Windows 安装目录 / 已初始化的进程内运行时 / POSIX PATH 上的 qgis_process）。"""
    return _QGIS_APP is not None or _find_qgis_bat() is not None or _find_qgis_cli() is not None


def qgis_version() -> str | None:
    """QGIS 版本号（如 "3.44.12"）；未知返回 None。

    进程内运行时已初始化时直接读 Qgis.QGIS_VERSION；否则对
    qgis_process*.bat / PATH 上的 qgis_process 跑一次 `--version` 解析。
    只做展示用，失败不影响可用性判定。
    """
    if _QGIS_APP is not None:
        try:
            from qgis.core import Qgis  # type: ignore

            version = str(getattr(Qgis, "QGIS_VERSION", "") or "").strip()
            if version:
                match = re.search(r"(\d+\.\d+(?:\.\d+)?(?:\.\d+)?)", version)
                return match.group(1) if match else version
        except Exception:  # noqa: BLE001 —— 展示用途，失败降级到 CLI 探测
            pass
    launcher = _find_qgis_bat() or _find_qgis_cli()
    if not launcher:
        return None
    try:
        proc = subprocess.run(
            [launcher, "--version"], capture_output=True, text=True,
            timeout=60, env=_qgis_cli_env(),
        )
        output = f"{proc.stdout}\n{proc.stderr}"
        match = re.search(r"QGIS[^\d]*(\d+\.\d+(?:\.\d+)?(?:\.\d+)?)", output)
        return match.group(1) if match else None
    except Exception:  # noqa: BLE001
        return None


_QGIS_PY_LAUNCHER: str | None = None
_QGIS_PY_LAUNCHER_PROBED = False


def qgis_python_launcher() -> str | None:
    """QGIS 自带 Python 的启动器，用于**子进程**运行 PyQGIS 脚本（如 color-style 制图）。

    Windows 返回安装 bin 目录下的 python-qgis*.bat（o4w_env + QGIS_PREFIX_PATH +
    PYTHONPATH 全部就绪，PyQt ABI 与宿主无关）；POSIX 返回 PATH 上的 python3，
    且用一次极短探测（`python3 -c "import qgis"`）确认 PyQGIS 真正可 import
    （Debian 系需装 python3-qgis，缺包时 python3 存在但 import 失败）。
    不可用返回 None。进程级只探测一次（探测结果缓存，正常路径不被拖慢）。
    """
    global _QGIS_PY_LAUNCHER, _QGIS_PY_LAUNCHER_PROBED
    if _QGIS_PY_LAUNCHER_PROBED:
        return _QGIS_PY_LAUNCHER
    _QGIS_PY_LAUNCHER_PROBED = True
    if os.name != "nt":
        py = shutil.which("python3")
        if not py:
            logger.warning("[qgis] qgis_python_launcher: 未找到 python3")
            return None
        try:
            proc = subprocess.run(
                [py, "-c", "import qgis"], capture_output=True,
                timeout=30, env=_qgis_cli_env(),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("[qgis] qgis_python_launcher: 探测 `import qgis` 异常: %s", e)
            return None
        if proc.returncode != 0:
            logger.warning(
                "[qgis] qgis_python_launcher: %s 无法 import qgis（rc=%s）；"
                "POSIX 上运行 PyQGIS 需安装 python3-qgis（如 apt install python3-qgis）",
                py, proc.returncode,
            )
            return None
        _QGIS_PY_LAUNCHER = py
        return _QGIS_PY_LAUNCHER
    bat = _find_qgis_bat()
    candidates: list[str] = []
    if bat:
        bin_dir = Path(bat).parent
        candidates = sorted(glob.glob(str(bin_dir / "python-qgis*.bat")))
    if not candidates:
        candidates = sorted(glob.glob(r"C:\Program Files\QGIS *\bin\python-qgis*.bat"))
    if not candidates:
        candidates = sorted(glob.glob(r"C:\Program Files (x86)\QGIS *\bin\python-qgis*.bat"))
    _QGIS_PY_LAUNCHER = candidates[0] if candidates else None
    return _QGIS_PY_LAUNCHER


# ─── POSIX CLI 模式（Linux/macOS）─────────────────────────────────────────────
# 进程内 QgsApplication 初始化依赖 Windows OSGeo4W 目录结构（apps/qgis、WinDLL 预加载等），
# Linux/macOS 上不可行；改为经 CLI 子进程执行（list --json / run --json）。
# 注意：Debian/Ubuntu 的 /usr/bin/qgis_process 是 shell 包装脚本（source /etc/default/qgis
# 后转发参数），QGIS 3.22 上该脚本会透传一个 .bin 不认识的 `--noversioncheck` 直接失败；
# 真正的 ELF 可执行文件是同目录的 qgis_process.bin。发现逻辑按候选顺序探测，命中第一个可用者。
_QGIS_CLI: str | None = None
_QGIS_CLI_PROBED = False

# 输出参数的常见 key 提示（CLI 模式 JSON 解析失败时，据此从用户参数回填输出路径）
_OUTPUT_KEY_HINTS = ("out", "output", "destination", "sink", "result", "target")


def _qgis_cli_candidates() -> list[str]:
    """收集 qgis_process 启动器候选（POSIX，按优先级去重保持顺序）。

    1) 环境变量 QGIS_PROCESS_CLI（用户显式指定，可为绝对路径）；
    2) shutil.which("qgis_process")；
    3) Debian/Ubuntu 布局：若命中的是包装脚本，追加同目录的 <path>.bin
       （/usr/bin/qgis_process → /usr/bin/qgis_process.bin）。
    """
    candidates: list[str] = []
    env_path = os.environ.get("QGIS_PROCESS_CLI", "").strip()
    if env_path:
        candidates.append(env_path)
    which = shutil.which("qgis_process")
    if which:
        candidates.append(which)
        # Debian/Ubuntu 包装脚本 → 真实 ELF 可执行文件（同目录 <path>.bin）
        bin_path = which + ".bin"
        if bin_path not in candidates:
            candidates.append(bin_path)
    # 去重保持顺序，仅保留存在的文件
    seen: set[str] = set()
    out: list[str] = []
    for c in candidates:
        if c and c not in seen and os.path.isfile(c):
            seen.add(c)
            out.append(c)
    return out


def _probe_qgis_cli_candidate(cli: str) -> tuple[bool, str]:
    """探测一个候选启动器是否真正可用：跑 `--version`，要求 rc==0 且输出含 QGIS。

    Returns:
        (可用性, 失败原因)。可用时原因恒为空串。
    """
    try:
        proc = subprocess.run(
            [cli, "--version"], capture_output=True, text=True,
            timeout=30, env=_qgis_cli_env(),
        )
    except subprocess.TimeoutExpired:
        return False, "探测超时（>30s）"
    except FileNotFoundError:
        return False, "文件不存在"
    except Exception as e:  # noqa: BLE001
        return False, f"启动异常: {e}"
    output = f"{proc.stdout}\n{proc.stderr}"
    if proc.returncode != 0:
        return False, f"rc={proc.returncode}, stderr={(proc.stderr or '').strip()[:120]}"
    if "QGIS" not in output:
        return False, f"输出不含 QGIS 标识: {output.strip()[:120]}"
    return True, ""


def _find_qgis_cli() -> str | None:
    """POSIX：探测通过的 qgis_process 启动器（进程级只探一次，缓存第一个可用者）。

    Windows 返回 None（走 bat 进程内路径）。全部候选失败时记 warning 并列出
    各候选与失败原因，返回 None。
    """
    global _QGIS_CLI, _QGIS_CLI_PROBED
    if _QGIS_CLI_PROBED:
        return _QGIS_CLI
    _QGIS_CLI_PROBED = True
    if os.name == "nt":
        return None
    for cli in _qgis_cli_candidates():
        ok, reason = _probe_qgis_cli_candidate(cli)
        if ok:
            _QGIS_CLI = cli
            logger.info("[qgis] CLI mode via %s", cli)
            return _QGIS_CLI
        logger.warning("[qgis] 候选 qgis_process 不可用：%s（%s）", cli, reason)
    candidates = _qgis_cli_candidates()
    logger.warning(
        "[qgis] 未找到可用的 qgis_process 启动器；候选与失败原因：%s",
        "; ".join(f"{c}: {_probe_qgis_cli_candidate(c)[1]}" for c in candidates) or "（无候选）",
    )
    return None


def _ensure_utf8_cpg(path: str) -> None:
    """把 QGIS 产出的 .shp 同目录 .cpg 改写为 UTF-8（失败仅 warning，不影响分析结果）。

    原因：QGIS/Qt 写 ESRI Shapefile 时 .cpg 内容是 `system`（跟随系统 locale），
    而 GDAL 读端不认 `system`，会按 Latin-1 解码 → 中文字段名（如 `名称`）与属性值
    全部乱码（`å ç§`）。QGIS 内部实际按 UTF-8 编码写出，显式声明 UTF-8 即可正确读取。
    """
    try:
        p = str(path)
        if not p.lower().endswith(".shp"):
            return
        cpg = os.path.splitext(p)[0] + ".cpg"
        if os.path.isfile(cpg):
            with open(cpg, "r", encoding="ascii", errors="ignore") as f:
                content = (f.read() or "").strip()
            if content.lower() != "utf-8":
                with open(cpg, "w", encoding="ascii") as f:
                    f.write("UTF-8")
    except Exception as e:  # noqa: BLE001
        logger.warning("[qgis] 改写 .cpg 为 UTF-8 失败（%s）: %s", path, e)


def _qgis_cli_env() -> dict[str, str]:
    """qgis_process 子进程环境：headless 平台后端 + UTF-8 + GRASS 运行库。

    POSIX 直接调 qgis_process.bin（绕过 Debian 包装脚本）时，grass7 provider 的
    依赖库（libgrass_*）不在默认链接路径上；Debian 包装脚本靠 qgis-plugin-grass
    注入 LD_LIBRARY_PATH，这里用 glob 找系统 GRASS 运行库目录自行补上。
    """
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")  # 无显示环境（服务器）必需
    env.setdefault("GDAL_FILENAME_IS_UTF8", "YES")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    # GRASS 运行库（如 /usr/lib/grass78/lib）：命中才追加，已存在不重复加
    ld = env.get("LD_LIBRARY_PATH", "")
    existing = [p for p in ld.split(os.pathsep) if p]
    for grass_lib in sorted(glob.glob("/usr/lib/grass*/lib")):
        if os.path.isdir(grass_lib) and grass_lib not in existing:
            ld = grass_lib + (os.pathsep + ld if ld else "")
            existing.insert(0, grass_lib)
    if ld:
        env["LD_LIBRARY_PATH"] = ld
    return env


def _cli_json_output(stdout: str) -> dict[str, Any] | None:
    """从 qgis_process --json 输出稳健解析 JSON 对象。

    qgis_process 可能在 JSON 前后输出横幅/进度文本（随版本与终端差异）；
    从首个 '{' 起 raw_decode（允许尾部多余文本），失败返回 None。
    """
    s = (stdout or "").strip()
    if not s:
        return None
    start = s.find("{")
    if start < 0:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(s[start:])
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        return None


def _cli_list_algorithms(cli: str) -> dict[str, dict[str, Any]]:
    """`qgis_process list --json` 列出全部算法（POSIX CLI 模式）。

    与 generate_schema._export_qgis 同口径：gdal provider 除外（gdal:* 由 gdal
    引擎直执行接管，不在 qgis 段重复）。
    """
    try:
        proc = subprocess.run(
            [cli, "list", "--json"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=180, env=_qgis_cli_env(),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("[qgis] qgis_process list 异常: %s", e)
        return {}
    data = _cli_json_output(proc.stdout or "")
    if not isinstance(data, dict):
        logger.warning(
            "[qgis] qgis_process list 输出非 JSON（rc=%s）: %s",
            proc.returncode, (proc.stderr or proc.stdout or "")[:300],
        )
        return {}
    providers = data.get("providers") or {}
    catalog: dict[str, dict[str, Any]] = {}
    for prov_id, prov in providers.items():
        if prov_id == "gdal":
            continue
        for algo_id, info in ((prov or {}).get("algorithms") or {}).items():
            info = info or {}
            catalog[algo_id] = {
                "name": info.get("name", ""),
                "provider": prov_id,
                "group": info.get("group", ""),
                "description": info.get("short_description", "") or info.get("name", ""),
            }
    return catalog


def _looks_like_gis_path(v: str) -> bool:
    """字符串值是否形如 GIS 数据路径（GDB 逻辑路径或常见矢量/栅格扩展名）。"""
    vl = str(v).replace("\\", "/").lower()
    if ".gdb/" in vl or vl.endswith(".gdb"):
        return True
    return vl.endswith(
        (".shp", ".gpkg", ".geojson", ".tif", ".tiff", ".csv", ".parquet", ".fgb", ".vrt")
    )


def _cli_run_tool(cli: str | None, algo_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
    """`qgis_process run <algo> [--json] -- KEY=VALUE...` 执行算法（POSIX CLI 模式）。

    - 用户参数原样传 KEY=VALUE（大小写保留），GDB 逻辑路径转 QGIS URI；
    - `--json`（较新版本支持）失败/不支持时自动降级为无 JSON 重试，
      输出按用户显式传入的 out*/output* 路径回填（要求运行后真实存在）。
    """
    if not cli:
        return _fail("未找到 qgis_process 可执行文件。")
    kvs: list[str] = []
    user_out_paths: list[str] = []
    for k, v in (parameters or {}).items():
        if v is None:
            continue
        if isinstance(v, bool):
            kvs.append(f"{k}={'True' if v else 'False'}")
        elif isinstance(v, (list, tuple)):
            kvs.append(f"{k}={','.join(str(x) for x in v)}")
        elif isinstance(v, str):
            uri = _to_qgis_uri(v)
            kvs.append(f"{k}={uri}")
            if _looks_like_gis_path(v) and any(h in k.lower() for h in _OUTPUT_KEY_HINTS):
                user_out_paths.append(_from_qgis_uri(uri))
        else:
            kvs.append(f"{k}={v}")
    for p in user_out_paths:
        _ensure_parent_for_output(p)

    audit: dict[str, float] = {}
    started = time.perf_counter()

    def _invoke(with_json: bool):
        if os.name != "nt":
            # POSIX qgis_process（至少 QGIS 3.22）：KEY=VALUE 直接跟在 algo_id 后即可，
            # 加 `--` 分隔符会被当作"参数已结束、无参数"报 mandatory 缺失。Windows
            # OSGeo4W 的 qgis_process.bat 保留原 `--` 用法不变。
            cmd = [cli, "run"] + (["--json"] if with_json else []) + [algo_id] + kvs
        else:
            cmd = [cli, "run"] + (["--json"] if with_json else []) + [algo_id, "--"] + kvs
        return subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=QGIS_RUN_TIMEOUT, env=_qgis_cli_env(),
        )

    used_json = True
    try:
        proc = _invoke(with_json=True)
        if proc.returncode != 0 and "unknown option" in (proc.stderr or "").lower():
            # 旧版 qgis_process 不支持 run --json：降级重试
            used_json = False
            proc = _invoke(with_json=False)
    except subprocess.TimeoutExpired:
        return _fail(f"QGIS 算法 '{algo_id}' 执行超时（上限 {QGIS_RUN_TIMEOUT} 秒）。", audit=audit)
    except FileNotFoundError:
        return _fail(f"qgis_process 不存在：{cli}")
    audit["total_seconds"] = time.perf_counter() - started

    data = _cli_json_output(proc.stdout or "") if used_json else None
    error_text: str | None = None
    results: Any = None
    log_lines: list[str] = []
    if isinstance(data, dict):
        results = data.get("results")
        err = data.get("error")
        log_lines = [str(x) for x in (data.get("log") or []) if x]
        if isinstance(err, dict) and err:
            error_text = str(err.get("msg") or err)
        elif isinstance(err, str) and err:
            error_text = err
    if proc.returncode != 0 or (error_text and not results):
        detail = error_text or (proc.stderr or "").strip() or (proc.stdout or "").strip()
        return _fail(f"QGIS 算法 '{algo_id}' 执行失败：{detail[:800]}", audit=audit, qgis_log=log_lines)

    # 输出提取：JSON results 优先；否则回填用户显式输出路径（运行后真实存在者）
    output_paths: list[str] = []
    if isinstance(results, dict):
        for rv in results.values():
            if isinstance(rv, str) and rv:
                output_paths.append(_from_qgis_uri(rv))
            elif isinstance(rv, dict):
                for dv in rv.values():
                    if isinstance(dv, str) and dv:
                        output_paths.append(_from_qgis_uri(dv))
                        break
    if not output_paths:
        for p in user_out_paths:
            if os.path.exists(p):
                output_paths.append(p)
    if not output_paths:
        return _fail(
            f"QGIS 算法 '{algo_id}' 执行完成，但未找到输出文件。"
            "请在 parameters 中显式给出 OUTPUT=<完整路径> 后重试。",
            audit=audit, qgis_log=log_lines,
        )
    # QGIS 写 .shp 时 .cpg 是 `system`，GDAL 读端只认 `UTF-8`：统一改写，
    # 否则中文字段名/属性值经 GDAL 读出是 Latin-1 乱码。失败不影响本次结果。
    for p in output_paths:
        _ensure_utf8_cpg(p)
    msg = f"QGIS 算法 '{algo_id}' 执行完成。"
    logger.info("[qgis-audit] cli_algorithm_completed algo=%s audit=%s", algo_id, audit)
    return _ok(output_paths, msg, qgis_log=log_lines, audit=audit)


def _configure_qgis_environment() -> Path:
    """配置进程内 QGIS Python/Qt/GDAL 路径；实现与基准脚本保持一致。

    同时兼容 QGIS 3.x LTR（Qt5/PyQt5）与 4.x（Qt6/PyQt6）：
      - 探测 qgis / qgis-ltr 前缀、qt6 / qt5 运行时目录；
      - 递归把安装根下所有含 .dll/.pyd 的目录加入 DLL 搜索（add_dll_directory + PATH）；
      - 预加载 qgis_core.dll 与 Qt 核心 DLL——不预加载则 Python import qgis._core 时
        因依赖解析失败报 DLL load failed；
      - PyQt.sip 别名：优先 PyQt6.sip，其次 PyQt5.sip / 顶层 sip。
    """
    bat = _find_qgis_bat()
    if not bat:
        raise RuntimeError("未找到 qgis_process*.bat")
    install_root = Path(bat).parents[1]  # <QGIS>/bin/qgis_process*.bat
    qgis_prefix = _find_qgis_prefix(install_root)
    qgis_python = qgis_prefix / "python"
    bundled_site = install_root / "apps" / "Python312" / "Lib" / "site-packages"
    if not qgis_python.is_dir():
        raise RuntimeError(f"QGIS Python 目录不存在: {qgis_python}")

    # Qt 运行时：qt6 或 qt5
    qt_dir = install_root / "apps" / "qt6"
    if not qt_dir.is_dir():
        qt_dir = install_root / "apps" / "qt5"
    qt_core_dll = "Qt6Core.dll" if qt_dir.name == "qt6" else "Qt5Core.dll"

    os.environ["QGIS_PREFIX_PATH"] = str(qgis_prefix).replace("\\", "/")
    os.environ.setdefault("GDAL_DATA", str(install_root / "apps" / "gdal" / "share" / "gdal"))
    os.environ.setdefault("PROJ_DATA", str(install_root / "share" / "proj"))
    os.environ.setdefault("PROJ_LIB", os.environ["PROJ_DATA"])
    os.environ["QT_PLUGIN_PATH"] = os.pathsep.join([
        str(install_root / "apps" / qgis_prefix.name / "qtplugins"),
        str(qt_dir / "plugins"),
    ])

    # DLL 搜索路径：递归收集安装根下所有含 .dll/.pyd 的目录（qgis_core / Qt / gdal /
    # proj / pdalcpp / VC 运行库等散落在 bin、apps/qgis(-ltr)/bin、apps/qt5/bin 等处）。
    # add_dll_directory 全量加入（无长度限制，供 Python 加载 _core.pyd 依赖）；
    # 系统 PATH 只加核心 bin 目录（供 QGIS 运行时 LoadLibrary 及子进程解析），避免 PATH 膨胀。
    dll_dirs = set()
    for root, _dirs, files in os.walk(install_root):
        if any(f.lower().endswith((".dll", ".pyd")) for f in files):
            dll_dirs.add(root)
    for d in dll_dirs:
        try:
            os.add_dll_directory(d)
        except Exception:  # noqa: BLE001
            pass
    core_bin_dirs = [
        install_root / "bin",
        qgis_prefix / "bin",
        qt_dir / "bin",
        install_root / "apps" / "Python312",
        install_root / "apps" / "Python312" / "DLLs",
        qgis_prefix / "plugins",
    ]
    os.environ["PATH"] = (
        os.pathsep.join(str(p) for p in core_bin_dirs if p.is_dir())
        + os.pathsep + os.environ.get("PATH", "")
    )

    # 预加载 QGIS 核心 DLL（关键：不预加载则 import qgis._core 报 DLL load failed）
    for dll in ("qgis_core.dll", qt_core_dll):
        try:
            ctypes.WinDLL(dll)
        except Exception:  # noqa: BLE001
            logger.warning("[qgis] preload %s failed: %s", dll, sys.exc_info()[1])

    for p in (qgis_python, qgis_python / "plugins", bundled_site):
        if p.is_dir() and str(p) not in sys.path:
            sys.path.insert(0, str(p))

    # PyQt.sip 别名：QGIS 4.x 用 PyQt6.sip，3.x LTR 用 PyQt5.sip 或顶层 sip。
    for mod in ("PyQt6.sip", "PyQt5.sip", "sip"):
        try:
            sip_mod = __import__(mod, fromlist=["*"])
            sys.modules.setdefault("sip", sip_mod)
            break
        except ImportError:
            continue

    return qgis_prefix


def _qgis_runtime() -> tuple[Any, Any]:
    """初始化一次 QGIS，并在整个 MCP 生命周期内复用 processing 注册表。"""
    global _QGIS_APP, _QGIS_PROCESSING
    if _QGIS_APP is not None and _QGIS_PROCESSING is not None:
        return _QGIS_APP, _QGIS_PROCESSING
    with _QGIS_INIT_LOCK:
        if _QGIS_APP is None:
            _configure_qgis_environment()
            from qgis.core import QgsApplication  # type: ignore
            from qgis.analysis import QgsNativeAlgorithms  # type: ignore
            import processing  # type: ignore
            app = QgsApplication([], False)
            app.initQgis()
            app.processingRegistry().addProvider(QgsNativeAlgorithms())
            # 3D provider（native 之外的常用算法集）；失败不阻断（某些发行版无 3d 模块）
            try:
                from qgis.analysis import Qgs3DAlgorithms  # type: ignore
                app.processingRegistry().addProvider(Qgs3DAlgorithms())
            except Exception:  # noqa: BLE001
                pass
            _QGIS_APP, _QGIS_PROCESSING = app, processing
            logger.info("[qgis-audit] runtime_initialized process_reused=true")
    return _QGIS_APP, _QGIS_PROCESSING


def list_qgis_algorithms() -> dict[str, dict[str, Any]]:
    """列出全部 QGIS 处理算法（进程级缓存）。

    Windows 安装：进程内 QgsApplication 注册表；POSIX：`qgis_process list --json`。

    Returns:
        {algo_id: {name, group, provider, description}}；QGIS 不可用时返回 {}。
    """
    global _ALGO_CACHE
    if _ALGO_CACHE is not None:
        return _ALGO_CACHE

    _ALGO_CACHE = {}
    if _QGIS_APP is not None or _find_qgis_bat() is not None:
        try:
            app, _ = _qgis_runtime()
            cache: dict[str, dict[str, Any]] = {}
            for algo in app.processingRegistry().algorithms():
                cache[algo.id()] = {"name": algo.displayName(), "group": algo.group(),
                                    "provider": algo.provider().id(), "description": algo.shortHelpString()}
            _ALGO_CACHE = cache
            return _ALGO_CACHE
        except Exception as e:  # noqa: BLE001
            logger.warning("[qgis] list_qgis_algorithms(inproc) error: %s", e)
    cli = _find_qgis_cli()
    if cli:
        _ALGO_CACHE = _cli_list_algorithms(cli)
    return _ALGO_CACHE


def _qgis_default_repr(v: Any) -> Any:
    """把 QGIS 参数默认值安全转为 JSON 可序列化标量。"""
    if v is None:
        return None
    if isinstance(v, (str, int, float, bool)):
        return v
    try:
        s = v.toString()  # QgsCoordinateReferenceSystem 等 Qt 类型
        if isinstance(s, str) and s:
            return s
    except Exception:  # noqa: BLE001
        pass
    if isinstance(v, (list, tuple)):
        return [_qgis_default_repr(x) for x in v]
    try:
        return str(v)
    except Exception:  # noqa: BLE001
        return None


def _qgis_param_is_optional(p: Any) -> bool:
    """参数是否可选（QGIS 3.x 无 mandatory()，经 FlagOptional 标志判定）。"""
    try:
        from qgis.core import QgsProcessingParameterDefinition  # type: ignore

        return bool(p.flags() & QgsProcessingParameterDefinition.FlagOptional)
    except Exception:  # noqa: BLE001
        return False


def _qgis_algo_schema(algo: Any) -> dict[str, Any]:
    """把一个 QgsProcessingAlgorithm 序列化为 schema 条目（含 required/params）。"""
    params: dict[str, Any] = {}
    required: list[str] = []
    for p in algo.parameterDefinitions():
        name = p.name()
        optional = _qgis_param_is_optional(p)
        entry: dict[str, Any] = {
            "is_destination": bool(p.isDestination()),
            "type": {"id": p.type()},
            "description": (p.description() or name),
            "optional": optional,
            "default": _qgis_default_repr(p.defaultValue()),
        }
        params[name] = entry
        # 必填 = 非可选、非输出目标（由引擎自动回填）且无默认值（QGIS 会自动填默认值，
        # 带 default 的参数运行时无需显式传入，如 native:buffer 的 SEGMENTS/DISSOLVE 等）。
        if not optional and not entry["is_destination"] and entry["default"] is None:
            required.append(name)
    return {
        "name": algo.displayName(),
        "provider": algo.provider().id(),
        "group": algo.group(),
        "description": algo.shortHelpString() or algo.displayName(),
        "required": required,
        "params": params,
    }


def get_qgis_help(algo_id: str) -> dict[str, Any] | None:
    """取某算法的参数定义（进程内注册表；进程级缓存）。CLI 模式无结构化定义，返回 None。"""
    if algo_id in _HELP_CACHE:
        return _HELP_CACHE[algo_id]
    if _QGIS_APP is None and _find_qgis_bat() is None:
        return None
    try:
        app, _ = _qgis_runtime()
        algo = app.processingRegistry().algorithmById(algo_id)
        if algo is None:
            return None
        params = {p.name(): {"is_destination": bool(p.isDestination()),
                             "type": {"id": p.type()},
                             "description": (p.description() or p.name()),
                             "optional": _qgis_param_is_optional(p),
                             "default": _qgis_default_repr(p.defaultValue())}
                  for p in algo.parameterDefinitions()}
        data = {"parameters": params}
        _HELP_CACHE[algo_id] = data
        return data
    except Exception as e:  # noqa: BLE001
        logger.warning("[qgis] get_qgis_help(%s) error: %s", algo_id, e)
        return None


def export_qgis_schemas() -> dict[str, dict[str, Any]]:
    """一次性导出全部算法的完整 schema（含 required/params），供 generate_schema 使用。

    进程内注册表逐算法读取参数定义（761 个算法约数秒）；QGIS 进程内运行时不可用
    时返回 {}，由调用方降级为仅元数据目录。输出与 list_qgis_algorithms 同形，
    额外含 required/params 键。
    """
    try:
        app, _ = _qgis_runtime()
    except Exception as e:  # noqa: BLE001
        logger.warning("[qgis] export_qgis_schemas: 运行时不可用 (%s)", e)
        return {}
    out: dict[str, dict[str, Any]] = {}
    for algo in app.processingRegistry().algorithms():
        prov = algo.provider().id()
        # gdal:* 已由 gdal_engine 直执行接管，不在 qgis 段重复（与 list_qgis_algorithms 一致）。
        if prov == "gdal":
            continue
        try:
            out[algo.id()] = _qgis_algo_schema(algo)
        except Exception as e:  # noqa: BLE001 —— 单算法失败不阻断目录导出
            logger.warning("[qgis] export %s 失败: %s", algo.id(), e)
    return out


# ─── GDB 路径约定 ↔ QGIS URI 双向转换 ──────────────────────────────────────────
def _is_gdb_logical_path(path: str) -> bool:
    p = str(path).replace("\\", "/")
    low = p.lower()
    idx = low.find(".gdb/")
    if idx < 0:
        return False
    suffix = p[idx + 5:]
    if suffix.lower().endswith((".shp", ".tif", ".tiff", ".csv", ".txt", ".geojson")):
        return False
    return bool(suffix.strip())


def _to_qgis_uri(path: str) -> str:
    """xxx.gdb/图层名 -> xxx.gdb|layername=图层名；非 GDB 原样。"""
    p = str(path).replace("\\", "/")
    low = p.lower()
    idx = low.find(".gdb/")
    if idx >= 0:
        gdb = p[: idx + 4]
        layer = p[idx + 5:].strip("/")
        if layer and "|" not in layer:
            return f"{gdb}|layername={layer}"
    return p


def _from_qgis_uri(uri: str) -> str:
    """xxx.gdb|layername=图层名 -> xxx.gdb/图层名；非该形态原样。"""
    u = str(uri).replace("\\", "/")
    low = u.lower()
    idx = low.find(".gdb|layername=")
    if idx >= 0:
        gdb = u[: idx + 4]
        layer = u[idx + len(".gdb|layername="):]
        return f"{gdb}/{layer}"
    return u


# ─── 引擎入口 ──────────────────────────────────────────────────────────────────
def _ok(output_paths: list[str], message: str = "", **extra: Any) -> dict[str, Any]:
    r: dict[str, Any] = {
        "success": True, "output": message or "完成", "error": None,
        "messages": [message] if message else [], "output_paths": output_paths,
        "engine": "qgis",
    }
    r.update(extra)
    return r


def _fail(error: str, **extra: Any) -> dict[str, Any]:
    r: dict[str, Any] = {
        "success": False, "output": None, "error": error,
        "messages": [], "output_paths": [], "engine": "qgis",
    }
    r.update(extra)
    return r


def _param_kind(pdef: dict[str, Any]) -> str | None:
    """QGIS 参数是输入源还是输出目标，还是都不是。

    type.id 为 source -> 输入矢量/栅格；
    is_destination=True 或 type.id 为 sink/outputVector/outputRaster -> 输出目标。
    """
    ptype = (pdef.get("type") or {}).get("id", "")
    if pdef.get("is_destination"):
        return "output"
    if ptype in ("source",):
        return "input"
    if ptype in ("sink", "outputVector", "outputRaster", "output"):
        return "output"
    return None


def run_qgis_tool(algo_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
    """执行一个 QGIS 处理算法。

    Windows 安装（qgis_process*.bat / 已初始化运行时）走进程内；POSIX 走
    `qgis_process` CLI 子进程。

    Returns: 与 inner 工具同形的 dict（{success, output, error, output_paths, engine='qgis'}）。
    """
    if not qgis_available():
        return _fail("QGIS 未安装或未找到 qgis_process。")
    algos = list_qgis_algorithms()
    if algo_id not in algos:
        return _fail(f"QGIS 算法 '{algo_id}' 不存在。可用 list_available_tools(source='qgis') 查询。")

    # POSIX CLI 模式（进程内运行时不可用且无 Windows 安装）
    if _QGIS_APP is None and _find_qgis_bat() is None:
        return _cli_run_tool(_find_qgis_cli(), algo_id, parameters)

    help_data = get_qgis_help(algo_id) or {}
    params_schema = help_data.get("parameters", {}) if isinstance(help_data, dict) else {}

    # 组装 inputs：用户参数 key 大小写不敏感映射到 QGIS 参数名；输入/输出路径转 URI。
    schema_by_lower = {k.lower(): k for k in params_schema}
    inputs: dict[str, Any] = {}
    output_keys: list[str] = []
    for ukey, uval in (parameters or {}).items():
        qname = schema_by_lower.get(ukey.lower(), ukey)
        pdef = params_schema.get(qname, {})
        kind = _param_kind(pdef)
        if kind == "input" and isinstance(uval, str):
            inputs[qname] = _to_qgis_uri(uval)
        elif kind == "output" and isinstance(uval, str):
            inputs[qname] = _to_qgis_uri(uval)
            output_keys.append(qname)
            # 预建 GDB 父目录（QGIS 不自建目录层级）
            _ensure_parent_for_output(uval)
        else:
            inputs[qname] = uval

    # 无显式输出键时，自动补默认 sink（多数算法叫 OUTPUT），指向临时文件，便于结果回取。
    if not output_keys:
        for qname, pdef in params_schema.items():
            if _param_kind(pdef) == "output":
                output_keys.append(qname)
                break

    audit: dict[str, float] = {}
    started = time.perf_counter()
    try:
        app, processing = _qgis_runtime()
        audit["runtime_ready_seconds"] = time.perf_counter() - started
        algo = app.processingRegistry().algorithmById(algo_id)
        if algo is None:
            # 进程内注册表只挂 native(+3d) provider；grass/saga/qgis 等其余 provider
            # 经安装目录的 qgis_process 子进程执行（与 POSIX CLI 模式同一实现）。
            bat = _find_qgis_bat()
            if bat:
                audit["fallback"] = "qgis_process"
                return _cli_run_tool(bat, algo_id, parameters)
            return _fail(f"QGIS 算法 '{algo_id}' 不存在。")
        run_started = time.perf_counter()
        results = processing.run(algo_id, inputs)
        audit["algorithm_seconds"] = time.perf_counter() - run_started
    except Exception as e:  # noqa: BLE001
        audit["failed_after_seconds"] = time.perf_counter() - started
        logger.exception("[qgis-audit] algorithm_failed algo=%s audit=%s", algo_id, audit)
        return _fail(f"QGIS 算法 '{algo_id}' 执行异常: {e}", audit=audit)
    # 提取输出路径：优先用户指定的输出键，否则 results 中第一个 sink 路径
    output_paths: list[str] = []
    for qk in output_keys:
        rval = results.get(qk)
        if isinstance(rval, str) and rval:
            output_paths.append(_from_qgis_uri(rval))
        elif isinstance(rval, dict):
            # QGIS 偶用 {" Destination": "..."} 形态
            for dv in rval.values():
                if isinstance(dv, str) and dv:
                    output_paths.append(_from_qgis_uri(dv))
                    break
    # 兜底：用户在 parameters 里给了输出路径，回填之（即便 QGIS 未回显完整 URI）
    if not output_paths:
        for qk in output_keys:
            uval = inputs.get(qk)
            if isinstance(uval, str) and uval:
                output_paths.append(_from_qgis_uri(uval))

    audit["total_seconds"] = time.perf_counter() - started
    log_lines: list[str] = []
    msg = f"QGIS 算法 '{algo_id}' 执行完成。"
    logger.info("[qgis-audit] algorithm_completed algo=%s audit=%s", algo_id, audit)
    return _ok(output_paths, msg, qgis_log=log_lines, audit=audit)


def _ensure_parent_for_output(path: str) -> None:
    """为输出路径建父目录（GDB 旁挂 .tif / GDB 父目录等）。"""
    p = str(path).replace("\\", "/")
    low = p.lower()
    idx = low.find(".gdb/")
    if idx >= 0:
        # GDB 逻辑路径：确保 .gdb 父目录存在
        gdb = p[: idx + 4]
        parent = os.path.dirname(gdb)
    else:
        parent = os.path.dirname(p)
    if parent:
        try:
            os.makedirs(parent, exist_ok=True)
        except Exception:  # noqa: BLE001
            pass
