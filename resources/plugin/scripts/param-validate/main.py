# -*- coding: utf-8 -*-
"""
GIS 工具参数形式校验 Hook（PreToolUse）— 基于 schema.json + schema-engine 增强版

功能：
- arcpy.* 工具：对照本地 schema.json 校验必填参数、参数类型、输入路径存在性
- 五引擎工具（inner_/wbt_/gdal_/qgis_ 前缀或裸名）：对照 arcgis-mcp-server
  运行时生成的 schema.json（engines 段）校验必填参数与非空；未知参数仅警告
- 跳过 Output 方向参数的校验
- 不在工具库中的工具仅警告不阻止

退出码：0=放行, 2=阻止（参数缺失或类型错误）, 1=内部错误
"""

import json
import re
import sys
import os
import io

# 强制 UTF-8
sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8', errors='replace')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ─── 数据源路径 ───────────────────────────────────────────────
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), 'schema.json')
# 五引擎 schema：由 arcgis-mcp-server 启动时生成/刷新（单一事实源，避免双份漂移）
ENGINE_SCHEMA_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'arcgis-mcp-server', 'schema.json'))

# ─── 缓存 ────────────────────────────────────────────────────
_tool_schema_cache = None
_engine_schema_cache: dict | None = None

# ─── 工具名映射：旧名 → schema key ───────────────────────────
# schema.json key 格式: "toolbox.ToolName"（如 3d.AddFeatureClassToTerrain）
# Claude 传入格式: "arcpy.toolbox.ToolName"（如 arcpy.ddd.AddFeatureClassToTerrain）
_TOOLBOX_ALIAS = {
    'ddd': '3d',    # 3D Analyst 工具箱
    'wmx': 'wmx',  # Workflow Manager（schema 中无此前缀，保留原样）
}


def _load_schema() -> dict:
    """
    加载 schema.json 并构建预计算查找表。
    返回 {arcpy_func_name: tool_info}，其中 tool_info = {
        "required": [str],          # 必填参数名列表
        "params": {                 # 所有参数的详细信息
            param_name: {
                "index": int,       # 参数顺序
                "direction": str,   # "Input" | "Output"
                "datatype": str,    # arcpy 数据类型
                "multiValue": bool  # 是否多值
            }
        }
    }
    """
    global _tool_schema_cache
    if _tool_schema_cache is not None:
        return _tool_schema_cache

    try:
        with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
            schema = json.load(f)
    except Exception as e:
        print(f"[param-validate] 加载 schema.json 失败: {e}", file=sys.stderr)
        _tool_schema_cache = {}
        return {}

    lookup = {}
    for schema_key, tool_def in schema.get('properties', {}).items():
        # schema_key: "3d.AddFeatureClassToTerrain"
        # 转换为 arcpy 格式: "arcpy.3d.AddFeatureClassToTerrain"
        parts = schema_key.split('.', 1)
        if len(parts) != 2:
            continue
        toolbox, tool_name = parts
        # 反向映射：schema 中的 "3d" 在 ArcPy 中可能是 "ddd"，但 ArcPy 3.x 也支持 "arcpy.3d"
        # 为兼容两种调用方式，同时注册两个 key
        arcpy_key = f"arcpy.{schema_key}"

        required = tool_def.get('required', [])
        params = {}
        for pname, pdef in tool_def.get('properties', {}).items():
            params[pname] = {
                'index': pdef.get('meta:index', -1),
                'direction': pdef.get('meta:direction', 'Input'),
                'datatype': pdef.get('meta:arcpy_datatype', ''),
                'multiValue': pdef.get('meta:multiValue', False),
            }

        tool_info = {'required': required, 'params': params}
        lookup[arcpy_key] = tool_info

        # 注册别名：arcpy.ddd.X ↔ arcpy.3d.X
        for alias_from, alias_to in _TOOLBOX_ALIAS.items():
            if toolbox == alias_to and alias_from != alias_to:
                alias_key = f"arcpy.{alias_from}.{tool_name}"
                lookup[alias_key] = tool_info
            elif toolbox == alias_from:
                alias_key = f"arcpy.{alias_to}.{tool_name}"
                lookup[alias_key] = tool_info

    _tool_schema_cache = lookup
    return lookup


