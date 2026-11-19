"""Execute unchanged source hooks with path and structured-result compatibility fixes."""
import runpy
import sys
import json
import os
import inspect

source = sys.argv[1]


def _expand_platform_vars(value: str) -> str:
    """按平台展开路径里的临时目录变量后再走 expandvars。

    os.path.expandvars 对未定义变量保留字面量，而 protected_dirs.json 里的
    ${TEMP}（Windows）在 Linux 上未定义、${TMPDIR}（POSIX）在 Windows 上未定义，
    字面量残留会让对应规则匹配不到任何真实路径。这里做双向回退。
    """
    if os.name == "nt":
        value = value.replace("${TMPDIR}", os.environ.get("TEMP", os.environ.get("TMP", "")))
    else:
        value = value.replace("${TEMP}", os.environ.get("TMPDIR", "/tmp"))
        value = value.replace("${TMP}", os.environ.get("TMPDIR", "/tmp"))
    return os.path.expandvars(value)


namespace = runpy.run_path(source, run_name="linktool_migrated_hook")
if "normalize_path" in namespace:
    normalize = namespace["normalize_path"]
    parameters = len(inspect.signature(normalize).parameters)
    # Source is_skills_directory calls normalize_path(path, "") although its
    # declaration accepts only path. Preserve its intended bundled-skills allow rule.
    def compatible_normalize(path, _cwd=""):
        expanded = _expand_platform_vars(path)
        return normalize(expanded, _cwd) if parameters > 1 else normalize(expanded)
    normalize.__globals__["normalize_path"] = compatible_normalize
if "determine_status" in namespace:
    original_status = namespace["determine_status"]
    def compatible_status(response):
        if not isinstance(response, dict) or response.get("isError") or response.get("error"):
            return original_status(response)
        flags = []
        errors = []
        def visit(value):
            if isinstance(value, dict):
                if isinstance(value.get("success"), bool):
                    flags.append(value["success"])
                    if not value["success"]:
                        errors.append(str(value.get("error") or value.get("message") or "GIS operation failed"))
                if isinstance(value.get("result"), dict):
                    visit(value["result"])
        for block in response.get("content", []):
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                try:
                    visit(json.loads(block["text"]))
                except (ValueError, TypeError):
                    pass
        if False in flags:
            return "fail", "; ".join(errors)[:200]
        if True in flags:
            return "success", ""
        return original_status(response)
    original_status.__globals__["determine_status"] = compatible_status
namespace["main"]()
