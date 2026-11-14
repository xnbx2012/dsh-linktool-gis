# -*- coding: utf-8 -*-
"""
GIS 工具执行日志记录 Hook - 增强版（PostToolUse）

功能：
- 为每次 execute_gis_tool 调用生成唯一执行 ID
- 记录工具名称、输入/输出路径、参数摘要、时间戳
- 记录执行状态（success/fail/unknown）及失败原因摘要
- 通过 additionalContext 注入一行压缩摘要（含 ✅/❌ 状态标记）到 Claude 上下文
- 维护 .workflow_state.jsonl（断点续跑）和 .workflow_progress.json（历史摘要）

退出码：0=始终放行
"""

import json
import sys
import os
import io
import uuid
from datetime import datetime

# 强制 UTF-8
sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8', errors='replace')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 输入路径关键字
INPUT_PATH_KEYWORDS = {
    'in_features', 'in_raster', 'in_table', 'input_features', 'in_features_or_layer',
    'in_feature_class', 'in_network', 'in_dataset', 'in_workspace', 'in_surface',
    'in_zone_data', 'in_flow_direction_raster', 'in_cost_raster', 'in_data'
}

# 输出路径关键字（覆盖 out_* 和 output_* 两种前缀）
OUTPUT_PATH_KEYWORDS = {
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

NON_PATH_OUTPUT_PARAMS = {
    'out_coor_system', 'out_spatial_reference', 'out_extent', 'out_statistics',
    'out_fields', 'out_field_name', 'out_stat_type', 'out_type',
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


def extract_paths(parameters: dict) -> tuple[list[str], list[str]]:
    """从参数中提取输入和输出路径"""
    input_paths, output_paths = [], []
    for key, value in parameters.items():
        if not isinstance(value, str):
            continue
        key_lower = key.lower()
        if key_lower in INPUT_PATH_KEYWORDS:
            input_paths.append(value)
        elif key_lower in OUTPUT_PATH_KEYWORDS and key_lower not in NON_PATH_OUTPUT_PARAMS:
            output_paths.append(value)
        elif (key_lower.startswith('out_') or key_lower.startswith('output_')) \
                and key_lower not in NON_PATH_OUTPUT_PARAMS:
            if os.sep in value or '/' in value or (len(value) > 2 and value[1] == ':'):
                output_paths.append(value)
    return input_paths, output_paths


def extract_parameters_summary(parameters: dict, input_paths: list, output_paths: list) -> dict:
    """提取参数摘要（排除路径类参数，保留业务参数）"""
    all_paths = set(input_paths + output_paths)
    return {
        k: v for k, v in parameters.items()
        if isinstance(v, str) and v not in all_paths
        and k.lower() not in NON_PATH_OUTPUT_PARAMS
    }


def determine_status(tool_response: dict) -> tuple[str, str]:
    """
    从工具响应中判断执行成功/失败。
    返回 (status: str, reason: str)。
    status: 'success' | 'fail' | 'unknown'
    """
    if not isinstance(tool_response, dict):
        return "unknown", ""

    # MCP 工具错误格式：{ "error": { "code": ..., "message": "..." } }
    if "error" in tool_response:
        err = tool_response["error"]
        msg = err.get("message", "") if isinstance(err, dict) else str(err)
        return "fail", msg[:200]

    # Claude Code MCP 错误格式：{ "content": [...], "isError": true }
    content = tool_response.get("content", [])
    is_error = tool_response.get("isError", False)
    if is_error and content:
        msg = "".join(c.get("text", "") for c in content if isinstance(c, dict))
        return "fail", msg[:200]

    # 兜底：检查 content 中是否有错误标记
    if content:
        text = "".join(c.get("text", "") for c in content if isinstance(c, dict))
        if "error" in text.lower() or "failed" in text.lower():
            return "fail", text[:200]

    return "success", ""


def build_compressed_summary(
    execution_id: str, tool_name: str,
    input_paths: list, output_paths: list,
    status: str = "unknown"
) -> str:
    """构建一行压缩摘要，用于 additionalContext（包含 ✅/❌ 状态标记）"""
    short_name = tool_name.split('.')[-1] if '.' in tool_name else tool_name
    short_inputs = [os.path.basename(p) for p in input_paths[:2]]
    short_outputs = [os.path.basename(p) for p in output_paths[:2]]
    id_short = execution_id[:8]

    parts = [f"[GIS-LOG] #{id_short} {short_name}"]
    if short_inputs:
        parts.append(f"输入: {', '.join(short_inputs)}")
    if short_outputs:
        parts.append(f"→ {', '.join(short_outputs)}")
    if status == "fail":
        parts.append("❌ FAIL")
    elif status == "success":
        parts.append("✅")

    return " | ".join(parts)


def main():
    try:
        input_data = json.loads(sys.stdin.read())
        cwd = input_data.get("cwd", "").replace("\\", "/")
        tool_input = input_data.get("tool_input", {})

        gis_tool_name = tool_input.get("tool_name", "")
        parameters = tool_input.get("parameters", {})

        if not gis_tool_name:
            sys.exit(0)

        tool_response = tool_input.get("tool_response", {})
        exec_status, fail_reason = determine_status(tool_response)

        execution_id = str(uuid.uuid4())
        input_paths, output_paths = extract_paths(parameters)
        params_summary = extract_parameters_summary(parameters, input_paths, output_paths)

        log_entry = {
            "execution_id": execution_id,
            "timestamp": datetime.now().isoformat(),
            "tool_name": gis_tool_name,
            "parameters": parameters,
            "input_paths": input_paths,
            "output_paths": output_paths,
            "parameters_summary": params_summary,
            "status": exec_status,       # 'success' | 'fail' | 'unknown'
            "fail_reason": fail_reason,   # 失败时原因摘要
        }

        # 写入 gis-tool-logs.json
        log_path = os.path.join(cwd, "02_WorkSpace", "gis-tool-logs.json")
        log_dir = os.path.dirname(log_path)
        if not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        if not os.path.exists(log_path):
            with open(log_path, 'w', encoding='utf-8') as f:
                json.dump([], f, ensure_ascii=False, indent=4)
        with open(log_path, 'r+', encoding='utf-8') as f:
            try:
                logs = json.load(f)
            except json.JSONDecodeError:
                logs = []
            logs.append(log_entry)
            f.seek(0)
            f.truncate()
            json.dump(logs, f, ensure_ascii=False, indent=4)

        print(f"[enhanced-record] 日志记录成功: {execution_id} [{exec_status}]", file=sys.stderr)

        # ─── 断点续跑状态 ───
        # 追加到 .workflow_state.jsonl，供 @task-plan resume 时跳过已完成步骤
        try:
            state_path = os.path.join(cwd, "02_WorkSpace", ".workflow_state.jsonl")
            state_entry = {
                "execution_id": execution_id,
                "timestamp": datetime.now().isoformat(),
                "tool_name": gis_tool_name,
                "input_paths": input_paths,
                "output_paths": output_paths,
                "status": exec_status,
                "fail_reason": fail_reason,
            }
            with open(state_path, 'a', encoding='utf-8') as sf:
                sf.write(json.dumps(state_entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

        # ─── 进度快照 ───
        # 维护 .workflow_progress.json，供启动新 Workflow 前判断哪些步骤已实际执行
        try:
            progress_path = os.path.join(cwd, "02_WorkSpace", ".workflow_progress.json")
            if os.path.exists(progress_path):
                with open(progress_path, 'r', encoding='utf-8') as pf:
                    progress = json.load(pf)
            else:
                progress = {"total_calls": 0, "completed_steps": {}}

            progress["total_calls"] = progress.get("total_calls", 0) + 1
            progress["last_execution"] = {
                "execution_id": execution_id,
                "timestamp": datetime.now().isoformat(),
                "tool_name": gis_tool_name,
                "input_paths": input_paths,
                "output_paths": output_paths,
                "status": exec_status,
            }
            for op in output_paths:
                step_key = os.path.basename(op).split('.')[0]
                progress["completed_steps"][step_key] = {
                    "tool_name": gis_tool_name,
                    "execution_id": execution_id,
                    "timestamp": datetime.now().isoformat(),
                    "status": exec_status,
                }

            with open(progress_path, 'w', encoding='utf-8') as pf:
                json.dump(progress, pf, ensure_ascii=False, indent=2)
        except Exception:
            pass

        # 输出压缩摘要（含 ✅/❌ 状态）作为 additionalContext
        summary = build_compressed_summary(
            execution_id, gis_tool_name, input_paths, output_paths, exec_status
        )
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": summary
            }
        }
        print(json.dumps(output, ensure_ascii=False))
        sys.exit(0)

    except json.JSONDecodeError as e:
        print(f"[enhanced-record] JSON 解析错误: {e}", file=sys.stderr)
        sys.exit(1)
    except SystemExit:
        raise
    except Exception as e:
        print(f"[enhanced-record] 内部错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