# ─── 路径类型集合 ─────────────────────────────────────────────
# 从 schema.json 的 354 种 datatype 中提取出与文件/目录路径相关的类型
_PATH_DATATYPES = frozenset({
    'Feature Class', 'Feature Dataset', 'Raster Dataset', 'Raster Layer',
    'Raster Catalog', 'Table', 'Table View', 'Workspace', 'Folder', 'File',
    'Shapefile', 'TIN', 'LAS Dataset', 'LAS Dataset Layer', 'Layer', 'Layer File',
    'Feature Layer', 'Mosaic Dataset', 'Mosaic Layer', 'Terrain', 'Terrain Layer',
    'Network Dataset', 'Network Dataset Layer', 'Geometric Network',
    'Topology', 'Topology Layer', 'Parcel Fabric', 'Parcel Fabric Layer for ArcMap',
    'Parcel Layer', 'Trace Network', 'Trace Network Layer',
    'Utility Network', 'Utility Network Layer', 'Relationship Class',
    'Text File', 'dBASE Table', 'CAD Drawing Dataset', 'BIM File Workspace',
    'Geodataset', 'Dataset', 'Image Service', 'Map Server',
    'Address Locator', 'Toolbox', 'Scene Layer', 'Building Layer',
    'Building Scene Layer', 'Catalog Layer', 'Geostatistical Layer',
    'Geostatistical Value Table', 'Group Layer', 'Annotation Layer',
    'Dimension Layer', 'Graphics Layer', 'Diagram Layer',
    'Oriented Imagery Layer', 'Trajectory Layer', 'Voxel Layer',
    'Network Analyst Layer', 'Network Data Source',
    'Parcel Fabric for ArcMap', 'WCS Coverage', 'WMS Map',
    'Composite Geodataset', 'Coverage', 'Coverage Feature Class',
    'Coordinate System', 'Spatial Reference', 'Envelope', 'Extent',
})


def _is_path_type(datatype: str) -> bool:
    """判断 datatype 是否为路径类型（支持复合类型列表）"""
    if datatype in _PATH_DATATYPES:
        return True
    # 复合类型如 "['Feature Class', 'Feature Layer']"
    if datatype.startswith('['):
        try:
            types = eval(datatype)
            return any(t in _PATH_DATATYPES for t in types)
        except Exception:
            return False
    return False


def _is_numeric_type(datatype: str) -> bool:
    """判断是否为数值类型"""
    return datatype in ('Double', 'Long', 'Short')


def _is_boolean_type(datatype: str) -> bool:
    """判断是否为布尔类型"""
    return datatype == 'Boolean'


def _format_datatype(datatype: str) -> str:
    """格式化数据类型用于错误信息显示"""
    if not datatype:
        return '未知'
    # 复合类型简化显示
    if datatype.startswith('['):
        try:
            types = eval(datatype)
            return ' 或 '.join(types)
        except Exception:
            return datatype
    return datatype


# ─── 路径存在性检查 ───────────────────────────────────────────
def _check_path_exists(path_value: str, cwd: str = "") -> bool:
    """检查路径是否存在（支持 GDB 内要素类路径，只检查 GDB 文件本身）"""
    if not path_value or not isinstance(path_value, str):
        return True

    def _resolve(p: str) -> str:
        """将相对路径基于 cwd 解析为绝对路径"""
        if not os.path.isabs(p) and cwd:
            return os.path.join(cwd, p)
        return p

    # GDB 内路径：只检查 GDB 是否存在
    if '.gdb' in path_value:
        gdb_end = path_value.index('.gdb') + 4
        gdb_path = _resolve(path_value[:gdb_end])
        return os.path.exists(gdb_path)

    # SDE / 数据库连接路径跳过
    if path_value.startswith(('DB_connections', 'Database Connections')):
        return True

    return os.path.exists(_resolve(path_value))


