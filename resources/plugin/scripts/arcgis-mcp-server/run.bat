@echo off
REM ArcGIS MCP Server 启动脚本
REM 通过 cd /d "%~dp0" 切换到脚本目录，避免中文路径编码问题
cd /d "%~dp0"
uv run --with "mcp[cli]" python main.py
