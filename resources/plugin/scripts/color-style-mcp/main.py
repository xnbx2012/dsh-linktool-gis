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

from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("arcgis-mcp-server")


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


def execute_arcpy_script(script_code: str, input_data: dict | None = None) -> dict[str, Any]:
    """
    Execute a Python script using ArcGIS Pro's Python interpreter.

    Args:
        script_code: Python script code to execute
        input_data: Optional data to pass to the script via stdin

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

    try:
        result = subprocess.run(
            [python_exe, "-c", script_code],
            input=json.dumps(input_data) if input_data else None,
            capture_output=True,
            text=True,
            timeout=900  # 15 minute timeout
        )

        if result.returncode != 0:
            return {
                "success": False,
                "result": None,
                "error": f"Script execution failed: {result.stderr}"
            }

        # Try to parse JSON output from stdout
        try:
            output = json.loads(result.stdout)
            return {
                "success": True,
                "result": output,
                "error": None
            }
        except json.JSONDecodeError:
            # Return raw stdout if not valid JSON
            return {
                "success": True,
                "result": result.stdout.strip(),
                "error": None
            }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "result": None,
            "error": "Script execution timed out after 15 minutes (900 seconds)"
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
        messages = [result.getMessages(i) for i in range(result.messageCount)]

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

    result = execute_arcpy_script(script, input_data)
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
async def query_feature_attributes(feature_path: str, sql_where: str = "", max_records: int = 100) -> str:
    """
    Query attributes from a feature class or shapefile.

    Args:
        feature_path: Path to the feature class (e.g., 'C:/data.gdb/featureclass' or 'C:/data.shp')
        sql_where: Optional SQL WHERE clause for filtering (without the 'WHERE' keyword)
        max_records: Maximum number of records to return (default 100, use to prevent context explosion)

    Returns:
        JSON string with field definitions and attribute data
    """
    script = '''
import arcpy
import json
import sys

input_json = sys.stdin.read()
params = json.loads(input_json)

feature_path = params["feature_path"]
sql_where = params.get("sql_where", "")
max_records = params.get("max_records", 100)

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

    # Query data using SearchCursor
    data = []
    count = 0

    with arcpy.da.SearchCursor(feature_path, field_names, where_clause=sql_where if sql_where else None) as cursor:
        for row in cursor:
            if count >= max_records:
                break
            row_dict = {}
            for i, field_name in enumerate(field_names):
                value = row[i]
                # Handle special types for JSON serialization
                if value is None:
                    row_dict[field_name] = None
                elif isinstance(value, (int, float, str, bool)):
                    row_dict[field_name] = value
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
        "fields": fields,
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
        "max_records": max_records
    }

    result = execute_arcpy_script(script, input_data)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def get_arcpy_info() -> str:
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

    result = execute_arcpy_script(script)
    return json.dumps(result, ensure_ascii=False, indent=2)


def main():
    """Run the MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
