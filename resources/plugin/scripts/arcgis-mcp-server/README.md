# ArcGIS MCP Server

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that provides GIS tools and data access through ArcPy. This server enables Claude and other MCP clients to execute ArcGIS operations, query geodatabases, and manipulate spatial data.

## Features

- **GIS Tool Execution**: Execute any ArcPy tool (e.g., `arcpy.analysis.Clip`, `arcpy.management.Buffer`)
- **Geodatabase Management**: List and explore File Geodatabase (GDB) contents
- **Feature Querying**: Query attribute tables with SQL WHERE clauses
- **ArcPy Information**: Get ArcGIS Pro installation details and version info

## Requirements

- **ArcGIS Pro** must be installed on the system
- Python 3.12 or higher
- The server runs in the local Python environment but executes ArcPy operations through ArcGIS Pro's Python interpreter

## Installation

### 1. Clone and Setup

```bash
git clone <repository-url>
cd arcgis-mcp-server

# Install dependencies using uv (recommended)
uv sync

# Or using pip
pip install -e ".[windows]"
```

### 2. Configure MCP Server

#### Option A: Using `mcp install` (Recommended)

```bash
# Install the server into Claude Desktop configuration
mcp install main.py --name "arcgis-mcp-server"
```

#### Option B: Manual Configuration

Edit your Claude Desktop configuration file:

- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

Add the following configuration:

```json
{
  "mcpServers": {
    "arcgis": {
      "command": "uv",
      "args": [
        "run",
        "--with",
        "mcp[cli]",
        "python",
        "main.py"
      ],
      "cwd": "D:\\02_User_Files\\02项目文件\\20260116_LinkTool\\tool_agent\\plugin\\arcgis-mcp-server"
    }
  }
}
```

Or using Python directly:

```json
{
  "mcpServers": {
    "arcgis": {
      "command": "python",
      "args": ["-m", "main"],
      "cwd": "D:\\02_User_Files\\02项目文件\\20260116_LinkTool\\tool_agent\\plugin\\arcgis-mcp-server"
    }
  }
}
```

## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `ARCGIS_PRO_PATH` | Path to ArcGIS Pro installation directory | `C:\Program Files\ArcGIS\Pro` |

If `ARCGIS_PRO_PATH` is not set, the server will try to auto-detect ArcGIS Pro from common installation paths or the Start Menu shortcut.

## Available Tools

### 1. `execute_gis_tool`

Execute any ArcPy tool by name with parameters.

**Parameters:**
- `tool_name`: Tool path in dot notation (e.g., `arcpy.analysis.Clip`)
- `parameters`: Dictionary of tool parameters

**Example:**
```python
# Clip features
tool_name = "arcpy.analysis.Clip"
parameters = {
    "in_features": "C:/data/input.shp",
    "clip_features": "C:/data/clip_boundary.shp",
    "out_feature_class": "C:/data/output.shp"
}
```

### 2. `list_gdb_contents`

List all contents of a File Geodatabase.

**Parameters:**
- `gdb_path`: Full path to the `.gdb` directory

**Returns:**
- Feature classes, raster datasets, tables, feature datasets, topologies, network datasets

### 3. `query_feature_attributes`

Query attributes from a feature class or shapefile.

**Parameters:**
- `feature_path`: Path to the feature class
- `sql_where`: Optional SQL WHERE clause (without `WHERE` keyword)
- `max_records`: Maximum records to return (default: 100)

**Example:**
```python
feature_path = "C:/data/parcels.shp"
sql_where = "ZONE = 'R1' AND AREA > 1000"
max_records = 50
```

### 4. `get_arcpy_info`

Get ArcGIS Pro and ArcPy installation information.

**Returns:**
- ArcPy version
- Product name
- Installation directory
- Build number
- Python version

## How It Works

Since ArcPy is only available within the ArcGIS Pro Python environment, this server uses a subprocess execution pattern:

1. The MCP server receives tool calls in the local Python environment
2. It constructs Python scripts containing the ArcPy operations
3. Scripts are executed via `subprocess.run()` using ArcGIS Pro's Python interpreter
4. Results are serialized as JSON and returned to the client

This approach ensures:
- The MCP server remains stable even if ArcPy operations fail
- No ArcPy dependency in the main environment
- Proper isolation of GIS operations

## Testing

### Test with Claude Code

Once configured, you can test the server in Claude Code:

```
Check my ArcGIS Pro installation info
```

```
List the contents of my geodatabase at C:/data/test.gdb
```

```
Query the first 10 records from C:/data/parcels.shp where ZONE = 'R1'
```

### Test Server Directly

```bash
# Run the server
python main.py

# In another terminal, test with mcp client
mcp client --server arcgis
```

## Troubleshooting

### "ArcGIS Pro Python interpreter not found"

Set the `ARCGIS_PRO_PATH` environment variable:

```powershell
$env:ARCGIS_PRO_PATH = "C:\Program Files\ArcGIS\Pro"
```

Or add it to your system environment variables.

### Tool execution timeout

Long-running GIS operations may exceed the 15-minute (900 seconds) execute_gis_tool timeout. Consider:
- Breaking operations into smaller chunks
- Using direct ArcPy scripts for very large datasets

### Permission errors

Ensure the user running the MCP server has:
- Read access to input data paths
- Write access to output directories
- Execute permissions on ArcGIS Pro's Python interpreter

## License

MIT License - See LICENSE file for details.

## Contributing

Contributions are welcome! Please submit issues and pull requests on the project repository.
