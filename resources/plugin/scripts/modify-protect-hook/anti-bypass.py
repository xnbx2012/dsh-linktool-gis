# -*- coding: utf-8 -*-
"""
anti-bypass.py - 拦截 arcpy 绕过行为（PreToolUse Hook）

本 Hook 是 plugin/CROSS_AGENT_RULES.md 的强制兜底机制，覆盖三条 arcpy 绕过路径：
  1. 直接执行 arcpy（Write 脚本后用 Bash/python 运行）
  2. 委托任一智能体执行 arcpy 脚本（任何 Agent 写含 arcpy 的脚本一律拦截）
  3. 通过 .bat / .sh 等包装脚本绕过执行 arcpy

同时承担「@task-plan 禁止产出可执行脚本」守卫：
  - 任何 Agent 写 .py/.bat/.sh 且内容含 arcpy / python 执行语句 → 拦截
  - 若能识别调用 Agent 为 @task-plan → 拦截其一切 .py/.bat/.sh 写入

退出码：0 = 放行；2 = 阻止（错误信息经 hookSpecificOutput 返回 Claude）；1 = 内部错误
"""

import sys
import os
import re
import io
import json

# 强制 UTF-8
sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8', errors='replace')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 可执行脚本扩展名（task-plan 一律禁止产出；其他 Agent 内容含 arcpy 时禁止）
EXECUTABLE_EXTENSIONS = ('.py', '.bat', '.sh', '.cmd', '.ps1')

# 标识「arcpy 直接执行」的内容特征
ARCPY_CONTENT_PATTERNS = [
    r'import\s+arcpy',
    r'from\s+arcpy',
    r'arcpy\.',
    r'execute_python_script',
]
ARCPY_CONTENT_RE = re.compile('|'.join(ARCPY_CONTENT_PATTERNS), re.IGNORECASE)

# 其余四个引擎的 CLI 直调特征（小写二进制形态，区分大小写以避免误伤文档叙述）
ENGINE_CLI_CONTENT_RE = re.compile(
    r'\bwhitebox_tools\b'
    r'|import\s+whitebox'
    r'|\bqgis_process\b'
    r'|\bogr2ogr\b'
    r'|\bgdal(?:info|translate|warp|contour|dem|grid|rasterize|polygonize|merge|buildvrt|addo|sieve|fillnodata|nearblack|transform)\b',
)

# Bash 中通过裸 python / uv run python -c / .bat / .sh 间接执行 arcpy 的特征
BASH_ARCPY_RE = re.compile(
    r'(python[\w\.]*\s+.*-c.*(?:import\s+arcpy|from\s+arcpy|arcpy\.))'
    r'|(uv\s+run\s+python.*(?:import\s+arcpy|from\s+arcpy|arcpy\.))'
    r'|(import\s+arcpy)'
    r'|(from\s+arcpy)',
    re.IGNORECASE,
)
# Bash 中调用 .bat / .sh 包装脚本（可能内嵌 python/arcpy）
BASH_WRAPPER_RE = re.compile(
    r'(\.(?:bat|sh|cmd)\b.*\b(?:python|uv\s+run)\b)'
    r'|(\b(?:bash|sh|cmd|source)\s+\S+\.(?:bat|sh|cmd)\b)',
    re.IGNORECASE,
)


def _is_executable(file_path: str) -> bool:
    """判断路径是否为可执行脚本文件"""
    if not file_path:
        return False
    lower = file_path.lower()
    return any(lower.endswith(ext) for ext in EXECUTABLE_EXTENSIONS)


def _looks_like_task_plan(agent_name: str) -> bool:
    """识别调用者是否为 @task-plan（agent 名暴露不可靠，best-effort）"""
    if not agent_name:
        return False
    lower = str(agent_name).lower()
    # 兼容 task-plan / linktool-plugin:task-plan 等写法
    return lower.endswith(':task-plan') or lower == 'task-plan'


