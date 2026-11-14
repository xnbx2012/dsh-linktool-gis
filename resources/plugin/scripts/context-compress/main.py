# -*- coding: utf-8 -*-
"""
上下文压缩 Hook（PostCompact + PostToolUse）

功能：
- PostCompact 触发时：读取 gis-tool-logs.json，生成压缩摘要重新注入上下文
- PostToolUse 触发时：由 enhanced_record.py 处理（此脚本仅处理 PostCompact）

退出码：0=始终放行
"""

import json
import sys
import os
import io

# 强制 UTF-8
sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8', errors='replace')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


def build_compressed_history(log_path: str) -> str:
    """从日志文件构建压缩的操作历史摘要"""
    if not os.path.exists(log_path):
        return ""

    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            logs = json.load(f)
    except (json.JSONDecodeError, IOError):
        return ""

    if not logs:
        return ""

    lines = ["[GIS 操作历史摘要]"]
    for i, entry in enumerate(logs, 1):
        tool_name = entry.get("tool_name", "unknown")
        short_name = tool_name.split('.')[-1] if '.' in tool_name else tool_name

        input_paths = entry.get("input_paths", [])
        output_paths = entry.get("output_paths", [])
        short_inputs = [os.path.basename(p) for p in input_paths[:2]]
        short_outputs = [os.path.basename(p) for p in output_paths[:2]]

        ts = entry.get("timestamp", "")
        time_str = ts[11:19] if len(ts) > 19 else ""  # HH:MM:SS

        parts = [f"#{i}"]
        if time_str:
            parts.append(time_str)
        parts.append(short_name)
        if short_inputs:
            parts.append(f"← {', '.join(short_inputs)}")
        if short_outputs:
            parts.append(f"→ {', '.join(short_outputs)}")

        lines.append(" ".join(parts))

    return "\n".join(lines)


def main():
    try:
        input_data = json.loads(sys.stdin.read())
        hook_event_name = input_data.get("hook_event_name", "")

        if hook_event_name == "PostCompact":
            # PostCompact：重新注入压缩历史
            cwd = input_data.get("cwd", "").replace("\\", "/")
            log_path = os.path.join(cwd, "02_WorkSpace", "gis-tool-logs.json")

            summary = build_compressed_history(log_path)
            if summary:
                output = {
                    "hookSpecificOutput": {
                        "hookEventName": "PostCompact",
                        "additionalContext": summary
                    }
                }
                print(json.dumps(output, ensure_ascii=False))
                print(f"[context-compress] 已注入压缩历史摘要", file=sys.stderr)

        sys.exit(0)

    except json.JSONDecodeError as e:
        print(f"[context-compress] JSON 解析错误: {e}", file=sys.stderr)
        sys.exit(1)
    except SystemExit:
        raise
    except Exception as e:
        print(f"[context-compress] 内部错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
