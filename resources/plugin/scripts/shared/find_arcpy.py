# -*- coding: utf-8 -*-
"""
共享模块：ArcPy 解释器定位与脚本执行工具

从 arcgis-mcp-server/main.py 提取，供所有需要 ArcPy 的 Hook 共用。
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def find_py_interpreter() -> str | None:
    """
    定位 ArcGIS Pro Python 解释器路径。

    查找顺序：
    1. 环境变量 ARCGIS_PRO_PATH
    2. 默认安装路径（C:/D:/E: 盘）
    3. 用户 AppData 安装路径
    4. 开始菜单快捷方式解析
    5. Windows 注册表

    Returns:
        Python 解释器路径，或 None
    """
    # 1. 环境变量
    env_path = os.environ.get("ARCGIS_PRO_PATH")
    if env_path:
        python_exe = Path(env_path) / "bin" / "Python" / "envs" / "arcgispro-py3" / "python.exe"
        if python_exe.exists():
            return str(python_exe)

    # 2. 默认安装路径
    user_profile = os.environ.get("USERPROFILE", "")
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")

    default_paths = [
        r"C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe",
        r"C:\Program Files (x86)\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe",
        r"D:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe",
        r"D:\Program Files (x86)\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe",
        r"E:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe",
        r"E:\Program Files (x86)\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe",
        r"C:\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe",
        r"D:\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe",
        r"E:\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe",
        os.path.join(local_appdata, r"Programs\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"),
        os.path.join(user_profile, r"AppData\Local\Programs\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"),
        r"C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3-clone\python.exe",
        r"D:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3-clone\python.exe",
        os.path.join(local_appdata, r"Programs\ArcGIS\Pro\bin\Python\envs\arcgispro-py3-clone\python.exe"),
    ]
    for path in default_paths:
        if path and os.path.exists(path):
            return path

    # 3. 快捷方式解析
    shortcut_paths = [
        Path(r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\ArcGIS\ArcGIS Pro\ArcGIS Pro.lnk"),
        Path(r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\ArcGIS Pro\ArcGIS Pro.lnk"),
        Path(r"C:\ProgramData\Microsoft\Windows\Start Menu\ArcGIS Pro.lnk"),
        Path(os.path.join(appdata, r"Microsoft\Windows\Start Menu\Programs\ArcGIS\ArcGIS Pro\ArcGIS Pro.lnk")),
        Path(os.path.join(appdata, r"Microsoft\Windows\Start Menu\Programs\ArcGIS Pro\ArcGIS Pro.lnk")),
        Path(os.path.join(appdata, r"Microsoft\Windows\Start Menu\ArcGIS Pro.lnk")),
        Path(os.path.join(user_profile, r"AppData\Roaming\Microsoft\Windows\Start Menu\Programs\ArcGIS\ArcGIS Pro\ArcGIS Pro.lnk")),
        Path(os.path.join(user_profile, r"AppData\Roaming\Microsoft\Windows\Start Menu\Programs\ArcGIS Pro\ArcGIS Pro.lnk")),
        Path(os.path.join(user_profile, r"Desktop\ArcGIS Pro.lnk")),
        Path(os.path.join(user_profile, r"OneDrive\Desktop\ArcGIS Pro.lnk")),
        Path(r"C:\Users\Public\Desktop\ArcGIS Pro.lnk"),
    ]

    for shortcut_path in shortcut_paths:
        if shortcut_path.exists():
            target = _resolve_lnk(shortcut_path)
            if target:
                arcgis_dir = Path(target).parent.parent
                python_exe = arcgis_dir / "bin" / "Python" / "envs" / "arcgispro-py3" / "python.exe"
                if python_exe.exists():
                    return str(python_exe)
                python_exe_clone = arcgis_dir / "bin" / "Python" / "envs" / "arcgispro-py3-clone" / "python.exe"
                if python_exe_clone.exists():
                    return str(python_exe_clone)

    # 4. Windows 注册表
    try:
        import winreg
        registry_paths = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\ESRI\ArcGISPro"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\ESRI\ArcGISPro"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\ESRI\ArcGISPro"),
        ]
        for hkey, key_path in registry_paths:
            try:
                with winreg.OpenKey(hkey, key_path) as key:
                    install_dir, _ = winreg.QueryValueEx(key, "InstallDir")
                    if install_dir:
                        python_exe = Path(install_dir) / "bin" / "Python" / "envs" / "arcgispro-py3" / "python.exe"
                        if python_exe.exists():
                            return str(python_exe)
            except (OSError, FileNotFoundError):
                continue
    except ImportError:
        pass

    # arcpy 引擎仅限 Windows：ArcGIS Pro 不提供 Linux/macOS 版本。
    # 非 Windows 上直接给明确提示，而不是让调用方拿到 None 后自己猜。
    if os.name != "nt":
        print(
            "find_arcpy: 非 Windows 平台，arcpy 引擎不可用（ArcGIS Pro 为 Windows 专属，"
            "Linux/macOS 请使用 qgis/gdal/whitebox/inner 引擎）",
            file=sys.stderr,
        )
    return None


def _resolve_lnk(path: Path) -> str | None:
    """解析 Windows 快捷方式（.lnk）到目标路径"""
    try:
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(str(path))
        return shortcut.Targetpath
    except Exception:
        return None


def run_arcpy_script(script_code: str, input_data: dict | None = None, timeout: int = 120) -> dict[str, Any]:
    """
    通过 ArcGIS Pro Python 解释器执行 ArcPy 脚本。

    Args:
        script_code: Python 脚本代码
        input_data: 可选的输入数据（通过 stdin 传递为 JSON）
        timeout: 超时秒数（默认 120）

    Returns:
        {"success": bool, "result": Any, "error": str|None}
    """
    python_exe = find_py_interpreter()
    if not python_exe:
        return {
            "success": False,
            "result": None,
            "error": "未找到 ArcGIS Pro Python 解释器。请设置 ARCGIS_PRO_PATH 环境变量。"
        }

    try:
        # 强制子进程使用 UTF-8 编码，避免 Windows GBK 无法编码 emoji 等 Unicode 字符
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run(
            [python_exe, "-c", script_code],
            input=json.dumps(input_data, ensure_ascii=False) if input_data else None,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout,
            env=env,
        )

        if result.returncode != 0:
            return {
                "success": False,
                "result": None,
                "error": f"脚本执行失败: {result.stderr}"
            }

        try:
            output = json.loads(result.stdout)
            return {"success": True, "result": output, "error": None}
        except json.JSONDecodeError:
            return {"success": True, "result": result.stdout.strip(), "error": None}

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "result": None,
            "error": f"脚本执行超时（{timeout}秒）"
        }
    except Exception as e:
        return {
            "success": False,
            "result": None,
            "error": f"执行错误: {str(e)}"
        }
