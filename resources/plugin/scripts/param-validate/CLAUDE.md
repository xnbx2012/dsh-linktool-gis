# CLAUDE.md — param-validate

GIS 工具参数形式校验 Hook。在 `PreToolUse` 阶段校验 `execute_gis_tool` 的参数是否完整和正确。覆盖五引擎（arcpy + 内置/Whitebox/GDAL/QGIS）两种 schema。

---

## 触发配置

```json
{
  "matcher": "mcp__plugin_linktool-plugin_arcgis-mcp-server__execute_gis_tool",
  "hooks": [
    { "type": "command", "command": "uv run --no-project python \"${DSH_PLUGIN_ROOT}/scripts/param-validate/main.py\"" }
  ]
}
```

## 双 schema

| schema | 覆盖 | 来源 |
|---|---|---|
| `schema.json`（本目录，静态入库） | `arcpy.*` 工具：必填参数、参数类型、输入路径存在性 | 原插件工具参数数据库 |
| `../arcgis-mcp-server/schema.json`（engines 段，运行时生成，7 天 TTL） | `inner_`/`wbt_`/`gdal_`/`qgis_` 前缀或裸名：必填参数、非空、轻量数值类型 | arcgis-mcp-server 启动时生成（单一事实源；缺失时引擎段仅提示不阻止） |

工具名解析与 `main.py._resolve_engine` 一致：前缀强制引擎；裸名按 inner → whitebox → gdal(:) → qgis(:) 降级查找；`arcpy.` 形态走 arcpy schema 分支。

## 校验规则

1. **必填参数校验**：缺失或为空 → 阻止（exit 2）
2. **类型校验**：arcpy 按数据类型（路径存在性/数值/布尔）；五引擎按 parameter_type 做轻量数值检查（不查路径存在性，引擎自身会给清晰错误）
3. **未知参数警告**：不在 schema 中的参数警告但不阻止
4. **未收录工具**：仅警告不阻止（exit 0）

## 退出码

| 退出码 | 含义 |
|--------|------|
| `0` | 参数校验通过（含仅警告） |
| `2` | 缺少必填参数或类型错误（阻止执行） |
| `1` | 脚本内部错误 |

## 调试

```bash
echo '{"cwd":"D:/proj","tool_input":{"tool_name":"wbt_clip","parameters":{"input":"D:/proj/01_DataBackup/a.shp","clip":"D:/proj/01_DataBackup/b.shp"}}}' | uv run --no-project python main.py
# 缺 output → exit 2
```
