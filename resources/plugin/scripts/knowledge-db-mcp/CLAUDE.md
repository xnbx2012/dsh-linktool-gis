# CLAUDE.md — knowledge-db-mcp

向量知识库 MCP 服务器。基于 SQLite + sqlite_vec 提供 GIS 案例的语义检索，通过 SiliconFlow API 进行文本嵌入和重排序。

---

## 项目结构

```
knowledge-db-mcp/
├── main.py          # FastMCP 服务器 + search_knowledge 工具
├── data.sqlite      # SQLite 数据库（向量表 + 文档内容表）
├── run.bat          # 启动脚本（封装 uv run python main.py）
├── pyproject.toml   # uv 依赖配置（httpx, mcp, sqlite-vec）
└── uv.lock          # 锁定的依赖版本
```

---

## 工具列表

### `search_knowledge(query, top_k, use_rerank)`

在向量数据库中检索相关文档。

- `query`: 搜索关键词或自然语言问题
- `top_k`: 返回结果数量（默认 10）
- `use_rerank`: 是否使用 Reranker 优化结果排序（默认 `True`）

**返回**:
```json
{
  "results": [
    {
      "id": 1,
      "source_file": "案例文件名.md",
      "h1": "一级标题",
      "h2": "二级标题",
      "content": "文档片段内容...",
      "distance": 0.123,
      "rerank_score": 0.95
    }
  ],
  "total": 10
}
```

**检索流程**:
1. `init_vec_table(db)` 检查并初始化 `vec_chunks` 虚拟表
2. 如 `vec_chunks` 为空，从 `chunks` 表迁移已有嵌入数据
3. `get_embedding(query)` 调用 SiliconFlow API 获取查询向量（512维）
4. KNN 向量检索（如启用 rerank 则取 `top_k * 3` 条候选）
5. 从 `chunks` 表获取候选文档的元信息（source_file, h1, h2, content）
6. 如启用 rerank，调用 SiliconFlow Reranker API 重排序
7. 返回最终结果

---

## 数据库结构

### `chunks` 表
| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER | 主键 |
| `source_file` | TEXT | 源文件路径 |
| `h1` | TEXT | 一级标题 |
| `h2` | TEXT | 二级标题 |
| `content` | TEXT | 文档片段内容 |
| `embedding` | BLOB | 预计算的嵌入向量（512维 float 打包） |

### `vec_chunks` 虚拟表
- sqlite_vec 扩展创建的向量虚拟表
- `chunk_id INTEGER PRIMARY KEY`（与 `chunks.id` 关联）
- `embedding float[512]`（支持 `embedding MATCH ?` 语法进行 KNN 搜索）

---

## SiliconFlow API 配置

| 配置项 | 值 |
|--------|-----|
| 接口基址 | `https://api.siliconflow.cn` |
| 嵌入模型 | `Qwen/Qwen3-Embedding-4B`（512维） |
| 重排序模型 | `Qwen/Qwen3-Reranker-8B` |
| API Key | 环境变量 `SILICONFLOW_API_KEY`（在 `plugin.json` 中配置） |

**插件配置**（`plugin/.claude-plugin/plugin.json`）:
```json
"knowledge-db": {
  "command": "${CLAUDE_PLUGIN_ROOT}/scripts/knowledge-db-mcp/run.bat",
  "env": {
    "SILICONFLOW_API_KEY": "sk-..."
  }
}
```

---

## 开发规范

### 数据库管理

- `data.sqlite` 可以替换或更新，重启服务器后自动检测并初始化
- 新增知识库数据时，需要先计算嵌入并写入 `chunks` 表，然后重启服务器触发 `init_vec_table` 自动迁移到 `vec_chunks`
- 嵌入向量通过 `struct.pack("512f", *floats)` 打包为 BLOB 存储

### 本地调试

```bash
# 直接启动（需设置环境变量）
set SILICONFLOW_API_KEY=sk-...
uv run python main.py

# 或通过 run.bat（自动进入脚本所在目录）
run.bat
```

---

## 依赖

```toml
[project]
requires-python = ">=3.12"
dependencies = [
    "httpx>=0.28.1",
    "mcp>=1.26.0",
    "sqlite-vec>=0.1.7",
]
```

---

## 知识库知识类型

当前知识库按以下类型组织：

- **选址类**: 设施选址、缓冲区叠加、最优路径
- **评价类**: 耕地质量、适宜性、生态敏感性
- **预测类**: 空间模拟、趋势分析
- **网络分析类**: 路径规划、服务区分析、设施优化
- **统计报表类**: 分区统计、密度分析、热点分析

**检索策略**: 以任务类型关键词 + 主要数据名作为 `query` 传入
