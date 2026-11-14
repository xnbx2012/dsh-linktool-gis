#coding=utf-8
"""
文件操作保护Hook - 保护文件系统安全
规则：
1. cwd下只允许01_DataBackup、02_WorkSpace、03_Result三个文件夹，该目录下创建任何其它文件、文件夹均不允许
2. cwd以外的所有文件和文件夹均不允许任何读、写、编辑、创建、删除、Grep、Glob、NotebookEdit操作
3. 01_DataBackup目录仅允许读取，禁止任何写入、创建、修改、删除操作
4. 支持重点关注目录配置（protected_dirs.json）
5. 使用多线程并行审查以提高性能

注意：
- 所有阻止操作必须通过 print 到 stderr 并 sys.exit(2) 实现
- 程序内部错误使用 sys.exit(1)
- 所有输出强制使用UTF-8编码
- 所有错误信息必须精准说明原因，并引导至正确路径
"""

import json
import sys
import os
import re
import io
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Optional
from threading import Lock

# 强制使用UTF-8编码
sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8', errors='replace')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 允许的根目录文件夹（相对于cwd，全部小写用于比较）
ALLOWED_CWD_SUBDIRS = {"01_databackup", "02_workspace", "03_result"}

# 仅允许读取的目录（禁止写入）
READONLY_CWD_SUBDIRS = {"01_databackup"}

# 重点关注目录配置路径
PROTECTED_DIRS_CONFIG = os.path.join(os.path.dirname(__file__), "protected_dirs.json")

def _fmt_cwd(cwd: str) -> str:
    """获取cwd的可用路径别名（带引号）"""
    return f"'{cwd}'" if cwd else "当前工作空间"

def _fmt_readonly_suggest(out_type: str = "过程") -> str:
    """生成01_DataBackup只读违规的引导信息"""
    if out_type == "结果":
        return (
            "如需保存结果文件，请将输出路径修改为 cwd 下的 '03_Result' 文件夹。\n"
            "    示例: {cwd}/03_Result/your_output_file"
        )
    return (
        "如需保存过程文件，请将输出路径修改为 cwd 下的 '02_WorkSpace' 文件夹。\n"
        "    示例: {cwd}/02_WorkSpace/your_output_file"
    )

def _fmt_cwd_root_suggest(cwd: str) -> str:
    return (
        f"请在 cwd 下的 '02_WorkSpace' 或 '03_Result' 文件夹内创建文件。\n"
        "    示例: '{cwd}/02_WorkSpace/result.txt'"
    )

def _fmt_plugin_suggest(cwd: str) -> str:
    return (
        "plugin 目录仅供 Skill 脚本内部使用，不应直接读写。\n"
        f"请将文件操作限制在当前工作空间 ({cwd}) 下的 '02_WorkSpace' 或 '03_Result' 文件夹内。"
    )

def is_skills_directory(path: str, cwd: str = "") -> bool:
    """检查路径是否在 skills 目录内（与scripts同级的skills目录）"""
    try:
        # __file__ 位于 plugin/scripts/modify-protect-hook/main.py
        plugin_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))  # plugin/
        skills_dir = normalize_path(os.path.join(plugin_root, "skills"), "")
        path_norm = normalize_path(path)
        return path_norm.startswith(skills_dir + os.sep) or path_norm == skills_dir
    except:
        return False

# 用于多线程的错误收集
error_lock = Lock()
found_errors = []

