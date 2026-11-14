# -*- coding: utf-8 -*-
"""
失败模式检测 Hook（PostToolUse）— S15 优雅退出

功能：
- 监测连续失败模式（同一工具连续 3 次失败）
- 通过 additionalContext 注入警告，建议 Agent 停止重试并报告根因

退出码：0=始终放行（PostToolUse 不阻止操作）
"""

import json
import sys
import os
import io
from collections import defaultdict

# 强制 UTF-8
sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8', errors='replace')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


def detect_failure_pattern(log_path: str, window: int = 3) -> str | None:
    """
    分析最近的工具执行日志（JSONL 格式），检测连续失败模式。
    返回警告字符串（无警告则返回 None）。
    """
    if not os.path.exists(log_path):
        return None

    # 逐行解析 JSONL 文件（.workflow_state.jsonl 每行一条 JSON）
    logs = []
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        logs.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except IOError:
        return None

    if len(logs) < window:
        return None

    # 分析最近 N 条记录
    recent = logs[-window:]
    tool_names = [entry.get("tool_name", "") for entry in recent]

    # 检测同一工具连续执行（可能是失败重试）
    if len(set(tool_names)) == 1 and tool_names[0]:
        tool = tool_names[0]
        short_name = tool.split('.')[-1] if '.' in tool else tool
        # 检查输出路径是否全部为空（可能是失败）
        all_empty_output = all(
            not entry.get("output_paths", [])
            for entry in recent
        )
        if all_empty_output:
            return (
                f"[S15-GRACEFUL-EXIT] 工具 '{short_name}' 已连续执行 {window} 次且均无输出路径，"
                f"疑似连续失败。建议：1) 检查输入数据是否正确 2) 检查参数是否有效 "
                f"3) 连续 {window} 次相同错误后应立即停止重试并报告根因，"
                f"交由 @task-plan 或用户决定下一步策略。"
            )

    return None


def main():
    try:
        input_data = json.loads(sys.stdin.read())
        cwd = input_data.get("cwd", "").replace("\\", "/")
        tool_input = input_data.get("tool_input", {})
        gis_tool_name = tool_input.get("tool_name", "")

        if not gis_tool_name:
            sys.exit(0)

        log_path = os.path.join(cwd, "02_WorkSpace", ".workflow_state.jsonl")
        warning = detect_failure_pattern(log_path)

        if warning:
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": warning
                }
            }
            print(json.dumps(output, ensure_ascii=False))

        sys.exit(0)

    except json.JSONDecodeError as e:
        print(f"[failure-pattern] JSON 解析错误: {e}", file=sys.stderr)
        sys.exit(1)
    except SystemExit:
        raise
    except Exception as e:
        print(f"[failure-pattern] 内部错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
