# -*- coding: utf-8 -*-

import json
import sys
import os

if __name__ == "__main__":
    try:
        print("正在记录GIS工具执行日志...")
        sys.stdin.reconfigure(encoding='utf-8')
        sys.stdout.reconfigure(encoding='utf-8')
        input_data = sys.stdin.read()
        hook_event = json.loads(input_data)
        print(hook_event)

        cwd = hook_event.get("cwd", "").replace("\\\\", "/")  # 替换反斜杠为正斜杠，确保路径格式一致
        tool_input = hook_event.get("tool_input", {})

        # cwd = "D:/02_User_Files/02项目文件/20260116_LinkTool/LinkTool-ClaudeCode/test"

        # 构建 01_DataBackup 的绝对路径
        log_dir = os.path.join(cwd, "02_WorkSpace", "gis-tool-logs.json")

        # 确保gis-tool-logs.json文件存在，如果不存在则创建一个空的JSON文件
        if not os.path.exists(log_dir):
            print(f"日志文件不存在，正在创建: {log_dir}")
            with open(log_dir, 'w', encoding='utf-8') as log_file:
                json.dump([], log_file, ensure_ascii=False, indent=4)
        print(f"日志文件路径: {log_dir}")
        # 将tool_input添加到日志文件中
        with open(log_dir, 'r+', encoding='utf-8') as log_file:
            try:
                logs = json.load(log_file)
            except json.JSONDecodeError:
                logs = []
            logs.append(tool_input)
            log_file.seek(0)
            json.dump(logs, log_file, ensure_ascii=False, indent=4)

        print("GIS工具执行日志记录成功！")
        sys.exit(0)

    except json.JSONDecodeError as e:
        print(f"Error: 无法解析 JSON 输入 - {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)