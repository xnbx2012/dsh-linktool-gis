#coding=utf-8
"""
GIS操作保护Hook - 保护GIS数据输出路径
规则：
1. 禁止GIS数据输出到cwd以外的目录
2. 禁止GIS数据输出到cwd根目录（必须在三个允许的子文件夹内）
3. 禁止GIS数据输出到01_DataBackup目录（该目录仅允许读取）
4. 支持重点关注目录配置
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
import io
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Optional

# 强制使用UTF-8编码
sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8', errors='replace')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 允许的根目录文件夹（相对于cwd，全部小写用于比较）
ALLOWED_CWD_SUBDIRS = {"01_databackup", "02_workspace", "03_result"}

# 仅允许读取的目录（禁止GIS写入）
READONLY_CWD_SUBDIRS = {"01_databackup"}

# 重点关注目录配置路径
PROTECTED_DIRS_CONFIG = os.path.join(os.path.dirname(__file__), "protected_dirs.json")

def is_skills_directory(path: str, cwd: str = "") -> bool:
    """检查路径是否在 skills 目录内（与scripts同级的skills目录）"""
    try:
        # __file__ 位于 plugin/scripts/modify-protect-hook/gis.py
        plugin_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))  # plugin/
        skills_dir = normalize_path(os.path.join(plugin_root, "skills"), "")
        path_norm = normalize_path(path)
        return path_norm.startswith(skills_dir + os.sep) or path_norm == skills_dir
    except:
        return False

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
    """检查是否命中重点关注目录保护规则，如果命中直接退出"""
    file_path_norm = normalize_path(file_path)

    for rule in protected_dirs:
        # 确保 rule 是字典类型
        if not isinstance(rule, dict):
            continue
        protected_path = normalize_path(rule.get("path", ""))
        if not protected_path:
            continue

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
                    f"Error: GIS输出路径 '{file_path}' 位于受保护区域 '{rule.get('path', '')}'，操作被禁止。\n"
                    f"受保护区域为系统目录或敏感配置区域，禁止写入GIS数据。",
                    file=sys.stderr
                )
                sys.exit(2)
            elif access_type == "read":
                print(
                    f"Error: GIS输出路径 '{file_path}' 位于受保护区域 '{rule.get('path', '')}'，写入操作被禁止。\n"
                    f"该区域仅允许读取，不允许写入。",
                    file=sys.stderr
                )
                sys.exit(2)

    return True

def check_readonly_violation(output_path: str, cwd: str) -> bool:
    """
    检查是否试图写入只读目录
    01_DataBackup目录禁止任何GIS数据写入
    """
    try:
        cwd_norm = normalize_path(cwd)
        output_path_norm = normalize_path(output_path)

        # 获取相对路径
        rel_path = os.path.relpath(output_path_norm, cwd_norm).lower()

        # 检查是否在只读目录下
        top_dir = rel_path.split(os.sep)[0] if os.sep in rel_path else rel_path

        if top_dir in READONLY_CWD_SUBDIRS:
            print(
                f"Error: GIS数据 '{output_path}' 试图输出到只读目录 '01_DataBackup'，操作被拒绝。\n"
                f"01_DataBackup 目录仅允许读取，用于存放原始输入数据，禁止任何GIS数据写入。\n"
                f"如需保存过程数据，请将路径修改为: '{cwd}/02_WorkSpace/your_output'\n"
                f"如需保存结果数据，请将路径修改为: '{cwd}/03_Result/your_output'",
                file=sys.stderr
            )
            sys.exit(2)

    except Exception:
        pass

    return True

def validate_gis_output_path(output_path: str, cwd: str, tool_name: str = "") -> bool:
    """
    验证GIS输出路径是否合法
    """
    if not output_path or not isinstance(output_path, str):
        return True  # 没有指定路径，由GIS工具自己处理

    output_path_norm = normalize_path(output_path)
    cwd_norm = normalize_path(cwd)

    # 1. 检查是否在cwd外部
    if not output_path_norm.startswith(cwd_norm + os.sep) and output_path_norm != cwd_norm:
        print(
            f"Error: GIS数据 '{output_path}' 试图输出到cwd ('{cwd}') 之外的目录，操作被拒绝。\n"
            f"GIS数据只能输出到当前工作空间下的 '02_WorkSpace'（过程数据）或 '03_Result'（结果数据）文件夹。\n"
            f"提示: 请修改输出路径，将数据保存到上述文件夹内。\n"
            f"  正确示例: '{cwd}/02_WorkSpace/output.gdb'\n"
            f"  正确示例: '{cwd}/03_Result/result.shp'\n"
            f"  错误示例: 'D:/其他目录/output.gdb'",
            file=sys.stderr
        )
        sys.exit(2)

    # 2. 获取相对路径
    rel_path = os.path.relpath(output_path_norm, cwd_norm).lower()

    # 3. 检查是否在允许的子目录中
    if os.sep not in rel_path:
        # 试图直接输出到cwd根目录
        print(
            f"Error: GIS数据 '{output_path}' 试图输出到cwd根目录，操作被拒绝。\n"
            f"GIS数据不能直接输出到 '{cwd}' 根目录，必须位于 '02_WorkSpace' 或 '03_Result' 子文件夹内。\n"
            f"提示: 请创建二级文件夹或在上述文件夹内直接输出。\n"
            f"  正确示例: '{cwd}/02_WorkSpace/output.gdb'\n"
            f"  正确示例: '{cwd}/03_Result/result.shp'\n"
            f"  错误示例: '{cwd}/output.gdb'",
            file=sys.stderr
        )
        sys.exit(2)

    # 4. 检查父目录是否在允许列表中
    top_dir = rel_path.split(os.sep)[0]
    if top_dir not in ALLOWED_CWD_SUBDIRS:
        print(
            f"Error: GIS数据 '{output_path}' 输出路径不在允许的文件夹内。\n"
            f"只允许输出到 '01_DataBackup'（只读）、'02_WorkSpace'（过程）、'03_Result'（结果）文件夹。\n"
            f"提示: 请在上述文件夹内创建二级文件夹或直接输出至该文件夹。\n"
            f"  正确示例: '{cwd}/02_WorkSpace/subdir/output.gdb'\n"
            f"  错误示例: '{cwd}/forbidden_dir/output.gdb'",
            file=sys.stderr
        )
        sys.exit(2)

    # 5. 检查是否在只读目录中
    if top_dir in READONLY_CWD_SUBDIRS:
        print(
            f"Error: GIS数据 '{output_path}' 试图输出到只读目录 '01_DataBackup'，操作被拒绝。\n"
            f"01_DataBackup 目录仅允许读取，用于存放原始输入数据，禁止任何GIS数据写入。\n"
            f"如需保存过程数据，请将路径修改为: '{cwd}/02_WorkSpace/your_output'\n"
            f"如需保存结果数据，请将路径修改为: '{cwd}/03_Result/your_output'",
            file=sys.stderr
        )
        sys.exit(2)

    return True

def is_only_filename(path: str) -> bool:
    """判断是否为纯文件名（不含路径分隔符和上级目录引用）"""
    if not path or not isinstance(path, str):
        return False
    import re
    if re.match(r'^[A-Za-z]:', path):
        return False
    if '/' in path or '\\' in path or '..' in path:
        return False
    return True

def _combine_out_location_and_name(parameters: dict) -> List[Tuple[str, str]]:
    """
    将 out_location / out_name 或类似的"目录+文件名"参数组合成完整路径。
    规则：
    - out_location + out_name -> 完整路径，跳过单独的 out_location
    - out_workspace + out_name -> 完整路径，跳过单独的 out_workspace
    - 任何含路径分隔符的 out_* 参数直接作为完整路径
    - 纯文件名跳过（除非可与 out_location 组合）
    """
    output_paths = []

    if not isinstance(parameters, dict):
        return output_paths

    output_keywords = [
        'out_path', 'out_workspace', 'out_feature_class', 'out_raster',
        'out_table', 'out_dataset', 'output_path', 'output_workspace',
        'workspace', 'scratch_workspace', 'out_folder', 'out_file',
        'out_featureclass', 'out_features', 'out_feature_dataset',
        'out_raster_dataset', 'out_rasterdataset', 'out_table_name',
        'out_geodatabase', 'out_gdb_path', 'out_tin', 'out_las_dataset',
        'out_mosaic_dataset', 'out_slpk', 'out_service_definition',
        'output_feature_class', 'output_featureclass', 'output_features',
        'output_fc', 'output_table', 'output_dataset', 'output_file',
        'output_folder', 'output_location', 'output_geodatabase', 'output_locator',
    ]

    # 常见"目录"参数名（与 out_name / out_file 组合）
    location_keys = {'out_location', 'out_workspace', 'out_folder', 'out_folder_path', 'output_workspace', 'workspace'}

    # 明确不是路径的 out_* / output_* 参数（值是枚举/类型/范围等非路径内容）
    NON_PATH_OUT_PARAMS = {
        'out_coor_system', 'out_spatial_reference', 'out_extent',
        'out_statistics', 'out_fields', 'out_field_name',
        'out_stat_type', 'out_type', 'out_format', 'out_units',
        'out_linear_units', 'out_horizontal_unit', 'out_alias',
        'out_option', 'out_schema', 'out_geometry_type',
        'out_coordinate_system', 'out_area_units',
        'out_relationship_type', 'out_event_properties',
        'output_type', 'output_format', 'output_method', 'output_mode',
        'output_record_option', 'output_scale', 'output_zone',
        'output_field_type', 'output_field_alias', 'output_field_decimals_or_length',
        'output_time_type', 'output_time_format', 'output_time_zone', 'output_time_field',
        'output_coordinate_format', 'output_path_shape', 'output_variables',
        'output_classes', 'output_conditions', 'output_all',
        'output_slope_measurement', 'output_measurement', 'output_value_field',
    }

    for key, value in parameters.items():
        if not isinstance(value, str) or not value.strip():
            continue

        key_lower = key.lower()

        # 尝试与 out_name / out_file 组合成完整路径
        if key_lower in location_keys:
            out_name = parameters.get('out_name') or parameters.get('out_file', '')
            if out_name and is_only_filename(out_name):
                # 合并目录 + 文件名
                combined = os.path.join(value.rstrip(os.sep), out_name)
                output_paths.append(('out_location+out_name', combined))
                continue
            # 无法组合，fallback 为原路径
            if not is_only_filename(value):
                output_paths.append((key, value))
            continue

        # out_name / out_file：若已在上一步组合则跳过
        if key_lower in {'out_name', 'out_file'}:
            # 检查是否已被 out_location 组合
            if any(param == 'out_location+out_name' for param, _ in output_paths):
                continue
            # 无法组合则跳过
            if is_only_filename(value):
                continue
            output_paths.append((key, value))
            continue

        is_output_param = any(kw in key_lower for kw in output_keywords)

        # 排除已知的非路径 out_* 参数（如坐标系WKT、空间范围、统计配置等）
        is_excluded_out_param = key_lower in NON_PATH_OUT_PARAMS

        if is_excluded_out_param:
            continue

        if key_lower.startswith('out_') or key_lower.startswith('output_') or is_output_param:
            if not is_only_filename(value):
                output_paths.append((key, value))

    return output_paths

def check_single_output_path(path_info: Tuple[str, str, str, List[dict], str]) -> bool:
    """
    检查单个输出路径的完整规则
    """
    param_name, output_path, tool_name, protected_dirs, cwd = path_info

    # 0. skills 目录放行
    if is_skills_directory(output_path, cwd):
        return True

    # 1. 检查重点关注目录
    check_protected_dirs_and_exit(output_path, protected_dirs)

    # 2. 验证GIS输出路径
    validate_gis_output_path(output_path, cwd, tool_name)

    # 3. 检查只读目录违规
    check_readonly_violation(output_path, cwd)

    return True

def check_output_paths_parallel(output_paths: List[Tuple[str, str]], tool_name: str,
                                 protected_dirs: List[dict], cwd: str,
                                 max_workers: int = 4):
    """
    使用多线程并行检查多个输出路径
    """
    if not output_paths:
        return

    task_args = [
        (param_name, output_path, tool_name, protected_dirs, cwd)
        for param_name, output_path in output_paths
    ]

    with ThreadPoolExecutor(max_workers=min(max_workers, len(task_args))) as executor:
        future_to_path = {
            executor.submit(check_single_output_path, args): args
            for args in task_args
        }

        for future in as_completed(future_to_path):
            try:
                result = future.result()
                if not result:
                    print("Error: GIS输出路径检查未通过，具体原因已由检查函数说明。", file=sys.stderr)
                    sys.exit(2)
            except SystemExit as e:
                sys.exit(e.code if e.code else 2)
            except Exception as e:
                print(f"Error: GIS输出路径检查过程中发生错误: {e}", file=sys.stderr)
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

        parameters = tool_input.get("parameters", {})

        protected_dirs = load_protected_dirs()

        # 提取所有输出路径
        output_paths = _combine_out_location_and_name(parameters)

        # 使用多线程并行执行路径检查
        check_output_paths_parallel(output_paths, tool_name, protected_dirs, cwd)

        print(f"GIS operation allowed: {tool_name}")
        sys.exit(0)

    except SystemExit:
        raise
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
