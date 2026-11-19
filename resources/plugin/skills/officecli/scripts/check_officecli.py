"""
OfficeCLI 安装检查与自动安装脚本

在 report 智能体执行前调用，检查 officecli 是否可用。
Windows：优先使用 plugin/bin/ 内嵌的 officecli.exe（PE 二进制，随插件分发）。
Linux/macOS：内嵌的 officecli.exe 是 Windows PE，无法执行——绝不当作可用；
  改为检测 PATH 上的 officecli（或仓库 bin/officecli 无扩展名可执行文件），
  未找到则通过官方 install.sh（curl ... | bash）自动安装。
"""

import json
import os
import shutil
import subprocess
import sys

# 内嵌二进制文件路径（plugin/bin/officecli.exe，仅 Windows PE，仅供 Windows 使用）
PLUGIN_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BUNDLED_BINARY = os.path.join(PLUGIN_ROOT, "bin", "officecli.exe")
# Linux/macOS 下仓库内可能存在的无扩展名内嵌二进制（若存在且可执行）
BUNDLED_BINARY_POSIX = os.path.join(PLUGIN_ROOT, "bin", "officecli")

# 官方安装脚本 URL（与子技能 officecli-docx / officecli-xlsx 的 SKILL.md 保持一致）
INSTALL_PS1_URL = "https://raw.githubusercontent.com/iOfficeAI/OfficeCLI/main/install.ps1"
INSTALL_SH_URL = "https://raw.githubusercontent.com/iOfficeAI/OfficeCLI/main/install.sh"

# Windows 默认安装路径（官方 install.ps1 的行为）
DEFAULT_INSTALL_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "OfficeCli"
)
BINARY_NAME = "officecli.exe"


def _get_binary_path() -> str | None:
    """获取 officecli 可执行文件路径。

    Windows 优先级：内嵌 .exe > PATH > 默认安装目录。
    Linux/macOS：绝不使用内嵌 .exe（Windows PE 无法执行）；
      PATH 上的 officecli > 仓库 bin/officecli（无扩展名，需可执行）。
    """
    if os.name == "nt":
        # 1. 检查内嵌二进制文件（随 plugin 分发，无需额外安装）
        if os.path.isfile(BUNDLED_BINARY):
            return BUNDLED_BINARY

        # 2. 检查 PATH
        path = shutil.which(BINARY_NAME) or shutil.which("officecli")
        if path:
            return path

        # 3. 检查默认安装目录（可能安装了但 PATH 未刷新）
        local_binary = os.path.join(DEFAULT_INSTALL_DIR, BINARY_NAME)
        if os.path.isfile(local_binary):
            return local_binary

        return None

    # ── POSIX（Linux / macOS）──
    # 1. PATH 上的 officecli
    path = shutil.which("officecli")
    if path:
        return path

    # 2. 仓库内嵌的无扩展名二进制（若存在且可执行；officecli.exe 是 PE，跳过）
    if os.path.isfile(BUNDLED_BINARY_POSIX) and os.access(BUNDLED_BINARY_POSIX, os.X_OK):
        return BUNDLED_BINARY_POSIX

    return None


def is_officecli_installed() -> bool:
    """检查 officecli 是否可用。"""
    return _get_binary_path() is not None


