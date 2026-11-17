#coding=utf-8
"""
Bash命令审查Hook - 保护系统安全
规则：
1. 审查ls、dir等文件目录相关命令，禁止操作或读取cwd目录以外的任何文件或目录
2. 审查创建文件、编辑文件内容、删除文件、文件夹的Bash命令，均禁止操作cwd以外的文件和目录
3. 审查格式化磁盘的Bash命令，直接禁止执行任何格式化操作
4. 审查直接通过Bash执行的Python代码，禁止代码中出现任何cwd以外的路径
5. 审查通过Bash执行的Python代码，如果含有import arcpy就禁止执行，返回信息指引其调用arcgis-mcp-server操作
6. 01_DataBackup目录仅允许读取，禁止任何写入、创建、修改、删除操作
7. 基于LLM审查所有Bash命令是否包含删除、格式化等危险操作或是对cwd以外文件和目录进行操作、编辑、读取等行为
8. 使用多线程并行审查以提高性能
9. 处理相对路径，例如 echo test > hello.txt 实际上是在cwd中创建文件

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
import shlex
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Optional, Set

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

# 危险命令列表（直接禁止）
DANGEROUS_COMMANDS = {
    'format', 'format.com', 'diskpart', 'diskmgmt.msc',
    'fdisk', 'mkfs', 'newfs', 'mkswap', 'swapon', 'swapoff',
    'dd',
    'mkfs.ext', 'mkfs.ext2', 'mkfs.ext3', 'mkfs.ext4',
    'mkfs.ntfs', 'mkfs.fat', 'mkfs.vfat', 'mkfs.exfat',
    'fsck', 'chkdsk',
}

# 创建/写入文件类命令（需要检查目标路径）
FILE_CREATION_COMMANDS = {
    'mkdir', 'md', 'touch', 'mkfile',
    'cp', 'copy', 'xcopy', 'robocopy', 'mv', 'move', 'ren', 'rename',
    'rm', 'del', 'delete', 'rmdir', 'rd', 'deltree',
    'echo', 'tee',
    'chmod', 'chown', 'attrib', 'icacls', 'cacls',
}

# 重定向符号
REDIRECTION_CHARS = {'>', '>>', '1>', '1>>', '2>', '2>>', '>&', '<'}

# Python执行命令
PYTHON_COMMANDS = {'python', 'python2', 'python3', 'py', 'python.exe', 'pythonw.exe'}

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

def normalize_path(path: str, cwd: str = "") -> str:
    """规范化路径，转为绝对路径并统一大小写"""
    try:
        # 如果是相对路径，先转换为绝对路径
        if cwd and not os.path.isabs(path):
            path = os.path.join(cwd, path)
        return os.path.normpath(os.path.abspath(path)).lower()
    except:
        return path.lower() if path else ""

def get_top_dir(path: str, cwd: str) -> Optional[str]:
    """获取路径在cwd下的顶级目录名"""
    try:
        path_norm = normalize_path(path, cwd)
        cwd_norm = normalize_path(cwd)

        # 确保在cwd下
        if not path_norm.startswith(cwd_norm + os.sep) and path_norm != cwd_norm:
            return None

        rel_path = os.path.relpath(path_norm, cwd_norm).lower()
        return rel_path.split(os.sep)[0] if os.sep in rel_path else rel_path
    except:
        return None

def is_valid_path(path: str) -> bool:
    """
    校验字符串是否真正是路径（而非纯中文/纯文本误识别）。
    有效路径必须满足：
      - 以 Windows 盘符开头（字母: + / 或 \\），或
      - 以 Unix 斜杠开头
    纯中文、纯英文标识符（如 "Workflow ID: xxx"）不算路径。
    """
    stripped = path.strip()
    if not stripped:
        return False
    # Windows 盘符路径
    if len(stripped) >= 3 and stripped[1] == ':' and stripped[2] in '/\\':
        return stripped[0].isalpha()
    # Unix 绝对路径
    if stripped.startswith('/'):
        return True
    return False


def extract_paths_from_command(command: str, cwd: str) -> List[str]:
    """
    从Bash命令中提取可能的路径参数
    包括重定向目标路径
    """
    paths = []

    # 处理重定向操作符，提取目标文件路径
    # 匹配模式: > file, >> file, 1> file, 2> file 等
    redirect_patterns = [
        r'(?:^|\s)(?:>|>>|1>|1>>|2>|2>>)\s*["\']?([^\s"<>|]+)["\']?',
        r'(?:^|\s)(?:>|>>|1>|1>>|2>|2>>)\s*["\']([^"]+)["\']',
    ]

    for pattern in redirect_patterns:
        for match in re.finditer(pattern, command):
            path = match.group(1).strip()
            # 跳过文件描述符重定向目标（如 &1, &2 等）
            if path.startswith('&'):
                continue
            if path:
                paths.append(path)

    # 使用shlex分割命令，然后分析参数
    try:
        # 先移除重定向部分，避免干扰参数解析
        cmd_without_redirect = command
        for redirect_pattern in [r'>\s*[^\s]+', r'>>\s*[^\s]+', r'1>\s*[^\s]+', r'2>\s*[^\s]+']:
            cmd_without_redirect = re.sub(redirect_pattern, '', cmd_without_redirect)

        # 移除 heredoc 内容（<< 'DELIM' ... DELIM 或 << DELIM ... DELIM），
        # heredoc 正文是数据内容而非命令参数，不应被路径检测解析
        cmd_without_redirect = re.sub(
            r"<<\s*['\"]?\w+['\"]?\s*\n.*?\n\w+\s*$",
            '', cmd_without_redirect, flags=re.DOTALL | re.MULTILINE
        )

        # posix=False 防止 shlex 将 Windows 路径分隔符 \ 当作转义字符吞掉
        # 例如 D:\test 在 posix=True 下会变成 D:test
        parts = shlex.split(cmd_without_redirect, posix=False)
        if not parts:
            return paths

        cmd = parts[0].lower()
        if cmd == 'cd':
            return paths # cd 路径不进行路径白名单检查，因为它是上下文切换，而非文件操作

        # 检查是否是文件操作命令
        if cmd in FILE_CREATION_COMMANDS or cmd in ['ls', 'dir', 'cat', 'type', 'more', 'less']:
            # 提取所有可能是路径的参数
            for part in parts[1:]:
                # 跳过选项参数
                if part.startswith('-') or part.startswith('/'):
                    continue
                # 跳过 URL（含 :// 的字符串是协议地址，不是文件路径）
                if '://' in part:
                    continue
                # 剥离引号后再检查是否是路径
                cleaned = part.strip('"').strip("'")
                if not cleaned:
                    continue
                # 可能是路径
                if '/' in cleaned or '\\' in cleaned or ':' in cleaned or '.' in cleaned:
                    if is_valid_path(cleaned):
                        paths.append(cleaned)  # 使用剥离引号后的路径

    except ValueError:
        # shlex解析失败，使用正则回退
        pass

    # 匹配带盘符的Windows路径（仅当真正是盘符+斜杠时才匹配）
    windows_path_pattern = r'\b([a-zA-Z]:[/\\][^\s"<>|]*)'
    for match in re.finditer(windows_path_pattern, command):
        path = match.group(1)
        if '://' in path:
            continue
        path = path.strip('"').strip("'")
        if path and is_valid_path(path) and path not in paths:
            paths.append(path)

    # 匹配Unix绝对路径
    # unix_path_pattern = r'(?<=\s)/[^\s"<>|]*'
    # for match in re.finditer(unix_path_pattern, command):
    #     path = match.group(0)
    #     if path not in paths:
    #         paths.append(path)

    # 去重并过滤掉 cwd 自身（cd 到 cwd 是合法操作）
    cwd_norm = normalize_path(cwd, "")
    unique_paths = []
    seen = set()
    for p in paths:
        p_norm = normalize_path(p, cwd)
        if p_norm in seen:
            continue
        seen.add(p_norm)
        # 跳过 cwd 本身（cd 到 cwd 不需要路径白名单检查）
        if p_norm == cwd_norm:
            continue
        unique_paths.append(p)
    return unique_paths

def check_dangerous_command_and_exit(command_lower: str) -> bool:
    """检查是否包含直接禁止的危险命令"""
    parts = command_lower.split()
    if not parts:
        return True

    first_word = parts[0]

    if first_word in DANGEROUS_COMMANDS:
        print(
            f"Error: 命令 '{first_word}' 属于危险操作，已被直接禁止。\n"
            f"该命令涉及系统安全或磁盘破坏性操作，禁止执行。",
            file=sys.stderr
        )
        sys.exit(2)

    format_patterns = [
        (r'\bformat\s+[a-zA-Z]:', "磁盘格式化命令"),
        (r'\bdiskpart\b', "磁盘分区工具"),
        (r'\bdd\s+if=', "磁盘镜像/覆盖命令"),
        (r'\bmkfs\.', "文件系统创建命令"),
        (r'\bnewfs\b', "新文件系统创建"),
        (r'>\s*[a-zA-Z]:\\', "直接写入磁盘根目录"),
    ]

    for pattern, desc in format_patterns:
        if re.search(pattern, command_lower):
            print(
                f"Error: 检测到 {desc}，禁止执行。\n"
                f"该操作可能破坏系统或数据，请确保操作对象仅限于当前工作空间下的文件。",
                file=sys.stderr
            )
            sys.exit(2)

    return True

def check_protected_dirs_and_exit(path: str, protected_dirs: List[dict], cwd: str) -> bool:
    """检查是否命中重点关注目录"""
    path_norm = normalize_path(path, cwd)

    for rule in protected_dirs:
        # 确保 rule 是字典类型
        if not isinstance(rule, dict):
            continue
        protected_path = normalize_path(rule.get("path", ""), "")
        if not protected_path:
            continue

        is_match = False
        if rule.get("recursive", True):
            is_match = path_norm.startswith(protected_path + os.sep) or path_norm == protected_path
        else:
            file_dir = os.path.dirname(path_norm)
            is_match = path_norm == protected_path or file_dir == protected_path

        if is_match:
            access_type = rule.get("access", "none")
            if access_type == "none":
                print(
                    f"Error: 路径 '{path}' 位于受保护区域 '{rule.get('path', '')}'，任何操作均被禁止。\n"
                    f"该区域为系统或关键配置目录，禁止访问。",
                    file=sys.stderr
                )
                sys.exit(2)

    return True

def is_plugin_allowed_area(path: str, cwd: str) -> bool:
    """检查路径是否在 plugin 允许操作区域内（skills 目录或 bin 目录）"""
    try:
        # __file__ 位于 plugin/scripts/modify-protect-hook/bash_guard.py
        plugin_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))  # plugin/
        skills_dir = normalize_path(os.path.join(plugin_root, "skills"), "")
        bin_dir = normalize_path(os.path.join(plugin_root, "bin"), "")
        path_norm = normalize_path(path, cwd)
        return (
            path_norm.startswith(skills_dir + os.sep) or path_norm == skills_dir or
            path_norm.startswith(bin_dir + os.sep) or path_norm == bin_dir
        )
    except:
        return False


def is_skills_directory(path: str, cwd: str) -> bool:
    """兼容旧调用，委托给 is_plugin_allowed_area"""
    return is_plugin_allowed_area(path, cwd)

def check_cwd_area_and_exit(path: str, cwd: str) -> bool:
    """检查路径是否在允许的操作区域内"""
    # skills 目录 / bin 目录放行
    if is_plugin_allowed_area(path, cwd):
        return True

    # Unix 特殊设备文件放行（如 /dev/null, /dev/zero），
    # 写入真实块设备（/dev/sda 等）已由 dangerous_patterns 覆盖。
    try:
        path_lower = path.strip().lower()
        if path_lower.startswith('/dev/') and not re.search(r'/dev/[sh]da', path_lower):
            return True
    except Exception:
        pass

    try:
        cwd_norm = normalize_path(cwd, "")
        path_norm = normalize_path(path, cwd)

        # 检查是否在cwd下
        if not path_norm.startswith(cwd_norm + os.sep) and path_norm != cwd_norm:
            print(
                f"Error: 命令试图访问cwd之外的目录: '{path}'\n"
                f"所有文件操作必须限制在当前工作空间 ('{cwd}') 下的三个文件夹内。\n"
                f"提示: 请将路径修改为 cwd 下的 '02_WorkSpace' 或 '03_Result' 文件夹。\n"
                f"  正确示例: '{cwd}/02_WorkSpace/output.txt'\n"
                f"  错误示例: '{os.path.dirname(cwd)}/output.txt'",
                file=sys.stderr
            )
            sys.exit(2)

        # 获取相对路径
        rel_path = os.path.relpath(path_norm, cwd_norm).lower()

        # 如果是cwd根目录下的文件/文件夹
        if os.sep not in rel_path:
            if rel_path not in ALLOWED_CWD_SUBDIRS:
                print(
                    f"Error: 路径 '{path}' 位于cwd根目录，拒绝操作。\n"
                    f"cwd根目录仅允许以下三个文件夹存在: '01_DataBackup'（只读）、'02_WorkSpace'（过程）、'03_Result'（结果）。\n"
                    f"请直接在上述三个文件夹内创建文件或二级文件夹。\n"
                    f"  正确示例: '{cwd}/02_WorkSpace/result.shp'\n"
                    f"  错误示例: '{cwd}/temp.txt'",
                    file=sys.stderr
                )
                sys.exit(2)
        else:
            # 在子目录中，检查父目录是否在允许列表中
            top_dir = rel_path.split(os.sep)[0]
            if top_dir not in ALLOWED_CWD_SUBDIRS:
                print(
                    f"Error: 路径 '{path}' 不在允许的文件夹内。\n"
                    f"只允许在 '01_DataBackup'（只读）、'02_WorkSpace'（过程）、'03_Result'（结果）内进行操作。\n"
                    f"提示: 请在该文件夹内创建二级文件夹或直接输出至该文件夹。\n"
                    f"  正确示例: '{cwd}/02_WorkSpace/subdir/output.shp'\n"
                    f"  错误示例: '{cwd}/forbidden_dir/file.txt'",
                    file=sys.stderr
                )
                sys.exit(2)

    except Exception as e:
        print(f"Error: 路径检查过程中发生错误: {e}", file=sys.stderr)
        sys.exit(1)

    return True

def check_readonly_violation_and_exit(path: str, cwd: str, is_write_operation: bool) -> bool:
    """检查是否违反了只读目录规则"""
    if not is_write_operation:
        return True

    try:
        path_norm = normalize_path(path, cwd)
        cwd_norm = normalize_path(cwd, "")

        rel_path = os.path.relpath(path_norm, cwd_norm).lower()
        top_dir = rel_path.split(os.sep)[0] if os.sep in rel_path else rel_path

        if top_dir in READONLY_CWD_SUBDIRS:
            print(
                f"Error: 路径 '{path}' 位于只读目录 '01_DataBackup' 中，禁止写入操作。\n"
                f"01_DataBackup 目录仅允许读取，用于存放原始输入数据。\n"
                f"如需保存过程文件，请将路径修改为: '{cwd}/02_WorkSpace/your_file'\n"
                f"如需保存结果文件，请将路径修改为: '{cwd}/03_Result/your_file'",
                file=sys.stderr
            )
            sys.exit(2)

    except Exception:
        pass

    return True

def is_write_operation(command: str) -> bool:
    """判断命令是否是写入类操作"""
    command_lower = command.lower().strip()

    # 检查重定向符号（创建或覆盖文件）
    if '>' in command or '>>' in command:
        return True

    write_commands = [
        'mkdir', 'md', 'touch', 'mkfile',
        'cp', 'copy', 'xcopy', 'robocopy', 'mv', 'move', 'ren', 'rename',
        'rm', 'del', 'delete', 'rmdir', 'rd', 'deltree',
        'echo', 'tee',
        'chmod', 'chown', 'attrib', 'icacls', 'cacls',
    ]

    parts = command_lower.split()
    if not parts:
        return False

    first_word = parts[0]
    if first_word in write_commands:
        return True

    return False

def extract_python_code_from_command(command: str) -> Optional[str]:
    """从Bash命令中提取Python代码"""
    command_lower = command.lower()

    is_python = any(cmd in command_lower for cmd in PYTHON_COMMANDS)
    if not is_python:
        return None

    c_pattern = r'(?:python\d?|py|python\.exe|pythonw\.exe)\s+(?:-\S+\s+)*-c\s+["\'](.+)["\']'
    match = re.search(c_pattern, command, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1)

    echo_pattern = r'echo\s+["\']?(.+?)["\']?\s*\|\s*(?:python\d?|py)'
    match = re.search(echo_pattern, command, re.IGNORECASE)
    if match:
        return match.group(1)

    file_pattern = r'(?:python\d?|py|python\.exe|pythonw\.exe)\s+(?:-\S+\s+)*(\S+\.py)'
    match = re.search(file_pattern, command, re.IGNORECASE)
    if match:
        py_file = match.group(1)
        return f"__FILE__:{py_file}"

    return None

def check_python_code_for_arcpy_and_exit(code: str) -> bool:
    """检查Python代码是否包含arcpy或其他 GIS 引擎（Whitebox/QGIS/GDAL CLI）直调特征"""
    if not code or code.startswith("__FILE__:"):
        return True

    arcpy_patterns = [
        r'import\s+arcpy',
        r'from\s+arcpy\s+import',
        r'import\s+arcpy\s+as',
        r'from\s+arcpy',
    ]
    # 其余引擎小写二进制/导入形态（区分大小写，避免误伤文档叙述）
    engine_patterns = [
        r'import\s+whitebox',
        r'\bwhitebox_tools\b',
        r'\bqgis_process\b',
        r'\bogr2ogr\b',
        r'\bgdal(?:info|translate|warp|contour|dem|grid|rasterize|polygonize|merge|buildvrt)\b',
    ]

    for pattern in arcpy_patterns:
        if re.search(pattern, code, re.IGNORECASE):
            print(
                f"Error: Python代码中检测到arcpy导入，直接执行arcpy存在安全隐患。\n"
                f"提示: 请使用 arcgis-mcp-server 工具执行GIS操作。\n"
                f"arcgis-mcp-server 提供 execute_gis_tool 工具，可安全执行 arcpy 工具并确保输出路径合规。",
                file=sys.stderr
            )
            sys.exit(2)

    for pattern in engine_patterns:
        if re.search(pattern, code):
            print(
                f"Error: Python代码中检测到 GIS 引擎 CLI（Whitebox/QGIS/GDAL）直调特征。\n"
                f"提示: 请使用 arcgis-mcp-server 的 execute_gis_tool（tool_name 前缀 wbt_/qgis_/gdal_ 可指定引擎）执行GIS操作。",
                file=sys.stderr
            )
            sys.exit(2)

    return True

def check_python_code_for_external_paths_and_exit(code: str, cwd: str) -> bool:
    """检查Python代码是否包含cwd以外的路径"""
    if not code or code.startswith("__FILE__:"):
        return True

    path_patterns = [
        r'["\']([a-zA-Z]:[/\\][^"\']+)["\']',
        r'["\'](/(?:[^"\']+))["\']',
    ]

    cwd_norm = normalize_path(cwd, "")

    for pattern in path_patterns:
        for match in re.finditer(pattern, code):
            path = match.group(1)
            path_norm = normalize_path(path, "")

            if not path_norm.startswith(cwd_norm + os.sep) and path_norm != cwd_norm:
                if 'site-packages' not in path_norm and 'lib\\python' not in path_norm and not is_skills_directory(path, cwd):
                    print(
                        f"Error: Python代码中包含cwd以外的路径: '{path}'\n"
                        f"Python脚本中的所有文件路径必须位于当前工作空间 ('{cwd}') 下的三个文件夹内。\n"
                        f"提示: 请将路径修改为 '01_DataBackup'（只读）、'02_WorkSpace'（过程）或 '03_Result'（结果）下的路径。\n"
                        f"  正确示例: '{cwd}/02_WorkSpace/data.shp'",
                        file=sys.stderr
                    )
                    sys.exit(2)

    return True

def check_llm_review_and_exit(command: str, cwd: str) -> bool:
    """使用启发式规则审查Bash命令的安全性"""
    dangerous_patterns = [
        r'\brm\s+-rf\s+/',
        r'\bdel\s+/[qQ]',
        r'\brd\s+/s\s+/q',
        r'\brmdir\s+/s\s+/q',
        r'\breg\s+delete\b',
        r'\breg\s+edit\b',
        r'\bwget\s+.*\|\s*sh\b',
        r'\bcurl\s+.*\|\s*sh\b',
        r'\bsudo\s+rm\b',
        r'>\s*/dev/[sh]da',
        r'\bdd\s+if=.*of=/dev',
    ]

    for pattern in dangerous_patterns:
        if re.search(pattern, command, re.IGNORECASE):
            print(
                f"Error: 检测到潜在危险操作模式，禁止执行。\n"
                f"匹配的禁止模式: {pattern}\n"
                f"请确保所有操作仅针对当前工作空间 ('{cwd}') 下的文件和目录。",
                file=sys.stderr
            )
            sys.exit(2)

    system_dirs = [
        (r'[cC]:[/\\][wW]indows', "C:\\Windows"),
        (r'[cC]:[/\\][pP]rogram\s+[fF]iles', "C:\\Program Files"),
        (r'[cC]:[/\\][pP]rogram[dD]ata', "C:\\ProgramData"),
        (r'(?<![A-Za-z0-9_./])/etc/', "/etc"),
        (r'(?<![A-Za-z0-9_./])/usr/', "/usr"),
        (r'(?<![A-Za-z0-9_./])/bin/', "/bin"),
        (r'(?<![A-Za-z0-9_./])/sbin/', "/sbin"),
        (r'(?<![A-Za-z0-9_./])/sys/', "/sys"),
        (r'(?<![A-Za-z0-9_./])/boot/', "/boot"),
        (r'(?<![A-Za-z0-9_./])/proc/', "/proc"),
        (r'(?<![A-Za-z0-9_./])/lib/', "/lib"),
        (r'(?<![A-Za-z0-9_./])/lib64/', "/lib64"),
        # 注意：/dev/ 不在此处拦截，因为 /dev/null 是合法的重定向目标。
        # 写入真实设备（如 /dev/sda）已由上方 dangerous_patterns 中 r'>\\s*/dev/[sh]da' 覆盖。
    ]

    for sys_dir, dir_name in system_dirs:
        if re.search(sys_dir, command, re.IGNORECASE):
            print(
                f"Error: 命令试图访问系统目录 '{dir_name}'，禁止执行。\n"
                f"系统目录包含操作系统关键文件，不允许修改。\n"
                f"提示: 请确保所有操作仅在当前工作空间 ('{cwd}') 下进行。",
                file=sys.stderr
            )
            sys.exit(2)

    return True

def check_single_path_task(args: Tuple[str, str, str, List[dict], bool]) -> bool:
    """检查单个路径的完整规则"""
    path, cwd, command, protected_dirs, write_op = args

    # 1. 检查重点关注目录
    check_protected_dirs_and_exit(path, protected_dirs, cwd)

    # 2. 检查cwd规则
    check_cwd_area_and_exit(path, cwd)

    # 3. 检查只读目录违规
    check_readonly_violation_and_exit(path, cwd, write_op)

    return True

def check_paths_parallel(paths: List[str], cwd: str, command: str,
                         protected_dirs: List[dict], is_write_op: bool,
                         max_workers: int = 4):
    """使用多线程并行检查多个路径"""
    if not paths:
        return

    task_args = [
        (path, cwd, command, protected_dirs, is_write_op)
        for path in paths
    ]

    with ThreadPoolExecutor(max_workers=min(max_workers, len(task_args))) as executor:
        future_to_path = {
            executor.submit(check_single_path_task, args): args
            for args in task_args
        }

        for future in as_completed(future_to_path):
            try:
                result = future.result()
                if not result:
                    print("Error: Bash命令路径检查未通过，具体原因已由检查函数说明。", file=sys.stderr)
                    sys.exit(2)
            except SystemExit as e:
                sys.exit(e.code if e.code else 2)
            except Exception as e:
                print(f"Error: 禁止读取或写入内容到不允许的目录: {e}", file=sys.stderr)
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

        command = tool_input.get("command", "")

        protected_dirs = load_protected_dirs()

        # 1. 检查直接禁止的危险命令
        check_dangerous_command_and_exit(command.lower())

        # 2. 提取命令中的路径（包括重定向目标）
        paths_in_command = extract_paths_from_command(command, cwd)

        # 3. 判断是否是写入操作
        write_op = is_write_operation(command)

        # 4. 使用多线程并行检查路径
        check_paths_parallel(paths_in_command, cwd, command, protected_dirs, write_op)

        # 5. 检查Python代码
        python_code = extract_python_code_from_command(command)
        if python_code:
            check_python_code_for_arcpy_and_exit(python_code)
            check_python_code_for_external_paths_and_exit(python_code, cwd)

        # 6. LLM辅助审查
        check_llm_review_and_exit(command, cwd)

        print(f"Bash command allowed: {command[:50]}...")
        sys.exit(0)

    except SystemExit:
        raise
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
