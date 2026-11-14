# -*- coding: utf-8 -*-
"""
数据备份 Hook（PreToolUse）

功能：
- 检测破坏性 GIS 工具（会原地修改输入数据的工具）
- 若输入数据在只读目录 01_DataBackup 中，自动复制到 02_WorkSpace
- 通过 updatedInput 修改工具参数，将路径从 01_DataBackup 重定向到 02_WorkSpace
- Claude 无需介入，工具自动在副本上执行

退出码：0=放行（含 updatedInput 修改）, 2=阻止（备份失败时）, 1=内部错误
"""

import json
import sys
import os
import io
import subprocess

# 强制 UTF-8
sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8', errors='replace')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 添加共享模块路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
from find_arcpy import run_arcpy_script

# 已知破坏性工具列表（原地修改输入数据，无输出路径参数）
DESTRUCTIVE_TOOLS = {
    "arcpy.management.CalculateField",
    "arcpy.management.AddField",
    "arcpy.management.DeleteField",
    "arcpy.management.AlterField",
    "arcpy.management.DeleteFeatures",
    "arcpy.management.DeleteRows",
    "arcpy.management.AssignDomainsToField",
    "arcpy.management.AssignDefaultToField",
    "arcpy.management.CalculateStatistics",
    "arcpy.management.Compact",
    "arcpy.management.BuildStatistics",
    "arcpy.management.Analyze",
    "arcpy.management.TruncateTable",
}

# 模块级通配符工具（前缀匹配）
DESTRUCTIVE_PREFIXES = [
    "arcpy.edit.",
    "arcpy.management.Update",
    "arcpy.management.Repair",
    "arcpy.management.Rebuild",
]

# 安全工具的输出参数关键字（有输出路径 = 安全，创建新数据）
# 覆盖 out_* 和 output_* 两种前缀的常见路径类输出参数
OUTPUT_PARAM_KEYWORDS = {
    # out_* 前缀
    'out_feature_class', 'out_featureclass', 'out_features', 'out_feature_dataset',
    'out_raster', 'out_raster_dataset', 'out_rasterdataset',
    'out_table', 'out_table_name', 'out_tables',
    'out_dataset', 'out_dataset_name', 'out_dataset_path',
    'out_path', 'out_workspace', 'out_workspace_location',
    'out_name', 'out_file', 'out_folder', 'out_folder_path',
    'out_location', 'out_location_file',
    'out_json_path', 'out_json_file',
    'out_geodatabase', 'out_gdb_path', 'out_fgdb', 'out_file_gdb', 'out_mobile_gdb',
    'out_tin', 'out_las_dataset', 'out_mosaic_dataset', 'out_sas_dataset',
    'out_network_analysis_layer',
    'out_netcdf_file', 'out_csv_file', 'out_excel_file', 'out_text_file',
    'out_pdf_file', 'out_image_file', 'out_tiff_file', 'out_gpx_file', 'out_kmz_file',
    'out_report', 'out_log', 'out_log_file',
    'out_slpk', 'out_service_definition',
    # output_* 前缀（ArcGIS Pro 新工具风格）
    'output_feature_class', 'output_featureclass', 'output_features', 'output_features_name',
    'output_fc', 'output_feature_dataset',
    'output_table', 'output_table_for_charts',
    'output_dataset',
    'output_path', 'output_workspace', 'output_folder', 'output_location',
    'output_file', 'output_name', 'output_geodatabase', 'output_locator',
    'output_report', 'output_layer', 'output_group_layer',
    'output_pred_raster', 'output_pred_features', 'output_predicted_features',
    'output_trained_raster', 'output_trained_features',
    'output_routes_name', 'output_stops_name', 'output_directions_name',
    'output_simulation_prefix',
}