# ─── 参数值类型校验 ───────────────────────────────────────────
def _validate_value_type(param_name: str, value, datatype: str, cwd: str = "") -> str | None:
    """
    校验参数值是否匹配期望的数据类型。
    返回错误信息字符串，校验通过返回 None。
    """
    if value is None:
        return None  # 空值由必填参数检查处理

    # 路径类型：检查存在性
    if _is_path_type(datatype):
        if isinstance(value, str) and value.strip():
            # 排除输出路径（out_ 开头通常不需要检查存在性）
            if not param_name.lower().startswith(('out_', 'output_')):
                if not _check_path_exists(value, cwd):
                    return f"输入路径不存在: {value}"
        return None

    # 数值类型
    if _is_numeric_type(datatype):
        if isinstance(value, bool):
            # bool 是 int 的子类，但不应传给数值参数
            return f"传入 bool, 期望 {_format_datatype(datatype)}"
        if not isinstance(value, (int, float)):
            return f"传入 {type(value).__name__}, 期望 {_format_datatype(datatype)}"
        return None

    # 布尔类型
    if _is_boolean_type(datatype):
        if not isinstance(value, bool):
            return f"传入 {type(value).__name__}, 期望 Boolean"
        return None

    # 其他类型（String, Field, Linear Unit, Value Table 等）：仅检查非空
    # ArcGIS 参数大多是字符串形式，不做严格类型检查
    return None


# ─── 五引擎 schema 加载与解析（镜像 arcgis-mcp-server/main.py 的命名规则）──────
def _load_engine_schema() -> dict:
    """加载 arcgis-mcp-server 生成的 schema.json 的 engines 段。

    返回 {engine: {tool_key: tool_def}}；文件缺失/无效返回 {}（引擎校验跳过）。
    """
    global _engine_schema_cache
    if _engine_schema_cache is not None:
        return _engine_schema_cache
    _engine_schema_cache = {}
    try:
        with open(ENGINE_SCHEMA_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        engines = data.get('engines', {})
        if isinstance(engines, dict):
            _engine_schema_cache = {k: v for k, v in engines.items() if isinstance(v, dict)}
    except FileNotFoundError:
        print(f"[param-validate] 引擎 schema 未生成（{ENGINE_SCHEMA_PATH}），引擎段跳过校验。", file=sys.stderr)
    except Exception as e:
        print(f"[param-validate] 加载引擎 schema 失败: {e}", file=sys.stderr)
    return _engine_schema_cache


def _camel_to_snake(name: str) -> str:
    s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s2 = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s1)
    return s2.lower()


def _normalize(raw: str) -> str:
    return raw.strip().lower().replace('-', '_').replace(' ', '_')


def _resolve_engine_tool(gis_tool_name: str) -> tuple[str | None, str, dict | None]:
    """把任意形态的 tool_name 解析为 (engine, canon, tool_def)。

    命名规则与 main.py._resolve_engine 一致：
      inner_x / wbt_x / gdal_x(→gdal:x) / qgis_provider:algo / arcpy.… 前缀强制引擎；
      裸名按 inner → whitebox → gdal(:) → qgis(:) 降级查找。
    arcpy 工具返回 ('arcpy', 原名, None)（走本地 schema.json 分支）。
    未命中任何引擎返回 (None, 原名, None)（仅警告不阻止）。
    """
    engines = _load_engine_schema()
    if not engines:
        return (None, gis_tool_name, None)
    inner = engines.get('inner', {})
    wbt = engines.get('whitebox', {})
    gdal = engines.get('gdal', {})
    qgis = engines.get('qgis', {})
    n = _normalize(gis_tool_name)

    if gis_tool_name.strip().startswith('arcpy.') or n.startswith('arcpy_'):
        return ('arcpy', gis_tool_name.strip(), None)
    if n.startswith('inner_'):
        key = _normalize(gis_tool_name[len('inner_'):])
        return ('inner', key, inner.get(key))
    if n.startswith('wbt_'):
        rest = gis_tool_name[len('wbt_'):]
        key = _normalize(rest)
        if key not in wbt:
            key = _camel_to_snake(rest)
        return ('whitebox', key, wbt.get(key))
    if n.startswith('gdal_'):
        algo = gis_tool_name[len('gdal_'):].strip().lower()
        if not algo.startswith('gdal:'):
            algo = 'gdal:' + algo
        return ('gdal', algo, gdal.get(algo))
    if n.startswith('qgis_'):
        algo = gis_tool_name[len('qgis_'):].strip().lower()
        return ('qgis', algo, qgis.get(algo))

    # 裸名降级
    if n in inner:
        return ('inner', n, inner[n])
    key = n if n in wbt else _camel_to_snake(gis_tool_name.strip())
    if key in wbt:
        return ('whitebox', key, wbt[key])
    if n.startswith('gdal:') and n in gdal:
        return ('gdal', n, gdal[n])
    if ':' in n and n in qgis:
        return ('qgis', n, qgis[n])
    return (None, gis_tool_name, None)