def load_protected_dirs() -> List[dict]:
    """加载重点关注目录配置"""
    if not os.path.exists(PROTECTED_DIRS_CONFIG):
        return []
    try:
        with open(PROTECTED_DIRS_CONFIG, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # 支持 { "protected_dirs": [...] } 格式
            if isinstance(data, dict) and "protected_dirs" in data:
                dirs = data["protected_dirs"]
            # 支持直接是列表的格式
            elif isinstance(data, list):
                dirs = data
            else:
                return []
            # 确保返回的列表只包含字典类型
            return [item for item in dirs if isinstance(item, dict)]
    except Exception as e:
        print(f"Warning: 无法加载protected_dirs.json: {e}", file=sys.stderr)
        return []

def normalize_path(path: str) -> str:
    """规范化路径，转为绝对路径并统一大小写（Windows不区分大小写）"""
    try:
        return os.path.normpath(os.path.abspath(path)).lower()
    except:
        return path.lower() if path else ""

def check_protected_dirs_and_exit(file_path: str, protected_dirs: List[dict]) -> bool:
    """
    检查是否命中重点关注目录保护规则
    如果命中，直接输出错误并退出
    """
    file_path_norm = normalize_path(file_path)

    for rule in protected_dirs:
        # 确保 rule 是字典类型
        if not isinstance(rule, dict):
            continue
        protected_path = normalize_path(rule.get("path", ""))
        if not protected_path:
            continue

        # 检查是否匹配
        is_match = False
        if rule.get("recursive", True):
            is_match = file_path_norm.startswith(protected_path + os.sep) or file_path_norm == protected_path
        else:
            file_dir = os.path.dirname(file_path_norm)
            is_match = file_path_norm == protected_path or file_dir == protected_path

        if is_match:
            access_type = rule.get("access", "none")
            if access_type == "none":
                print(
                    f"Error: 路径 '{file_path}' 位于受保护区域 '{rule.get('path', '')}'，任何操作均被禁止。\n"
                    f"受保护区域通常包含系统目录、配置文件或敏感数据，禁止任何读写操作。",
                    file=sys.stderr
                )
                sys.exit(2)
            elif access_type == "read":
                print(
                    f"Error: 路径 '{file_path}' 位于受保护区域 '{rule.get('path', '')}'，写入/编辑/删除操作被禁止。\n"
                    f"该区域仅允许读取操作，禁止写入。",
                    file=sys.stderr
                )
                sys.exit(2)

    return True

def is_within_allowed_subdir(file_path: str, cwd: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    检查文件是否在cwd下允许的子目录中
    返回: (是否允许, 错误类型, 错误信息)
    """
    try:
        cwd_norm = normalize_path(cwd)
        file_path_norm = normalize_path(file_path)

        # 确保文件在cwd下
        if not file_path_norm.startswith(cwd_norm + os.sep) and file_path_norm != cwd_norm:
            return False, "cwd_external", (
                f"Error: 路径 '{file_path}' 位于cwd ('{cwd}')之外的目录，任何操作均被禁止。\n"
                f"只允许操作当前工作空间下的三个文件夹: '01_DataBackup'（只读）、'02_WorkSpace'（读写）、'03_Result'（读写）。\n"
                f"提示: 请将操作限制在上述三个文件夹内。\n"
                f"  读取文件示例: '{cwd}/01_DataBackup/input.shp'\n"
                f"  写入文件示例: '{cwd}/02_WorkSpace/output.txt'"
            )

        # 获取相对路径
        rel_path = os.path.relpath(file_path_norm, cwd_norm).lower()

        # 如果是cwd根目录下的文件/文件夹
        if os.sep not in rel_path:
            # 检查是否是允许的目录之一
            if rel_path in ALLOWED_CWD_SUBDIRS:
                return True, None, None
            else:
                return False, "cwd_root_forbidden", (
                    f"Error: 路径 '{file_path}' 位于cwd根目录，操作被拒绝。\n"
                    f"cwd根目录仅允许以下文件夹存在: '01_DataBackup'、'02_WorkSpace'、'03_Result'。\n"
                    f"请直接在上述三个文件夹内创建文件或二级文件夹。\n"
                    f"  正确示例: '{cwd}/02_WorkSpace/result.txt'\n"
                    f"  错误示例: '{cwd}/temp.txt'"
                )
        else:
            # 在子目录中，检查父目录是否在允许列表中
            top_dir = rel_path.split(os.sep)[0]
            if top_dir in ALLOWED_CWD_SUBDIRS:
                return True, None, None
            else:
                return False, "subdir_forbidden", (
                    f"Error: 路径 '{file_path}' 不在允许的文件夹内。\n"
                    f"只允许在以下文件夹内操作: '01_DataBackup'（只读）、'02_WorkSpace'（过程文件）、'03_Result'（结果文件）。\n"
                    f"提示: 请在该文件夹内创建二级文件夹或直接输出至该文件夹。\n"
                    f"  正确示例: '{cwd}/02_WorkSpace/subdir/output.shp'"
                )
    except Exception as e:
        return False, "check_error", f"Error: 路径检查过程中发生错误: {e}"

def check_readonly_violation(file_path: str, cwd: str, tool_name: str) -> bool:
    """
    检查是否违反了只读目录规则
    01_DataBackup目录仅允许读取操作（Read/Glob/Grep），禁止写入类操作
    """
    # 只有写入类操作才需要检查
    write_operations = {"Write", "Edit", "Delete"}
    if tool_name not in write_operations:
        return True

    try:
        cwd_norm = normalize_path(cwd)
        file_path_norm = normalize_path(file_path)

        # 获取相对路径
        rel_path = os.path.relpath(file_path_norm, cwd_norm).lower()

        # 检查是否在只读目录下
        top_dir = rel_path.split(os.sep)[0] if os.sep in rel_path else rel_path

        if top_dir in READONLY_CWD_SUBDIRS:
            is_write = tool_name in {"Write", "Edit", "Delete"}
            if is_write:
                print(
                    f"Error: 路径 '{file_path}' 位于只读目录 '01_DataBackup' 中，禁止执行{tool_name}操作。\n"
                    f"01_DataBackup 目录仅允许读取，用于存放原始输入数据。\n"
                    f"如需保存过程文件，请将路径修改为: '{cwd}/02_WorkSpace/your_file'\n"
                    f"如需保存结果文件，请将路径修改为: '{cwd}/03_Result/your_file'",
                    file=sys.stderr
                )
            sys.exit(2)

    except Exception:
        pass

    return True

def extract_paths_from_grep_pattern(pattern: str, cwd: str) -> List[str]:
    """从Grep模式中提取可能的路径"""
    paths = []
    # 尝试匹配常见的路径模式
    path_pattern = r'[a-zA-Z]:\[^:*?"<>|]*|\/[^:*?"<>|]*'
    matches = re.findall(path_pattern, pattern)
    for match in matches:
        if os.path.exists(match) or os.path.isabs(match):
            paths.append(match)
    return paths

def check_single_path(path_info: Tuple[str, str, str, List[dict], str]) -> bool:
    """
    检查单个路径的完整规则
    """
    path_type, file_path, tool_name, protected_dirs, cwd = path_info

    # 0. skills 目录放行
    if is_skills_directory(file_path, cwd):
        return True

    # 1. 检查重点关注目录
    check_protected_dirs_and_exit(file_path, protected_dirs)

    # 2. 检查cwd规则
    allowed, error_type, error_msg = is_within_allowed_subdir(file_path, cwd)
    if not allowed:
        print(error_msg, file=sys.stderr)
        sys.exit(2)

    # 3. 检查只读目录违规（写入操作）
    check_readonly_violation(file_path, cwd, tool_name)

    return True

def check_paths_parallel(paths_to_check: List[Tuple[str, str]], tool_name: str,
                         protected_dirs: List[dict], cwd: str,
                         max_workers: int = 4):
    """
    使用多线程并行检查多个路径
    """
    if not paths_to_check:
        return

    # 准备任务参数
    task_args = [
        (path_type, file_path, tool_name, protected_dirs, cwd)
        for path_type, file_path in paths_to_check
    ]

    # 使用线程池并行执行检查
    with ThreadPoolExecutor(max_workers=min(max_workers, len(task_args))) as executor:
        future_to_path = {
            executor.submit(check_single_path, args): args
            for args in task_args
        }

        for future in as_completed(future_to_path):
            try:
                result = future.result()
                if not result:
                    print("Error: 文件操作路径检查未通过，具体原因已由检查函数说明。", file=sys.stderr)
                    sys.exit(2)
            except SystemExit as e:
                sys.exit(e.code if e.code else 2)
            except Exception as e:
                print(f"Error: 路径检查过程中发生错误: {e}", file=sys.stderr)
                sys.exit(2)

def main():
    try:
        # 读取输入
        input_data = sys.stdin.read()

        # 解析JSON
        try:
            hook_event = json.loads(input_data)
        except json.JSONDecodeError as e:
            print(f"Error: 无法解析 JSON 输入 - {e}", file=sys.stderr)
            sys.exit(1)

        # 检查hook_event是否为字典
        if not isinstance(hook_event, dict):
            print(f"Error: 输入数据不是有效的JSON对象", file=sys.stderr)
            sys.exit(1)

        cwd = hook_event.get("cwd", "")
        tool_name = hook_event.get("tool_name", "")
        tool_input = hook_event.get("tool_input", {})

        # 检查tool_input是否为字典
        if not isinstance(tool_input, dict):
            print(f"Error: tool_input 不是有效的字典对象", file=sys.stderr)
            sys.exit(1)

        protected_dirs = load_protected_dirs()

        # 收集需要检查的路径
        paths_to_check = []

        if tool_name in ["Read", "Edit", "Write", "Delete"]:
            file_path = tool_input.get("file_path")
            if file_path:
                paths_to_check.append(("文件", file_path))

            # 禁止 Read 工具读取 SKILL.md 文件
            if tool_name == "Read" and file_path:
                if os.path.basename(file_path).lower() == "skill.md":
                    print(
                        f"Error: 禁止使用 Read 工具读取 SKILL.md 文件。\n"
                        f"SKILL.md 是技能定义文件，只能通过 Skill 工具以技能名称加载。\n"
                        f"提示: 请使用 Skill 工具，传入 Skill 名称（如 'gis-task-plan'）即可加载对应技能，"
                        f"而不是用 Read 工具直接读取技能文件。",
                        file=sys.stderr
                    )
                    sys.exit(2)

        elif tool_name == "NotebookEdit":
            notebook_path = tool_input.get("notebook_path")
            if notebook_path:
                paths_to_check.append(("Notebook", notebook_path))

        elif tool_name == "Glob":
            pattern = tool_input.get("pattern", "")
            path = tool_input.get("path", "")
            if path:
                paths_to_check.append(("Glob目录", path))
            # 尝试从pattern中提取路径
            if pattern and (os.path.isabs(pattern) or ":" in pattern):
                base_path = pattern.split("*")[0] if "*" in pattern else pattern
                if os.path.isabs(base_path):
                    paths_to_check.append(("Glob模式", base_path))

        elif tool_name == "Grep":
            path = tool_input.get("path", "")
            pattern = tool_input.get("pattern", "")
            if path:
                paths_to_check.append(("Grep目录", path))
            # 检查pattern中是否包含路径
            extracted_paths = extract_paths_from_grep_pattern(pattern, cwd)
            for p in extracted_paths:
                paths_to_check.append(("Grep模式路径", p))

        # 使用多线程并行执行路径检查
        check_paths_parallel(paths_to_check, tool_name, protected_dirs, cwd)

        print(f"Operation allowed for {tool_name}")
        sys.exit(0)

    except SystemExit:
        raise
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
