"""
ArcGIS MCP Server

A FastMCP-based server for ArcGIS operations via ArcPy.
Since the current environment doesn't have arcpy, all GIS operations
are executed through subprocess calls to ArcGIS Pro's Python interpreter.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from arcpy_worker import ArcPyWorker
_arcpy_workers: dict[str, ArcPyWorker] = {}

from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("arcgis-mcp-server")

DEFAULT_ARCPY_TIMEOUT_SECONDS = 300
EXECUTE_GIS_TOOL_TIMEOUT_SECONDS = 900


def format_timeout_message(timeout_seconds: int) -> str:
    """Return a human-readable timeout duration for error messages."""
    minutes = timeout_seconds / 60
    if minutes.is_integer():
        return f"{int(minutes)} minutes ({timeout_seconds} seconds)"
    return f"{timeout_seconds} seconds"


def find_py_interpreter() -> str | None:
    """
    Find the path to the ArcGIS Pro Python interpreter.

    Checks in the following order:
    1. Environment variable ARCGIS_PRO_PATH
    2. Default installation paths (C: and D: drives)
    3. User-specific AppData installation paths
    4. ArcGIS Pro shortcut resolution (ProgramData and user Start Menu)
    5. Registry lookup (Windows)

    Returns:
        The path to the Python interpreter, or None if not found.
    """
    # Check environment variable first
    env_path = os.environ.get("ARCGIS_PRO_PATH")
    if env_path:
        python_exe = Path(env_path) / "bin" / "Python" / "envs" / "arcgispro-py3" / "python.exe"
        if python_exe.exists():
            return str(python_exe)

    # Get user profile for AppData paths
    user_profile = os.environ.get("USERPROFILE", "")
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")

    # Check default installation paths (Program Files on various drives)
    default_paths = [
        # Standard Program Files locations
        r"C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe",
        r"C:\Program Files (x86)\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe",
        r"D:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe",
        r"D:\Program Files (x86)\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe",
        r"E:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe",
        r"E:\Program Files (x86)\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe",
        # Direct installation at drive root
        r"C:\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe",
        r"D:\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe",
        r"E:\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe",
        # User-specific AppData installations (per-user install)
        os.path.join(local_appdata, r"Programs\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"),
        os.path.join(user_profile, r"AppData\Local\Programs\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"),
        # Alternative environment names
        r"C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3-clone\python.exe",
        r"D:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3-clone\python.exe",
        os.path.join(local_appdata, r"Programs\ArcGIS\Pro\bin\Python\envs\arcgispro-py3-clone\python.exe"),
    ]
    for path in default_paths:
        if path and os.path.exists(path):
            return path

    # Try to resolve from shortcuts in multiple locations
    shortcut_paths = [
        # System-wide Start Menu
        Path(r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\ArcGIS\ArcGIS Pro\ArcGIS Pro.lnk"),
        Path(r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\ArcGIS Pro\ArcGIS Pro.lnk"),
        Path(r"C:\ProgramData\Microsoft\Windows\Start Menu\ArcGIS Pro.lnk"),
        # User-specific Start Menu
        Path(os.path.join(appdata, r"Microsoft\Windows\Start Menu\Programs\ArcGIS\ArcGIS Pro\ArcGIS Pro.lnk")),
        Path(os.path.join(appdata, r"Microsoft\Windows\Start Menu\Programs\ArcGIS Pro\ArcGIS Pro.lnk")),
        Path(os.path.join(appdata, r"Microsoft\Windows\Start Menu\ArcGIS Pro.lnk")),
        Path(os.path.join(user_profile, r"AppData\Roaming\Microsoft\Windows\Start Menu\Programs\ArcGIS\ArcGIS Pro\ArcGIS Pro.lnk")),
        Path(os.path.join(user_profile, r"AppData\Roaming\Microsoft\Windows\Start Menu\Programs\ArcGIS Pro\ArcGIS Pro.lnk")),
        # Desktop shortcuts
        Path(os.path.join(user_profile, r"Desktop\ArcGIS Pro.lnk")),
        Path(os.path.join(user_profile, r"OneDrive\Desktop\ArcGIS Pro.lnk")),
        Path(r"C:\Users\Public\Desktop\ArcGIS Pro.lnk"),
    ]

    for shortcut_path in shortcut_paths:
        if shortcut_path.exists():
            target = resolve_lnk(shortcut_path)
            if target:
                # Derive Python path from ArcGIS Pro executable path
                # Target is like: C:\Program Files\ArcGIS\Pro\bin\ArcGISPro.exe
                arcgis_dir = Path(target).parent.parent  # Go up to Pro directory
                python_exe = arcgis_dir / "bin" / "Python" / "envs" / "arcgispro-py3" / "python.exe"
                if python_exe.exists():
                    return str(python_exe)
                # Also check for clone environment
                python_exe_clone = arcgis_dir / "bin" / "Python" / "envs" / "arcgispro-py3-clone" / "python.exe"
                if python_exe_clone.exists():
                    return str(python_exe_clone)

    # Try Windows Registry lookup as last resort
    try:
        import winreg
        # Check common ArcGIS Pro registry keys
        registry_paths = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\ESRI\ArcGISPro"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\ESRI\ArcGISPro"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\ESRI\ArcGISPro"),
        ]
        for hkey, key_path in registry_paths:
            try:
                with winreg.OpenKey(hkey, key_path) as key:
                    install_dir, _ = winreg.QueryValueEx(key, "InstallDir")
                    if install_dir:
                        python_exe = Path(install_dir) / "bin" / "Python" / "envs" / "arcgispro-py3" / "python.exe"
                        if python_exe.exists():
                            return str(python_exe)
            except (OSError, FileNotFoundError):
                continue
    except ImportError:
        pass  # winreg not available (non-Windows)

    return None


def resolve_lnk(path: Path) -> str | None:
    """
    Resolve a Windows shortcut (.lnk) file to its target path.

    Args:
        path: Path to the .lnk file

    Returns:
        Target path, or None if resolution fails
    """
    try:
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(str(path))
        return shortcut.Targetpath
    except Exception:
        # Fallback: try reading the link file directly (may not work for all .lnk files)
        return None


def execute_arcpy_script(script_code: str, input_data: dict | None = None, timeout_seconds: int | None = None) -> dict[str, Any]:
    """
    Execute a Python script using ArcGIS Pro's Python interpreter.

    Args:
        script_code: Python script code to execute
        input_data: Optional data to pass to the script via stdin
        timeout_seconds: Optional subprocess timeout in seconds. Defaults to metadata/query timeout.

    Returns:
        Dictionary with 'success', 'result', and 'error' keys
    """
    python_exe = find_py_interpreter()
    if not python_exe:
        return {
            "success": False,
            "result": None,
            "error": "ArcGIS Pro Python interpreter not found. Please set ARCGIS_PRO_PATH environment variable."
        }

    timeout_seconds = timeout_seconds or DEFAULT_ARCPY_TIMEOUT_SECONDS

    try:
        # 强制子进程使用 UTF-8 编码，避免 Windows GBK 无法编码中文或 emoji
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        if python_exe not in _arcpy_workers:
            _arcpy_workers[python_exe] = ArcPyWorker(python_exe)
        worker = _arcpy_workers[python_exe]
        reply = worker.run(script_code, input_data, timeout_seconds)
        from types import SimpleNamespace
        result = SimpleNamespace(**{k:reply[k] for k in ('returncode','stdout','stderr')})
        diagnostics = reply.get('execution_diagnostics', {})

        if result.returncode != 0:
            return {
                "success": False,
                "result": None,
                "error": f"Script execution failed: {result.stderr}"
                , "execution_diagnostics": diagnostics
            }

        # Try to parse JSON output from stdout
        try:
            output = json.loads(result.stdout)
            return {
                "success": True,
                "result": output,
                "error": None
                , "execution_diagnostics": diagnostics
            }
        except json.JSONDecodeError:
            # Return raw stdout if not valid JSON
            return {
                "success": True,
                "result": result.stdout.strip(),
                "error": None
                , "execution_diagnostics": diagnostics
            }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "result": None,
            "error": f"Script execution timed out after {format_timeout_message(timeout_seconds)}"
        }
    except Exception as e:
        return {
            "success": False,
            "result": None,
            "error": f"Execution error: {str(e)}"
        }


@mcp.tool()
async def execute_gis_tool(tool_name: str, parameters: dict) -> str:
    """
    Execute a GIS tool through the ArcPy API.

    Args:
        tool_name: Tool name in dot notation, e.g., 'arcpy.analysis.Clip', 'arcpy.management.CopyFeatures'
        parameters: Dictionary of tool parameters. Keys should match the tool's parameter names.
            Example for Clip: {"in_features": "path/to/input", "clip_features": "path/to/clip", "out_feature_class": "path/to/output"}

    Returns:
        JSON string with execution results or error message
    """
    script = '''
import arcpy
import json
import sys

# Read input parameters from stdin
input_json = sys.stdin.read()
params = json.loads(input_json)

tool_name = params["tool_name"]
tool_params = params["parameters"]

try:
    # Navigate to the tool using getattr
    tool_parts = tool_name.split(".")
    tool_obj = arcpy
    for part in tool_parts[1:]:  # Skip 'arcpy' as we already have it
        tool_obj = getattr(tool_obj, part)

    # Execute the tool with unpacked parameters
    result = tool_obj(**tool_params)

    # Try to get output messages
    messages = []
    if hasattr(result, 'getMessages'):
        messages = [result.getMessage(i) for i in range(result.messageCount)]

    output = {
        "success": True,
        "result": str(result) if result else None,
        "messages": messages
    }
    print(json.dumps(output))

except Exception as e:
    import traceback
    error_output = {
        "success": False,
        "error": str(e),
        "traceback": traceback.format_exc()
    }
    print(json.dumps(error_output))
'''

    input_data = {
        "tool_name": tool_name,
        "parameters": parameters
    }

    result = execute_arcpy_script(script, input_data, timeout_seconds=EXECUTE_GIS_TOOL_TIMEOUT_SECONDS)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def list_gdb_contents(gdb_path: str) -> str:
    """
    List all contents of a File Geodatabase (GDB).

    Args:
        gdb_path: Full path to the .gdb directory

    Returns:
        JSON string with categorized contents (FeatureClasses, RasterDatasets, Tables, etc.)
    """
    script = '''
import arcpy
import json
import sys
import os

input_json = sys.stdin.read()
params = json.loads(input_json)
gdb_path = params["gdb_path"]

try:
    if not os.path.exists(gdb_path):
        print(json.dumps({"success": False, "error": f"GDB path does not exist: {gdb_path}"}))
        sys.exit(0)

    contents = {
        "feature_classes": [],
        "raster_datasets": [],
        "tables": [],
        "feature_datasets": [],
        "topologies": [],
        "network_datasets": [],
        "other": []
    }

    # Walk through the GDB
    for dirpath, dirnames, filenames in arcpy.da.Walk(gdb_path):
        for filename in filenames:
            full_path = os.path.join(dirpath, filename)
            try:
                desc = arcpy.Describe(full_path)
                item_info = {
                    "name": filename,
                    "path": full_path,
                    "dataType": desc.dataType if hasattr(desc, 'dataType') else 'Unknown'
                }

                # Categorize by data type
                data_type = desc.dataType if hasattr(desc, 'dataType') else ''

                if data_type == 'FeatureClass':
                    # Get additional info for feature classes
                    if hasattr(desc, 'shapeType'):
                        item_info['shapeType'] = desc.shapeType
                    if hasattr(desc, 'fields'):
                        item_info['fieldCount'] = len(desc.fields)
                    contents['feature_classes'].append(item_info)
                elif data_type == 'RasterDataset':
                    contents['raster_datasets'].append(item_info)
                elif data_type == 'Table':
                    contents['tables'].append(item_info)
                elif data_type == 'FeatureDataset':
                    contents['feature_datasets'].append(item_info)
                elif data_type == 'Topology':
                    contents['topologies'].append(item_info)
                elif data_type == 'NetworkDataset':
                    contents['network_datasets'].append(item_info)
                else:
                    contents['other'].append(item_info)

            except Exception as e:
                contents['other'].append({
                    "name": filename,
                    "path": full_path,
                    "error": str(e)
                })

    # Also list feature datasets at top level
    try:
        arcpy.env.workspace = gdb_path
        datasets = arcpy.ListDatasets()
        if datasets:
            for ds in datasets:
                if ds not in [fd['name'] for fd in contents['feature_datasets']]:
                    contents['feature_datasets'].append({
                        "name": ds,
                        "path": os.path.join(gdb_path, ds),
                        "dataType": "FeatureDataset"
                    })
    except Exception:
        pass

    output = {
        "success": True,
        "gdb_path": gdb_path,
        "contents": contents
    }
    print(json.dumps(output, indent=2))

except Exception as e:
    import traceback
    print(json.dumps({
        "success": False,
        "error": str(e),
        "traceback": traceback.format_exc()
    }))
'''

    input_data = {"gdb_path": gdb_path}
    result = execute_arcpy_script(script, input_data)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def query_feature_attributes(feature_path: str, sql_where: str = "", max_records: int = 100, fields: list[str] | None = None) -> str:
    """
    Query attributes from a feature class or shapefile.

    Args:
        feature_path: Path to the feature class (e.g., 'C:/data.gdb/featureclass' or 'C:/data.shp')
        sql_where: Optional SQL WHERE clause for filtering (without the 'WHERE' keyword)
        max_records: Maximum number of records to return (default 100, hard cap 500 to prevent context explosion)
        fields: Optional list of field names to return (case-insensitive match).
            When omitted, all fields are returned. Specify a subset to save context.
            Example: ["DLBM", "DLMC", "TBMJ"]. Unknown field names cause an error
            listing the available fields.

    Returns:
        JSON string with field definitions and attribute data
    """
    MAX_RECORDS_HARD_CAP = 500
    max_records = min(max_records, MAX_RECORDS_HARD_CAP)
    script = '''
import arcpy
import json
import sys

input_json = sys.stdin.read()
params = json.loads(input_json)

feature_path = params["feature_path"]
sql_where = params.get("sql_where", "")
max_records = params.get("max_records", 100)
requested_fields = params.get("fields", None)

try:
    # Verify the feature exists
    if not arcpy.Exists(feature_path):
        print(json.dumps({
            "success": False,
            "error": f"Feature class does not exist: {feature_path}"
        }))
        sys.exit(0)

    # Get field information
    desc = arcpy.Describe(feature_path)
    fields = []
    field_names = []

    for field in desc.fields:
        fields.append({
            "name": field.name,
            "alias": field.aliasName,
            "type": field.type,
            "length": field.length if hasattr(field, 'length') else None
        })
        field_names.append(field.name)

    # Determine which fields to query and return
    if requested_fields:
        # Case-insensitive match against existing fields
        lower_map = {fn.lower(): fn for fn in field_names}
        selected = []
        unknown = []
        for rf in requested_fields:
            actual = lower_map.get(rf.lower())
            if actual is None:
                unknown.append(rf)
            else:
                selected.append(actual)

        if unknown:
            print(json.dumps({
                "success": False,
                "error": f"Field(s) not found: {unknown}. Available fields: {field_names}"
            }))
            sys.exit(0)

        query_field_names = selected
        returned_fields = [f for f in fields if f["name"] in selected]
    else:
        query_field_names = field_names
        returned_fields = fields

    # Query data using SearchCursor
    data = []
    count = 0

    with arcpy.da.SearchCursor(feature_path, query_field_names, where_clause=sql_where if sql_where else None) as cursor:
        for row in cursor:
            if count >= max_records:
                break
            row_dict = {}
            for i, field_name in enumerate(query_field_names):
                value = row[i]
                # Handle special types for JSON serialization
                if value is None:
                    row_dict[field_name] = None
                elif isinstance(value, (int, float, bool)):
                    row_dict[field_name] = value
                elif isinstance(value, str):
                    # Truncate very long strings to prevent context explosion
                    row_dict[field_name] = value if len(value) <= 500 else value[:500] + "…[truncated]"
                else:
                    # Convert other types to string
                    row_dict[field_name] = str(value)
            data.append(row_dict)
            count += 1

    # Get total count
    total_count = int(arcpy.management.GetCount(feature_path)[0])

    output = {
        "success": True,
        "feature_path": feature_path,
        "total_records": total_count,
        "returned_records": len(data),
        "truncated": len(data) < total_count,
        "fields": returned_fields,
        "data": data
    }

    print(json.dumps(output, indent=2, ensure_ascii=False))

except Exception as e:
    import traceback
    print(json.dumps({
        "success": False,
        "error": str(e),
        "traceback": traceback.format_exc()
    }))
'''

    input_data = {
        "feature_path": feature_path,
        "sql_where": sql_where,
        "max_records": max_records,
        "fields": fields
    }

    result = execute_arcpy_script(script, input_data)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_data_properties(data_path: str) -> str:
    """
    Get properties of a GIS dataset (feature class, shapefile, raster, table, etc.).

    Args:
        data_path: Path to the dataset (e.g., 'C:/data.gdb/featureclass', 'C:/data.shp', 'C:/data.tif')

    Returns:
        JSON string with dataset properties including extent, coordinate system, value range,
        resolution, tolerance, fields and field types
    """
    script = '''
import arcpy
import json
import sys

input_json = sys.stdin.read()
params = json.loads(input_json)

data_path = params["data_path"]

try:
    if not arcpy.Exists(data_path):
        print(json.dumps({
            "success": False,
            "error": f"Dataset does not exist: {data_path}"
        }))
        sys.exit(0)

    desc = arcpy.Describe(data_path)
    data_type = desc.dataType if hasattr(desc, 'dataType') else 'Unknown'

    # Basic info
    properties = {
        "success": True,
        "data_path": data_path,
        "data_type": data_type,
        "name": desc.name if hasattr(desc, 'name') else None,
        "catalog_path": desc.catalogPath if hasattr(desc, 'catalogPath') else None,
    }

    # Extent
    if hasattr(desc, 'extent') and desc.extent:
        ext = desc.extent
        properties["extent"] = {
            "xmin": ext.XMin,
            "ymin": ext.YMin,
            "xmax": ext.XMax,
            "ymax": ext.YMax,
            "zmin": ext.ZMin if hasattr(ext, 'ZMin') else None,
            "zmax": ext.ZMax if hasattr(ext, 'ZMax') else None,
            "mmin": ext.MMin if hasattr(ext, 'MMin') else None,
            "mmax": ext.MMax if hasattr(ext, 'MMax') else None
        }
    else:
        properties["extent"] = None

    # Spatial reference / coordinate system
    if hasattr(desc, 'spatialReference') and desc.spatialReference:
        sr = desc.spatialReference
        properties["coordinate_system"] = {
            "name": sr.name,
            "factory_code": sr.factoryCode if hasattr(sr, 'factoryCode') else None,
            "wkid": sr.factoryCode if hasattr(sr, 'factoryCode') else None,
            "wkt": sr.exportToString() if hasattr(sr, 'exportToString') else None,
            "unit": sr.linearUnitName if hasattr(sr, 'linearUnitName') else None
        }
    else:
        properties["coordinate_system"] = None

    # Tolerance
    if hasattr(desc, 'spatialReference') and desc.spatialReference:
        sr = desc.spatialReference
        tolerance_info = {}
        if hasattr(sr, 'XYTolerance'):
            tolerance_info["xy_tolerance"] = sr.XYTolerance
        if hasattr(sr, 'ZTolerance'):
            tolerance_info["z_tolerance"] = sr.ZTolerance
        if hasattr(sr, 'MTolerance'):
            tolerance_info["m_tolerance"] = sr.MTolerance
        if hasattr(sr, 'XYResolution'):
            tolerance_info["xy_resolution"] = sr.XYResolution
        if hasattr(sr, 'ZResolution'):
            tolerance_info["z_resolution"] = sr.ZResolution
        if hasattr(sr, 'MResolution'):
            tolerance_info["m_resolution"] = sr.MResolution
        properties["tolerance"] = tolerance_info if tolerance_info else None
    else:
        properties["tolerance"] = None

    # Fields (for feature classes, tables, etc.)
    if hasattr(desc, 'fields') and desc.fields:
        fields = []
        for field in desc.fields:
            fields.append({
                "name": field.name,
                "alias": field.aliasName if hasattr(field, 'aliasName') else None,
                "type": field.type,
                "length": field.length if hasattr(field, 'length') else None,
                "precision": field.precision if hasattr(field, 'precision') else None,
                "scale": field.scale if hasattr(field, 'scale') else None,
                "nullable": field.isNullable if hasattr(field, 'isNullable') else None,
                "required": field.required if hasattr(field, 'required') else None,
                "domain": field.domain if hasattr(field, 'domain') else None
            })
        properties["fields"] = fields
    else:
        properties["fields"] = []

    # Feature class specific properties
    if data_type in ('FeatureClass', 'ShapeFile', 'Shapefile'):
        if hasattr(desc, 'shapeType'):
            properties["shape_type"] = desc.shapeType
        if hasattr(desc, 'shapeFieldName'):
            properties["shape_field_name"] = desc.shapeFieldName
        if hasattr(desc, 'featureType'):
            properties["feature_type"] = desc.featureType
        # Feature count
        try:
            properties["feature_count"] = int(arcpy.management.GetCount(data_path)[0])
        except Exception:
            properties["feature_count"] = None

    # Raster specific properties
    if data_type in ('RasterDataset', 'RasterBand'):
        try:
            # Use Raster object for detailed raster info
            raster = arcpy.Raster(data_path)
            properties["raster_properties"] = {
                "width": raster.width,
                "height": raster.height,
                "band_count": raster.bandCount,
                "format": raster.format,
                "pixel_type": raster.pixelType,
                "cell_size": {
                    "x": raster.meanCellWidth,
                    "y": raster.meanCellHeight
                } if hasattr(raster, 'meanCellWidth') else None,
                "no_data_value": raster.noDataValue if hasattr(raster, 'noDataValue') else None,
                "compression": raster.compressionType if hasattr(raster, 'compressionType') else None
            }

            # Value range (min/max)
            try:
                min_val = raster.minimum
                max_val = raster.maximum
                properties["value_range"] = {
                    "minimum": min_val,
                    "maximum": max_val
                }
            except Exception:
                properties["value_range"] = None

            # Resolution
            try:
                properties["resolution"] = {
                    "x": raster.meanCellWidth,
                    "y": raster.meanCellHeight
                }
            except Exception:
                properties["resolution"] = None

            del raster
        except Exception as e:
            properties["raster_properties"] = {"error": str(e)}
            properties["value_range"] = None
            properties["resolution"] = None

    print(json.dumps(properties, indent=2, ensure_ascii=False))

except Exception as e:
    import traceback
    print(json.dumps({
        "success": False,
        "error": str(e),
        "traceback": traceback.format_exc()
    }))
'''

    input_data = {"data_path": data_path}
    result = execute_arcpy_script(script, input_data)
    return json.dumps(result, ensure_ascii=False, indent=2)


# @mcp.tool()
# async def get_arcpy_info() -> str:
    """
    Get information about the ArcPy installation and ArcGIS Pro version.

    Returns:
        JSON string with ArcPy version, product info, and installation details
    """
    script = '''
import arcpy
import json
import sys

try:
    info = {
        "success": True,
        "arcpy_version": arcpy.GetInstallInfo().get("Version", "Unknown"),
        "product_name": arcpy.GetInstallInfo().get("ProductName", "Unknown"),
        "install_dir": arcpy.GetInstallInfo().get("InstallDir", "Unknown"),
        "build_number": arcpy.GetInstallInfo().get("BuildNumber", "Unknown"),
        "python_version": sys.version,
        "spatial_references_available": True
    }

    # Try to get list of available toolboxes
    try:
        toolboxes = [tb for tb in dir(arcpy) if not tb.startswith('_')]
        info['available_modules'] = toolboxes[:50]  # Limit to first 50
    except Exception:
        pass

    print(json.dumps(info, indent=2))

except Exception as e:
    import traceback
    print(json.dumps({
        "success": False,
        "error": str(e),
        "traceback": traceback.format_exc()
    }))
'''

    # result = execute_arcpy_script(script)
    # return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_field_unique_values(feature_path: str, field_name: str, max_unique_values: int = 50) -> str:
    """
    Get unique values and their record counts for a specific field.

    When the number of unique values exceeds max_unique_values, only the count is returned
    (to avoid context explosion). When within the threshold, returns the full breakdown
    sorted by record count descending.

    Args:
        feature_path: Path to the feature class or shapefile.
            Example: 'C:/data.gdb/featureclass' or 'C:/data.shp'
        field_name: Name of the field to analyze.
            Must be an existing field in the dataset.
        max_unique_values: Threshold above which the tool skips the value breakdown.
            Defaults to 50. Set to a lower value for faster results on high-cardinality fields.

    Returns:
        JSON string with:
        - unique_count: Total number of unique values in the field
        - value_counts: (only when unique_count <= max_unique_values)
            Array of {value, count} objects sorted by count descending
        - field_type: The field's data type
        - total_records: Total record count in the dataset
    """
    script = '''
import arcpy
import json
import sys

input_json = sys.stdin.read()
params = json.loads(input_json)

feature_path = params["feature_path"]
field_name = params["field_name"]
max_unique_values = params.get("max_unique_values", 50)

try:
    if not arcpy.Exists(feature_path):
        print(json.dumps({
            "success": False,
            "error": f"Dataset does not exist: {feature_path}"
        }))
        sys.exit(0)

    desc = arcpy.Describe(feature_path)

    # Verify field exists and get its type
    field_info = None
    for field in desc.fields:
        if field.name.lower() == field_name.lower():
            field_info = {
                "name": field.name,
                "type": field.type,
                "alias": field.aliasName if hasattr(field, 'aliasName') else None,
                "length": field.length if hasattr(field, 'length') else None
            }
            break

    if field_info is None:
        print(json.dumps({
            "success": False,
            "error": f"Field '{field_name}' not found in {feature_path}. Available fields: {[f.name for f in desc.fields]}"
        }))
        sys.exit(0)

    # Get total record count
    total_records = int(arcpy.management.GetCount(feature_path)[0])

    # Count unique values using SearchCursor
    value_counts = {}
    null_count = 0

    with arcpy.da.SearchCursor(feature_path, [field_name]) as cursor:
        for row in cursor:
            val = row[0]
            if val is None:
                null_count += 1
            elif isinstance(val, (int, float)):
                # Use the raw number as key
                value_counts[val] = value_counts.get(val, 0) + 1
            else:
                # String or other — truncate if too long to prevent memory issues
                key = str(val)
                if len(key) > 500:
                    key = key[:500] + "…[truncated]"
                value_counts[key] = value_counts.get(key, 0) + 1

    unique_count = len(value_counts)

    # Build result
    result = {
        "success": True,
        "feature_path": feature_path,
        "field_name": field_name,
        "field_info": field_info,
        "total_records": total_records,
        "null_count": null_count,
        "unique_count": unique_count
    }

    # Only include value breakdown when within threshold
    if unique_count <= max_unique_values:
        sorted_counts = sorted(
            [{"value": k, "count": v} for k, v in value_counts.items()],
            key=lambda x: x["count"],
            reverse=True
        )
        result["value_counts"] = sorted_counts
        result["truncated"] = False
    else:
        result["value_counts"] = None
        result["truncated"] = True
        result["note"] = (
            f"Unique count ({unique_count}) exceeds threshold ({max_unique_values}). "
            "Set max_unique_values higher to get the full breakdown."
        )

    print(json.dumps(result, indent=2, ensure_ascii=False))

except Exception as e:
    import traceback
    print(json.dumps({
        "success": False,
        "error": str(e),
        "traceback": traceback.format_exc()
    }))
'''

    input_data = {
        "feature_path": feature_path,
        "field_name": field_name,
        "max_unique_values": max_unique_values
    }
    result = execute_arcpy_script(script, input_data)
    return json.dumps(result, ensure_ascii=False, indent=2)


def main():
    """Run the MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