# 数值型 parameter_type（whitebox/gdal/inner 的 Double/Integer 等）
_NUMERIC_PARAM_TYPES = {'double', 'float', 'number', 'integer', 'long', 'short'}


def _validate_engine_params(engine: str, tool_key: str, tool_def: dict | None,
                            parameters: dict) -> tuple[list, list]:
    """非 arcpy 引擎的参数校验：必填齐全 + 非空 + 轻量数值类型检查。

    返回 (errors, warnings)。tool_def 为 None（未收录/降级元数据目录）时仅提示不阻止。
    """
    errors: list[str] = []
    warnings: list[str] = []
    if tool_def is None:
        warnings.append(f"工具 '{tool_key}' 未收录在 {engine} schema 中，跳过必填校验")
        return errors, warnings

    required = tool_def.get('required', []) or []
    params = tool_def.get('params', {}) or {}
    qgis_meta = engine == 'qgis' and not params

    for req in required:
        if req not in parameters:
            pinfo = params.get(req) or {}
            hint = pinfo.get('description') or pinfo.get('name') or ''
            errors.append(f"缺少必填参数: {req}" + (f"（{hint}）" if hint else ''))
        elif parameters[req] is None or (isinstance(parameters[req], str) and parameters[req].strip() == ''):
            errors.append(f"必填参数 '{req}' 为空")

    for name, value in parameters.items():
        if name not in params:
            warnings.append(f"未知参数（可能有效）: {name}")
            continue
        pinfo = params[name] or {}
        ptype = str(pinfo.get('parameter_type') or (pinfo.get('type') or {}).get('id') or '').lower()
        if value is None:
            continue
        if ptype in _NUMERIC_PARAM_TYPES and isinstance(value, str):
            try:
                float(value)
            except ValueError:
                errors.append(f"参数 '{name}' 传入非数值字符串 '{value}'（期望 {ptype}）")
        elif ptype in _NUMERIC_PARAM_TYPES and not isinstance(value, (int, float)):
            errors.append(f"参数 '{name}' 传入 {type(value).__name__}（期望 {ptype}）")

    if qgis_meta:
        warnings.append("QGIS schema 为降级元数据目录（无参数定义），仅做引擎归属提示")
    return errors, warnings


