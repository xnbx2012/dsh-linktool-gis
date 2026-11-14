# -*- coding: utf-8 -*-
"""enhanced_record.py 单元测试（determine_status + build_compressed_summary）"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from importlib import import_module
spec = import_module("enhanced_record")
determine_status = spec.determine_status
build_compressed_summary = spec.build_compressed_summary

def check(cond, label):
    if cond:
        print(f"PASS  {label}")
    else:
        print(f"FAIL  {label}")
        sys.exit(1)

print("=== determine_status ===")

# MCP error format
r, reason = determine_status({"error": {"code": -1, "message": "000732: Dataset not found"}})
check(r == "fail" and "000732" in reason, "MCP error format → fail")

# Claude Code isError=true
r, reason = determine_status({"content": [{"text": "Tool execution failed"}], "isError": True})
check(r == "fail", "isError=true → fail")

# success (no error key, isError false/absent)
r, reason = determine_status({})
check(r == "success", "empty dict → success")
r, reason = determine_status({"content": [{"text": "result OK"}]})
check(r == "success", "content OK no error → success")

# fallback error text detection
r, reason = determine_status({"content": [{"text": "Execute failed: error code 5"}]})
check(r == "fail" and "Execute failed" in reason, "fallback text error → fail")

# unknown
r, reason = determine_status("not a dict")
check(r == "unknown", "non-dict → unknown")

print("=== build_compressed_summary ===")

s = build_compressed_summary(
    "abc12345-abc12345-abc12345",
    "arcpy.analysis.Buffer",
    ["D:/test/01_DataBackup/roads.shp"],
    ["D:/test/02_WorkSpace/buf.shp"],
    "success"
)
check("abc12345" in s, "short id present")
check("Buffer" in s, "short tool name")
check("roads" in s, "short input path")
check("buf" in s, "short output path")
check("✅" in s, "success → ✅ marker")
check("❌" not in s, "success → no ❌")

s = build_compressed_summary(
    "xyz99999-xyz99999-xyz99999",
    "arcpy.analysis.Intersect",
    [], ["D:/test/02_WorkSpace/out.shp"],
    "fail"
)
check("❌ FAIL" in s, "fail → ❌ FAIL marker")

print("=== 全部 PASS ===")