def verify_officecli(binary_path: str) -> dict:
    """
    通过 --version 验证 officecli 是否可正常执行。

    Returns:
        {"ok": True, "version": "..."} 或 {"ok": False, "error": "..."}
    """
    try:
        result = subprocess.run(
            [binary_path, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            env={**os.environ, "OFFICECLI_SKIP_UPDATE": "1"}  # CI 环境，跳过自动更新检查
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            return {"ok": True, "version": version}
        return {"ok": False, "error": result.stderr.strip() or result.stdout.strip()}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "--version 调用超时"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def install_officecli() -> dict:
    """
    通过官方脚本安装 OfficeCLI。
    Windows：PowerShell 执行 irm install.ps1 | iex；
    Linux/macOS：bash 执行 curl -fsSL install.sh | bash。
    安装成功后（Windows）将二进制文件复制到内嵌目录 (bin/)，以便分发使用。

    Returns:
        {"success": True, "path": "...", "version": "..."}
        {"success": False, "error": "..."}
    """
    if os.name == "nt":
        return _install_officecli_windows()

    # ── POSIX：curl install.sh | bash ──
    curl = shutil.which("curl")
    if not curl:
        return {"success": False, "error": "未找到 curl，无法下载官方安装脚本。请先安装 curl。"}
    bash = shutil.which("bash")
    if not bash:
        return {"success": False, "error": "未找到 bash，无法执行安装脚本。"}

    install_cmd = f"curl -fsSL '{INSTALL_SH_URL}' | bash"
    try:
        result = subprocess.run(
            [bash, "-c", install_cmd],
            capture_output=True,
            text=True,
            timeout=180,
            env={**os.environ, "OFFICECLI_SKIP_UPDATE": "1"}
        )
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "安装超时（下载时间过长），请检查网络连接。"}
    except Exception as e:
        return {"success": False, "error": f"安装异常: {e}"}

    # 检查安装结果（PATH 可能未刷新，安装后重新探测）
    path = shutil.which("officecli")
    if path:
        v = verify_officecli(path)
        if v["ok"]:
            _copy_to_bundled(path)
            return {"success": True, "path": path, "version": v["version"]}
        return {"success": False, "error": f"安装完成但版本校验失败: {v['error']}"}
    if os.path.isfile(BUNDLED_BINARY_POSIX) and os.access(BUNDLED_BINARY_POSIX, os.X_OK):
        v = verify_officecli(BUNDLED_BINARY_POSIX)
        if v["ok"]:
            return {"success": True, "path": BUNDLED_BINARY_POSIX, "version": v["version"]}

    return {
        "success": False,
        "error": (
            "安装完成但未找到 officecli。"
            f"请手动执行: curl -fsSL {INSTALL_SH_URL} | bash，"
            "然后重新打开终端（PATH 刷新）后重试。"
        ),
    }


def _install_officecli_windows() -> dict:
    """Windows：PowerShell 一行式安装（irm install.ps1 | iex）。"""
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if not pwsh:
        return {"success": False, "error": "未找到 PowerShell，无法执行安装。"}

    install_cmd = f"irm '{INSTALL_PS1_URL}' | iex"

    try:
        result = subprocess.run(
            [pwsh, "-ExecutionPolicy", "Bypass", "-Command", install_cmd],
            capture_output=True,
            text=True,
            timeout=180,
            env={**os.environ, "OFFICECLI_SKIP_UPDATE": "1"}
        )

        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "安装超时（下载时间过长），请检查网络连接。"}
    except Exception as e:
        return {"success": False, "error": f"安装异常: {e}"}

    # 检查安装结果
    binary_path = os.path.join(DEFAULT_INSTALL_DIR, BINARY_NAME)
    if not os.path.isfile(binary_path):
        path = shutil.which(BINARY_NAME) or shutil.which("officecli")
        if path:
            v = verify_officecli(path)
            if v["ok"]:
                # 将找到的二进制复制到内嵌目录
                _copy_to_bundled(path)
                return {"success": True, "path": BUNDLED_BINARY, "version": v["version"]}
        return {
            "success": False,
            "error": (
                "安装完成但未找到 officecli.exe。"
                f"请手动执行: irm {INSTALL_PS1_URL} | iex"
            ),
        }

    # 将安装目录加入当前进程 PATH
    os.environ["PATH"] = DEFAULT_INSTALL_DIR + os.pathsep + os.environ.get("PATH", "")

    v = verify_officecli(binary_path)
    if v["ok"]:
        # 将安装的二进制复制到内嵌目录，以便分发
        _copy_to_bundled(binary_path)
        return {"success": True, "path": BUNDLED_BINARY, "version": v["version"]}

    return {"success": False, "error": f"安装完成但版本校验失败: {v['error']}"}


def _copy_to_bundled(source: str) -> bool:
    """将 officecli 二进制文件复制到内嵌目录 (plugin/bin/)。仅 Windows 使用内嵌 .exe。"""
    if os.name != "nt":
        # POSIX：内嵌 .exe 无法执行，不复制
        return False
    try:
        bin_dir = os.path.join(PLUGIN_ROOT, "bin")
        os.makedirs(bin_dir, exist_ok=True)
        shutil.copy2(source, BUNDLED_BINARY)
        print(f"已将 OfficeCLI 复制到内嵌目录: {BUNDLED_BINARY}")
        return True
    except Exception as e:
        print(f"复制到内嵌目录失败: {e}", file=sys.stderr)
        return False


def check_and_install() -> dict:
    """
    主入口：检查 officecli，未安装则自动安装并校验版本。

    Returns:
        {"installed": True, "path": "...", "version": "..."}
        {"installed": False, "installed_now": True, "path": "...", "version": "..."}
        {"installed": False, "installed_now": False, "error": "..."}
    """
    # 已安装 → 直接校验版本
    path = _get_binary_path()
    if path:
        v = verify_officecli(path)
        if v["ok"]:
            print(f"OfficeCLI 已安装: {path} (v{v['version']})")
            return {"installed": True, "path": path, "version": v["version"]}
        # 版本校验失败，视为不可用，继续安装流程
        print(f"OfficeCLI 版本校验失败 ({v['error']})，将重新安装...")

    # 未安装或不可用 → 执行安装
    print("未检测到 OfficeCLI，正在通过官方脚本自动安装...")
    result = install_officecli()

    if result["success"]:
        print(f"OfficeCLI 安装成功: {result['path']} (v{result.get('version', 'unknown')})")
        return {
            "installed": False,
            "installed_now": True,
            "path": result["path"],
            "version": result.get("version"),
        }

    print(f"OfficeCLI 安装失败: {result['error']}")
    return {"installed": False, "installed_now": False, "error": result["error"]}


if __name__ == "__main__":
    status = check_and_install()
    print(json.dumps(status, ensure_ascii=False, indent=2))

    if not status.get("installed") and not status.get("installed_now"):
        sys.exit(1)