# 非路径的 out_* 参数（值是枚举/类型/范围等，不是文件路径）
NON_PATH_OUTPUT_PARAMS = {
    'out_coor_system', 'out_spatial_reference', 'out_extent',
    'out_statistics', 'out_fields', 'out_field_name', 'out_stat_type',
    'out_type', 'out_format', 'out_units', 'out_linear_units', 'out_horizontal_unit',
    'out_alias', 'out_option', 'out_schema', 'out_geometry_type',
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


def is_destructive(tool_name: str) -> bool:
    """判断工具是否为破坏性工具"""
    if tool_name in DESTRUCTIVE_TOOLS:
        return True
    for prefix in DESTRUCTIVE_PREFIXES:
        if tool_name.startswith(prefix):
            return True
    return False


def has_output_param(parameters: dict) -> bool:
    """检查参数中是否有输出路径参数"""
    for key in parameters:
        key_lower = key.lower()
        if key_lower in OUTPUT_PARAM_KEYWORDS:
            return True
        # out_* 前缀 fallback：排除已知非路径参数后，其余 out_* 视为输出
        if key_lower.startswith('out_') and key_lower not in NON_PATH_OUTPUT_PARAMS:
            return True
        # output_* 前缀 fallback：同理
        if key_lower.startswith('output_') and key_lower not in NON_PATH_OUTPUT_PARAMS:
            return True
    return False


def find_input_data_in_readonly(parameters: dict, cwd: str) -> list[tuple[str, str]]:
    """
    查找参数中位于 01_DataBackup 中的输入数据路径。
    返回 [(param_key, path), ...]
    """
    readonly_prefix = os.path.join(cwd, "01_DataBackup").replace("\\", "/").lower()

    # 输入路径关键字
    input_keywords = {
        'in_features', 'in_raster', 'in_table', 'input_features', 'in_features_or_layer',
        'in_feature_class', 'in_network', 'in_dataset', 'in_zone_data', 'in_data',
        'in_surface', 'in_workspace', 'in_cost_raster', 'in_flow_direction_raster'
    }

    results = []
    for key, value in parameters.items():
        if not isinstance(value, str):
            continue
        key_lower = key.lower()
        # 匹配输入参数或非 out_ 开头的路径参数
        is_input = key_lower in input_keywords or (
            not key_lower.startswith('out_') and
            (os.sep in value or '/' in value or (len(value) > 2 and value[1] == ':'))
        )
        if is_input:
            value_norm = value.replace("\\", "/").lower()
            if value_norm.startswith(readonly_prefix):
                results.append((key, value))

    return results


def copy_data_to_workspace(src_path: str, cwd: str) -> str | None:
    """
    将数据从 01_DataBackup 复制到 02_WorkSpace。
    返回目标路径，失败返回 None。
    """
    # 计算目标路径
    src_norm = src_path.replace("\\", "/")
    cwd_norm = cwd.replace("\\", "/")
    relative = src_norm[len(cwd_norm):].lstrip("/")
    dest_path = os.path.join(cwd, "02_WorkSpace", relative).replace("\\", "/")

    # 确保目标目录存在
    dest_dir = os.path.dirname(dest_path)
    if not os.path.exists(dest_dir):
        os.makedirs(dest_dir, exist_ok=True)

    # 通过 ArcPy 复制（始终覆盖，确保副本与源一致）
    script = '''
import arcpy
import json
import sys
import os

params = json.loads(sys.stdin.read())
src = params["src"]
dest = params["dest"]

# 允许覆盖已存在的输出（确保副本与源数据一致）
arcpy.env.overwriteOutput = True

try:
    desc = arcpy.Describe(src)
    data_type = desc.dataType

    if data_type in ("FeatureClass", "ShapeFile", "Shapefile"):
        arcpy.management.CopyFeatures(src, dest)
    elif data_type in ("RasterDataset", "RasterBand"):
        arcpy.management.CopyRaster(src, dest)
    elif data_type == "Table":
        arcpy.conversion.TableToTable(src, os.path.dirname(dest), os.path.basename(dest))
    elif data_type in ("FileGeodatabase", "Workspace"):
        arcpy.management.Copy(src, dest)
    else:
        arcpy.management.Copy(src, dest)

    print(json.dumps({"success": True, "dest": dest}))
except Exception as e:
    print(json.dumps({"success": False, "error": str(e)}))
'''
    result = run_arcpy_script(script, {"src": src_path, "dest": dest_path}, timeout=120)
    if result["success"] and isinstance(result["result"], dict) and result["result"].get("success"):
        return dest_path
    else:
        error = result.get("error", "") or (result["result"].get("error", "") if isinstance(result.get("result"), dict) else "")
        print(f"[data-backup] 复制失败: {src_path} → {dest_path}: {error}", file=sys.stderr)
        return None


def main():
    try:
        input_data = json.loads(sys.stdin.read())
        cwd = input_data.get("cwd", "").replace("\\", "/")
        tool_input = input_data.get("tool_input", {})
        gis_tool_name = tool_input.get("tool_name", "")
        parameters = tool_input.get("parameters", {})

        if not gis_tool_name:
            sys.exit(0)

        # 判断是否为破坏性工具
        # 有输出参数的工具通常是安全的（创建新数据）
        if has_output_param(parameters):
            sys.exit(0)

        if not is_destructive(gis_tool_name):
            sys.exit(0)

        # 查找位于 01_DataBackup 中的输入数据
        readonly_inputs = find_input_data_in_readonly(parameters, cwd)

        if not readonly_inputs:
            sys.exit(0)  # 没有只读数据，无需备份

        # 需要备份：复制数据并修改参数
        new_parameters = dict(parameters)
        backup_messages = []

        for param_key, src_path in readonly_inputs:
            dest_path = copy_data_to_workspace(src_path, cwd)
            if dest_path:
                new_parameters[param_key] = dest_path
                backup_messages.append(
                    f"  ✓ {param_key}: {os.path.basename(src_path)} → 02_WorkSpace/"
                )
            else:
                # 复制失败，阻止操作
                print(
                    f"[data-backup] 无法备份只读数据 '{src_path}'。\n"
                    f"工具 '{gis_tool_name}' 会原地修改数据，但输入位于只读目录 01_DataBackup。\n"
                    f"请先手动将数据复制到 02_WorkSpace，再执行此工具。",
                    file=sys.stderr
                )
                sys.exit(2)

        # 返回 updatedInput 修改工具参数
        msg = f"[data-backup] 检测到破坏性工具操作只读数据，已自动备份:\n" + "\n".join(backup_messages)
        print(msg, file=sys.stderr)

        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "updatedInput": {
                    "tool_name": gis_tool_name,
                    "parameters": new_parameters
                },
                "additionalContext": f"⚠️ 数据备份 Hook：已自动将只读数据从 01_DataBackup 复制到 02_WorkSpace，工具将在副本上执行。"
            }
        }
        print(json.dumps(output, ensure_ascii=False))
        sys.exit(0)

    except json.JSONDecodeError as e:
        print(f"[data-backup] JSON 解析错误: {e}", file=sys.stderr)
        sys.exit(1)
    except SystemExit:
        raise
    except Exception as e:
        print(f"[data-backup] 内部错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