def check_arcpy_bypass(tool_name: str, tool_input: dict, agent_name: str = None):
    """
    检测并拦截 arcpy 绕过尝试。
    返回 (should_block: bool, reason: str)。reason 为空字符串表示放行。
    """
    if not isinstance(tool_input, dict):
        return False, ""

    # ---- 规则 A：Write / Edit / Update 内容级拦截 ----
    if tool_name in ('Write', 'Edit', 'Update'):
        # 取写入内容（Write 用 content；Edit 用 new_string）
        content = tool_input.get('content', '')
        if not content:
            content = tool_input.get('new_string', '')
        file_path = tool_input.get('file_path', '') or ''

        # A1：任何 Agent 写含 arcpy / 其他引擎 CLI 直调的内容 → 拦截（杜绝「委托智能体跑 GIS」）
        if isinstance(content, str) and (ARCPY_CONTENT_RE.search(content) or ENGINE_CLI_CONTENT_RE.search(content)):
            return True, (
                f"内容含 GIS 引擎（arcpy/Whitebox/QGIS/GDAL CLI）直接执行特征，禁止 Write/Edit。"
                f"一切 GIS 执行必须经 execute_gis_tool（由 @gis-tool 在 Workflow 契约内调用）。"
                f"片段: {content[:80]!r}"
            )

        # A2：@task-plan 产出可执行脚本 → 一律拦截
        if _looks_like_task_plan(agent_name) and _is_executable(file_path):
            return True, (
                f"@task-plan 禁止产出可执行脚本 ({os.path.basename(file_path)})。"
                f"任务规划智能体不得写 .py/.bat/.sh，分析须委派 @gis-tool。"
            )

        # A3：其他 Agent 写可执行脚本，若内容含 python 执行语句（import/exec/subprocess）→ 拦截
        if _is_executable(file_path) and isinstance(content, str) and content:
            exec_smell = re.search(
                r'\b(?:import\s+\w|from\s+\w+\s+import|subprocess|exec\s*\(|os\.system|__main__)\b',
                content,
            )
            if exec_smell:
                return True, (
                    f"可执行脚本 {os.path.basename(file_path)} 含 Python 执行语句，"
                    f"禁止在运行层产出可执行脚本绕过 MCP。"
                )

    # ---- 规则 B：Bash 命令级拦截 ----
    if tool_name == 'Bash':
        cmd = tool_input.get('command', '')
        if isinstance(cmd, str):
            if BASH_ARCPY_RE.search(cmd):
                return True, (
                    f"Bash 命令尝试直接执行 arcpy，禁止。"
                    f"提示: 一切 arcpy 执行必须经 execute_gis_tool。命令片段: {cmd[:80]!r}"
                )
            if ENGINE_CLI_CONTENT_RE.search(cmd):
                return True, (
                    f"Bash 命令尝试直接执行 GIS 引擎 CLI（Whitebox/QGIS/GDAL），禁止。"
                    f"提示: 一切 GIS 执行必须经 execute_gis_tool（tool_name 前缀 wbt_/qgis_/gdal_ 可指定引擎）。"
                    f"命令片段: {cmd[:80]!r}"
                )
            if BASH_WRAPPER_RE.search(cmd):
                return True, (
                    f"Bash 命令尝试经 .bat/.sh 包装脚本执行（可能内嵌 arcpy），禁止绕过 MCP。"
                    f"命令片段: {cmd[:80]!r}"
                )

    return False, ""


def _detect_agent_name(hook_event: dict) -> str:
    """
    尝试从 Hook 事件/环境变量识别调用 Agent（best-effort）。
    Claude Code 不保证暴露 agent 名，取不到时返回空串，退化为内容级拦截。
    """
    for key in ('agent_name', 'agent', 'subagent_type'):
        val = hook_event.get(key)
        if val:
            return str(val)
    for env_key in ('CLAUDE_AGENT_NAME', 'CLAUDE_AGENT', 'CLAUDE_SUBAGENT_TYPE'):
        val = os.environ.get(env_key)
        if val:
            return str(val)
    return ""


def main():
    try:
        raw = sys.stdin.read()
        try:
            hook_event = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError as e:
            print(f"[anti-bypass] JSON 解析错误: {e}", file=sys.stderr)
            sys.exit(1)

        if not isinstance(hook_event, dict):
            print("[anti-bypass] 输入非 JSON 对象", file=sys.stderr)
            sys.exit(1)

        tool_name = hook_event.get('tool_name', '')
        tool_input = hook_event.get('tool_input', {}) or {}
        agent_name = _detect_agent_name(hook_event)

        blocked, reason = check_arcpy_bypass(tool_name, tool_input, agent_name)

        if blocked:
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": f"[anti-bypass] {reason}"
                }
            }
            # 同时打印到 stderr，便于非结构化调用方也能看到
            print(f"[anti-bypass] 拦截: {reason}", file=sys.stderr)
            print(json.dumps(output, ensure_ascii=False))
            sys.exit(2)

        # 放行
        sys.exit(0)

    except SystemExit:
        raise
    except Exception as e:
        print(f"[anti-bypass] 内部错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
