# -*- coding: utf-8 -*-
"""
结果验证 Hook（PostToolUse）- 替代 result-confirm skill

功能：
- GIS 工具执行后自动验证输出数据
- 属性检验：空值率、零值率、要素数量
- 几何验证：坐标系、空间范围、几何类型
- 通过 additionalContext 将验证报告注入 Claude 上下文
- 严重问题时通过 stderr 警告 Claude

退出码：0=始终放行（PostToolUse 不阻止已执行的操作）
"""

import json
import sys
import os
import io

# 强制 UTF-8
sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8', errors='replace')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 添加共享模块路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
from find_arcpy import run_arcpy_script

# 验证阈值
CONFIG = {
    "null_warning_threshold": 0.8,    # 空值率超过 80% 警告
    "zero_warning_threshold": 0.80,   # 零值率超过 80% 警告（降至 0.80，匹配 result-confirm SKILL.md 非零率门控）
    "extent_ratio_threshold": 10.0,   # 范围扩大/缩小超过 10 倍警告
    "max_sample_records": 1000,        # 最大采样记录数
}

# 非空间输出参数（不需要验证）
NON_SPATIAL_OUTPUT_PARAMS = {
    'out_coor_system', 'out_spatial_reference', 'out_extent', 'out_statistics',
    'out_fields', 'out_field_name', 'out_stat_type', 'out_type', 'out_json_path',
    'out_format', 'out_units', 'out_linear_units', 'out_horizontal_unit',
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

# 输出路径参数（覆盖 out_* 和 output_* 两种前缀）
OUTPUT_PATH_PARAMS = {
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

# 输入路径参数
INPUT_PATH_PARAMS = {
    'in_features', 'in_raster', 'in_table', 'input_features', 'in_features_or_layer',
    'in_feature_class', 'in_zone_data', 'in_data'
}

# 坐标系转换工具（输出 CRS 可能与输入不同）
CRS_CHANGE_TOOLS = {
    'arcpy.management.Project', 'arcpy.management.ProjectRaster',
    'arcpy.management.BatchProject', 'arcpy.management.DefineProjection'
}

# 范围变化工具（输出范围可能显著不同）
EXTENT_CHANGE_TOOLS = {
    'arcpy.analysis.Buffer', 'arcpy.analysis.Clip', 'arcpy.analysis.Erase',
    'arcpy.analysis.Intersect', 'arcpy.analysis.Union', 'arcpy.analysis.SpatialJoin',
    'arcpy.management.Extent', 'arcpy.management.MinimumBoundingGeometry'
}


def extract_paths(parameters: dict) -> tuple[str, str]:
    """提取输入和输出路径"""
    input_path = ""
    output_path = ""

    for key, value in parameters.items():
        if not isinstance(value, str):
            continue
        key_lower = key.lower()
        if key_lower in INPUT_PATH_PARAMS and not input_path:
            input_path = value
        elif key_lower in OUTPUT_PATH_PARAMS and key_lower not in NON_SPATIAL_OUTPUT_PARAMS:
            if not output_path:
                output_path = value
        elif (key_lower.startswith('out_') or key_lower.startswith('output_')) and key_lower not in NON_SPATIAL_OUTPUT_PARAMS:
            if not output_path and (os.sep in value or '/' in value or (len(value) > 2 and value[1] == ':')):
                output_path = value

    return input_path, output_path


def run_validation(output_path: str, input_path: str, tool_name: str) -> dict:
    """运行 ArcPy 验证脚本"""
    script = '''
import arcpy
import json
import sys

params = json.loads(sys.stdin.read())
output_path = params["output_path"]
input_path = params.get("input_path", "")
tool_name = params["tool_name"]

warnings = []
info = {}

try:
    # 检查输出是否存在
    desc = arcpy.Describe(output_path)
    data_type = desc.dataType
    info["data_type"] = data_type
    info["name"] = desc.name

    # ===== 几何验证 =====
    if hasattr(desc, 'shapeType'):
        info["shape_type"] = desc.shapeType

    if hasattr(desc, 'spatialReference') and desc.spatialReference:
        sr = desc.spatialReference
        info["crs_name"] = sr.name
        info["crs_wkid"] = sr.factoryCode if hasattr(sr, 'factoryCode') else None
    else:
        info["crs_name"] = None
        warnings.append("⚠️ 输出数据缺少坐标系信息")

    if hasattr(desc, 'extent') and desc.extent:
        ext = desc.extent
        info["extent"] = {
            "xmin": round(ext.XMin, 6), "ymin": round(ext.YMin, 6),
            "xmax": round(ext.XMax, 6), "ymax": round(ext.YMax, 6)
        }
    else:
        info["extent"] = None

    # 要素数量
    if data_type in ('FeatureClass', 'ShapeFile', 'Shapefile'):
        try:
            count = int(arcpy.management.GetCount(output_path)[0])
            info["feature_count"] = count
            if count == 0:
                warnings.append("🔴 输出数据包含 0 个要素！")
        except Exception:
            info["feature_count"] = None

    # ===== 属性检验 =====
    if hasattr(desc, 'fields') and desc.fields:
        fields_info = []
        for f in desc.fields:
            if f.name.startswith("Shape") or f.type in ("OID", "Geometry"):
                continue
            fields_info.append({
                "name": f.name, "type": f.type,
                "length": f.length if hasattr(f, 'length') else None,
                "nullable": f.isNullable if hasattr(f, 'isNullable') else None
            })
        info["field_count"] = len(fields_info)

        # 采样检查空值和零值
        if fields_info and info.get("feature_count", 0) > 0:
            field_names = [f["name"] for f in fields_info]
            null_counts = {n: 0 for n in field_names}
            zero_counts = {n: 0 for n in field_names}
            total = 0

            with arcpy.da.SearchCursor(output_path, field_names) as cursor:
                for row in cursor:
                    total += 1
                    for i, fname in enumerate(field_names):
                        if row[i] is None:
                            null_counts[fname] += 1
                        elif isinstance(row[i], (int, float)) and row[i] == 0:
                            zero_counts[fname] += 1
                    if total >= params.get("max_sample", 1000):
                        break

            if total > 0:
                for fname in field_names:
                    null_rate = null_counts[fname] / total
                    zero_rate = zero_counts[fname] / total
                    if null_rate > params.get("null_threshold", 0.8):
                        warnings.append(f"⚠️ 字段 '{fname}' 空值率 {null_rate*100:.1f}%（共 {total} 条记录）")
                    if zero_rate > params.get("zero_threshold", 0.80) and fname not in ("FID", "OBJECTID"):
                        warnings.append(f"⚠️ 字段 '{fname}' 零值率 {zero_rate*100:.1f}%")

    # ===== 与输入对比 =====
    if input_path:
        try:
            input_desc = arcpy.Describe(input_path)

            # 坐标系对比
            if hasattr(input_desc, 'spatialReference') and input_desc.spatialReference:
                input_sr = input_desc.spatialReference
                input_wkid = input_sr.factoryCode if hasattr(input_sr, 'factoryCode') else None
                output_wkid = info.get("crs_wkid")
                if input_wkid and output_wkid and input_wkid != output_wkid:
                    if tool_name not in params.get("crs_change_tools", set()):
                        warnings.append(
                            f"⚠️ 坐标系变化: 输入 WKID={input_wkid} → 输出 WKID={output_wkid}"
                        )

            # 范围对比
            if info.get("extent") and hasattr(input_desc, 'extent') and input_desc.extent:
                inp_ext = input_desc.extent
                out_ext = info["extent"]
                in_area = max(1, (inp_ext.XMax - inp_ext.XMin) * (inp_ext.YMax - inp_ext.YMin))
                out_area = max(1, (out_ext["xmax"] - out_ext["xmin"]) * (out_ext["ymax"] - out_ext["ymin"]))
                ratio = max(in_area, out_area) / max(1, min(in_area, out_area))
                if ratio > params.get("extent_threshold", 10.0):
                    if tool_name not in params.get("extent_change_tools", set()):
                        warnings.append(f"⚠️ 空间范围变化异常（{ratio:.1f}倍），请检查结果是否正确")

            # 要素数量对比
            if info.get("feature_count") is not None:
                try:
                    input_count = int(arcpy.management.GetCount(input_path)[0])
                    if input_count > 0 and info["feature_count"] == 0:
                        warnings.append(f"🔴 输入有 {input_count} 个要素，输出为 0 个！")
                except Exception:
                    pass
        except Exception:
            pass  # 输入数据检查失败不影响整体验证

    # 栅格验证
    if data_type in ('RasterDataset', 'RasterBand'):
        try:
            raster = arcpy.Raster(output_path)
            info["raster_size"] = f"{raster.width}x{raster.height}"
            info["band_count"] = raster.bandCount
            info["cell_size"] = f"{raster.meanCellWidth}x{raster.meanCellHeight}"
        except Exception:
            pass

except Exception as e:
    warnings.append(f"🔴 验证过程出错: {str(e)}")

result = {"info": info, "warnings": warnings}
print(json.dumps(result, ensure_ascii=False))
'''
    input_data = {
        "output_path": output_path,
        "input_path": input_path,
        "tool_name": tool_name,
        "null_threshold": CONFIG["null_warning_threshold"],
        "zero_threshold": CONFIG["zero_warning_threshold"],
        "extent_threshold": CONFIG["extent_ratio_threshold"],
        "max_sample": CONFIG["max_sample_records"],
        "crs_change_tools": list(CRS_CHANGE_TOOLS),
        "extent_change_tools": list(EXTENT_CHANGE_TOOLS)
    }

    return run_arcpy_script(script, input_data, timeout=120)


def format_validation_report(validation_result: dict, tool_name: str, output_path: str) -> str:
    """格式化验证报告为 Markdown"""
    if not validation_result["success"]:
        return f"[result-validate] ArcPy 验证失败: {validation_result['error']}"

    result = validation_result["result"]
    if not isinstance(result, dict):
        return f"[result-validate] 验证结果格式异常"

    info = result.get("info", {})
    warnings = result.get("warnings", [])

    lines = [f"### 结果验证报告 [{tool_name.split('.')[-1]}]"]
    lines.append(f"- 输出: `{os.path.basename(output_path)}`")
    lines.append(f"- 类型: {info.get('data_type', '未知')}")

    if info.get("shape_type"):
        lines.append(f"- 几何: {info['shape_type']}")
    if info.get("crs_name"):
        lines.append(f"- 坐标系: {info['crs_name']} (WKID:{info.get('crs_wkid', '?')})")
    if info.get("feature_count") is not None:
        lines.append(f"- 要素数: {info['feature_count']}")
    if info.get("field_count") is not None:
        lines.append(f"- 字段数: {info['field_count']}")
    if info.get("extent"):
        ext = info["extent"]
        lines.append(f"- 范围: X[{ext['xmin']}, {ext['xmax']}] Y[{ext['ymin']}, {ext['ymax']}]")
    if info.get("raster_size"):
        lines.append(f"- 栅格: {info['raster_size']}, {info.get('band_count', '?')}波段")

    if warnings:
        lines.append("")
        for w in warnings:
            lines.append(w)
    else:
        lines.append("\n✅ 所有检查通过")

    return "\n".join(lines)


def main():
    try:
        input_data = json.loads(sys.stdin.read())
        tool_input = input_data.get("tool_input", {})
        gis_tool_name = tool_input.get("tool_name", "")
        parameters = tool_input.get("parameters", {})

        if not gis_tool_name:
            sys.exit(0)

        # 提取输出路径
        input_path, output_path = extract_paths(parameters)

        if not output_path:
            sys.exit(0)  # 无输出路径，跳过验证

        # 检查输出文件是否实际存在
        if not os.path.exists(output_path):
            # 可能是 GDB 内要素类，尝试 ArcPy 验证
            pass

        # 运行验证
        result = run_validation(output_path, input_path, gis_tool_name)

        # 格式化报告
        report = format_validation_report(result, gis_tool_name, output_path)

        # 严重警告时输出到 stderr
        if result["success"] and isinstance(result["result"], dict):
            warnings = result["result"].get("warnings", [])
            critical = [w for w in warnings if "🔴" in w]
            if critical:
                print("\n".join(critical), file=sys.stderr)

        # 通过 additionalContext 注入验证报告
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": report
            }
        }
        print(json.dumps(output, ensure_ascii=False))
        sys.exit(0)

    except json.JSONDecodeError as e:
        print(f"[result-validate] JSON 解析错误: {e}", file=sys.stderr)
        sys.exit(1)
    except SystemExit:
        raise
    except Exception as e:
        print(f"[result-validate] 内部错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
