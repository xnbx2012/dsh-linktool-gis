# -*- coding: utf-8 -*-
"""anti-bypass.py 单元测试运行器（开发期临时测试，非发布物）"""
import sys
import os
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "anti-bypass.py")

spec = importlib.util.spec_from_file_location("anti_bypass", TARGET)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
check = mod.check_arcpy_bypass


def assert_block(cond_args, expected_block, label):
    block, reason = check(*cond_args)
    if block == expected_block:
        print(f"PASS  {label}")
    else:
        print(f"FAIL  {label}  -> block={block} expected={expected_block} reason={reason}")
        sys.exit(1)


print("=== anti-bypass.py 单元测试 ===")

# A1: 含 arcpy 的 Write 内容 -> 拦截（不区分 agent）
assert_block(("Write", {"file_path": "x.txt", "content": "import arcpy\narcpy.Buffer_analysis()"}, None), True,
             "A1 写含 import arcpy 的内容应拦截")
assert_block(("Write", {"file_path": "x.txt", "content": "from arcpy import management"}, None), True,
             "A1 写含 from arcpy 的内容应拦截")
assert_block(("Write", {"file_path": "x.txt", "content": "arcpy.management.GetCount(x)"}, None), True,
             "A1 写含 arcpy. 调用的内容应拦截")

# A1 放行: 正常 Python 无 arcpy
assert_block(("Write", {"file_path": "x.txt", "content": "print('hello')\nx = 1"}, None), False,
             "A1 正常 Python 内容应放行")

# A2: task-plan 写 .py/.bat/.sh -> 拦截（即使不含 arcpy）
assert_block(("Write", {"file_path": "run.bat", "content": "echo hi"}, "task-plan"), True,
             "A2 task-plan 写 .bat 应拦截")
assert_block(("Write", {"file_path": "tool.py", "content": "x=1"}, "task-plan"), True,
             "A2 task-plan 写 .py 应拦截")
assert_block(("Write", {"file_path": "deploy.sh", "content": "ls"}, "task-plan"), True,
             "A2 task-plan 写 .sh 应拦截")
# A2 放行: 非 task-plan 写普通脚本（无 arcpy、无执行语句）-> 仅当含执行语句才拦
assert_block(("Write", {"file_path": "note.md", "content": "# doc"}, "task-plan"), False,
             "A2 task-plan 写 .md 应放行")

# A3: 其他 Agent 写可执行脚本 + 含执行语句 -> 拦截
assert_block(("Write", {"file_path": "sneak.py", "content": "import os\nos.system('rm -rf x')"}, "gis-tool"), True,
             "A3 其他 Agent 写含 os.system 的 .py 应拦截")
# A3 放行: 其他 Agent 写可执行脚本但纯文本（无 import/exec/subprocess）
assert_block(("Write", {"file_path": "blank.sh", "content": "# just a comment"}, "gis-tool"), False,
             "A3 其他 Agent 写纯注释 .sh 应放行")

# B: Bash 含 arcpy -> 拦截
assert_block(("Bash", {"command": "uv run python -c \"import arcpy; arcpy.Buffer_analysis()\""}, None), True,
             "B Bash uv run python -c 含 arcpy 应拦截")
assert_block(("Bash", {"command": "python -c \"from arcpy import management\""}, None), True,
             "B Bash python -c 含 arcpy 应拦截")
# B: Bash 经 .bat/.sh 包装 -> 拦截
assert_block(("Bash", {"command": "run.bat && uv run python x"}, None), True,
             "B Bash 经 .bat 包装含 python 应拦截")
assert_block(("Bash", {"command": "sh deploy.sh"}, None), True,
             "B Bash sh .sh 脚本应拦截")
# B 放行: 正常 Bash
assert_block(("Bash", {"command": "echo hello world"}, None), False,
             "B 正常 echo 应放行")
assert_block(("Bash", {"command": "ls -la"}, None), False,
             "B 正常 ls 应放行")

print("=== 全部 PASS ===")