# ─── 主函数 ───────────────────────────────────────────────────
def main():
    try:
        input_data = json.loads(sys.stdin.read())
        cwd = input_data.get("cwd", "").replace("\\", "/")
        tool_input = input_data.get("tool_input", {})
        gis_tool_name = tool_input.get("tool_name", "")
        parameters = tool_input.get("parameters", {})

        if not gis_tool_name:
            sys.exit(0)

        # ─── 五引擎工具（inner_/wbt_/gdal_/qgis_/裸名）───
        engine, tool_key, tool_def = _resolve_engine_tool(gis_tool_name)
        if engine is not None and engine != 'arcpy':
            errors, warnings = _validate_engine_params(engine, tool_key, tool_def, parameters)
            if errors:
                error_msg = f"参数校验失败 [{gis_tool_name}（{engine} 引擎）]:\n" + "\n".join(f"  [X] {e}" for e in errors)
                if warnings:
                    error_msg += "\n警告:\n" + "\n".join(f"  [!] {w}" for w in warnings)
                print(error_msg, file=sys.stderr)
                sys.exit(2)
            if warnings:
                print(f"[param-validate] 警告 [{gis_tool_name}]:\n" + "\n".join(f"  [!] {w}" for w in warnings), file=sys.stderr)
            sys.exit(0)
        if engine is None:
            # 前缀形态但引擎 schema 未收录（如 qgis_x 未生成目录）→ 仅警告
            for prefix in ('inner_', 'wbt_', 'gdal_', 'qgis_'):
                if gis_tool_name.strip().lower().replace('-', '_').startswith(prefix):
                    print(f"[param-validate] 工具 '{gis_tool_name}' 未收录在引擎 schema 中，跳过校验。", file=sys.stderr)
                    sys.exit(0)
            # 裸名且未命中任何引擎 → 可能是 arcpy 短名（如 analysis.Buffer），交给 arcpy 分支尝试

        # ─── arcpy 工具 ───
        # 加载 schema
        tool_schema = _load_schema()

        # 查找匹配的工具
        if gis_tool_name not in tool_schema:
            print(f"[param-validate] 工具 '{gis_tool_name}' 不在 schema 中，跳过校验。", file=sys.stderr)
            sys.exit(0)

        tool_info = tool_schema[gis_tool_name]
        required_params = tool_info['required']
        all_params = tool_info['params']

        # 收集 Input 方向的参数名（用于未知参数检查）
        input_param_names = {
            name for name, info in all_params.items()
            if info['direction'] == 'Input'
        }

        errors = []
        warnings = []

        # ─── 1. 必填参数检查 ─────────────────────────────────
        for param in required_params:
            if param not in parameters:
                # 获取参数类型信息用于错误提示
                pinfo = all_params.get(param, {})
                dtype_str = _format_datatype(pinfo.get('datatype', ''))
                hint = f" (期望类型: {dtype_str})" if dtype_str != '未知' else ''
                errors.append(f"缺少必填参数: {param}{hint}")
            elif parameters[param] is None or (isinstance(parameters[param], str) and parameters[param].strip() == ""):
                pinfo = all_params.get(param, {})
                dtype_str = _format_datatype(pinfo.get('datatype', ''))
                hint = f" (期望类型: {dtype_str})" if dtype_str != '未知' else ''
                errors.append(f"必填参数 '{param}' 为空{hint}")

        # ─── 2. 参数类型校验 ─────────────────────────────────
        for param_name, param_value in parameters.items():
            pinfo = all_params.get(param_name)
            if pinfo is None:
                continue  # 未知参数在第 3 步处理

            # 跳过 Output 方向参数的类型校验（输出路径通常由用户指定，不需要检查存在性）
            # 但如果 Output 参数同时是必填参数（如 out_feature_class），不发出"无需传入"警告
            if pinfo['direction'] == 'Output':
                if param_name not in required_params:
                    warnings.append(f"参数 '{param_name}' 为 Output 方向，通常无需传入")
                continue

            datatype = pinfo.get('datatype', '')
            type_error = _validate_value_type(param_name, param_value, datatype, cwd)
            if type_error:
                dtype_str = _format_datatype(datatype)
                errors.append(f"参数 '{param_name}' {type_error} (期望类型: {dtype_str})")

        # ─── 3. 未知参数检查 ─────────────────────────────────
        for param_name in parameters:
            if param_name not in all_params:
                warnings.append(f"未知参数（可能有效）: {param_name}")

        # ─── 输出结果 ────────────────────────────────────────
        if errors:
            error_msg = f"参数校验失败 [{gis_tool_name}]:\n" + "\n".join(f"  [X] {e}" for e in errors)
            if warnings:
                error_msg += "\n警告:\n" + "\n".join(f"  [!] {w}" for w in warnings)
            print(error_msg, file=sys.stderr)
            sys.exit(2)

        if warnings:
            print(f"[param-validate] 警告 [{gis_tool_name}]:\n" + "\n".join(f"  [!] {w}" for w in warnings), file=sys.stderr)

        sys.exit(0)

    except json.JSONDecodeError as e:
        print(f"[param-validate] JSON 解析错误: {e}", file=sys.stderr)
        sys.exit(1)
    except SystemExit:
        raise
    except Exception as e:
        print(f"[param-validate] 内部错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
