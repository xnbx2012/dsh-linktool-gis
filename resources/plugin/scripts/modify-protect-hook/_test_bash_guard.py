# -*- coding: utf-8 -*-
"""bash_guard.py 中文误判修复单元测试"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from importlib import import_module
spec = import_module("bash_guard")
is_valid_path = spec.is_valid_path
extract_paths = spec.extract_paths_from_command

def check(cond, label):
    if cond:
        print(f"PASS  {label}")
    else:
        print(f"FAIL  {label}: {cond}")
        sys.exit(1)

print("=== is_valid_path ===")

# 真实 Windows 盘符路径
check(is_valid_path("D:/test/data"), "D:/test/data → True")
check(is_valid_path("C:\\Users\\test"), "C:\\Users\\test → True")
check(is_valid_path("D:/a"), "D:/a → True (min length)")

# 误识别的中文/文本（非路径）
check(not is_valid_path("Workflow ID: w5etkt08v"), "Workflow ID: w5etkt08v → False")
check(not is_valid_path("检查进度..."), "检查进度... → False")
check(not is_valid_path("ID: w5etkt08v"), "ID: w5etkt08v → False (no drive letter)")
check(not is_valid_path("D:workspace"), "D:workspace → False (no slash after colon)")

# Unix 绝对路径
check(is_valid_path("/usr/local/bin"), "/usr/local/bin → True")

print("=== extract_paths_from_command ===")

# 中文文本不应被误提取为路径
paths = extract_paths("echo 'Workflow ID: wf_test123 测试中文'", "")
check(paths == [], f"中文文本不被误识: {paths}")

paths = extract_paths("echo 检查进度...", "")
check(paths == [], f"中文 echo 不误识: {paths}")

# 真实盘符路径应被提取
paths = extract_paths("ls D:/test/01_DataBackup/", "")
check(any(is_valid_path(p) for p in paths), f"真实路径被提取: {paths}")
check(any("D:/test/01_DataBackup" in p for p in paths), f"包含完整路径: {paths}")

# 混合：中文文本 + 真实路径
paths = extract_paths("echo 'Workflow ID: w5etkt08v' && ls D:/data/02_WorkSpace/", "")
real_paths = [p for p in paths if is_valid_path(p)]
check(any("D:/data/02_WorkSpace" in p for p in real_paths), f"混合命令正确提取路径: {real_paths}")

print("=== 全部 PASS ===")
