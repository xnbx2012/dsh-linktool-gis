# -*- coding: utf-8 -*-
"""工具列表 schema 加载器与搜索器。

从 schema.json（启动时预生成）加载四引擎工具列表，替代 list_available_tools
每次调用时动态遍历各引擎（whitebox / gdal / qgis）的开销。

结构（与 export_param_schema.py 导出的 schema.json 兼容）：
{
  "engines": {
    "inner": { "<tool>": { "description", "category", "required", "params" } },
    "whitebox": { "<tool>": { "description", "category", "required", "params" } },
    "gdal": { "<gdal:tool>": { "description", "category", "required", "params" } },
    "qgis": { "<provider:algo>": { "name", "provider", "group", "description" } }
  },
  "generated_at": "ISO timestamp",
  "wbt_count": N, "inner_count": N, "gdal_count": N, "qgis_count": N
}

用法：
  from schema_loader import load_schema, search_tools

  schema = load_schema()  # 加载缓存
  results = search_tools(schema, keyword="buffer", source="all")
"""

from __future__ import annotations

import difflib
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# 共享 GIS 读写封装目录（与 main.py 同级 shared/）
_SHARED_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "shared"))

# 进程级缓存：已加载的 schema
_SCHEMA_CACHE: dict[str, Any] | None = None
# schema.json 路径（启动时由 main.py 传入）
_SCHEMA_PATH: str | None = None


def set_schema_path(path: str) -> None:
    """设置 schema.json 路径（在 main.py 启动序列中调用）。"""
    global _SCHEMA_PATH
    _SCHEMA_PATH = path


def _default_schema() -> dict[str, Any]:
    """返回空的默认 schema（各引擎空 dict），用于 schema.json 缺失/损坏时兜底。"""
    return {
        "engines": {
            "inner": {},
            "whitebox": {},
            "gdal": {},
            "qgis": {},
        },
        "generated_at": None,
        "wbt_count": 0,
        "inner_count": 0,
        "gdal_count": 0,
        "qgis_count": 0,
        "fallback": True,
    }


def load_schema(force_reload: bool = False) -> dict[str, Any]:
    """加载 schema.json 到内存缓存。

    优先从磁盘加载；若文件不存在或解析失败，返回默认空 schema
    （list_available_tools 回退到动态查询）。

    Args:
        force_reload: 强制从磁盘重新加载（绕过缓存）。

    Returns:
        schema dict，与 export_param_schema.py 导出的结构一致。
    """
    global _SCHEMA_CACHE
    if not force_reload and _SCHEMA_CACHE is not None:
        return _SCHEMA_CACHE

    path = _SCHEMA_PATH
    if path is None:
        # 尝试在脚本同目录查找
        path = os.path.join(os.path.dirname(__file__), "schema.json")

    if not os.path.isfile(path):
        logger.warning("[schema_loader] schema.json not found at %s, using empty fallback", path)
        _SCHEMA_CACHE = _default_schema()
        return _SCHEMA_CACHE

    try:
        with open(path, "r", encoding="utf-8") as f:
            schema = json.load(f)
        # 验证基本结构
        if "engines" not in schema:
            raise ValueError("schema.json missing 'engines' key")
        for eng in ("inner", "whitebox", "gdal", "qgis"):
            if eng not in schema["engines"]:
                schema["engines"][eng] = {}
        _SCHEMA_CACHE = schema
        logger.info(
            "[schema_loader] loaded schema: inner=%d whitebox=%d gdal=%d qgis=%d",
            schema.get("inner_count", len(schema["engines"].get("inner", {}))),
            schema.get("wbt_count", len(schema["engines"].get("whitebox", {}))),
            schema.get("gdal_count", len(schema["engines"].get("gdal", {}))),
            schema.get("qgis_count", len(schema["engines"].get("qgis", {}))),
        )
        return _SCHEMA_CACHE
    except Exception as e:
        logger.warning("[schema_loader] failed to load schema.json: %s, using empty fallback", e)
        _SCHEMA_CACHE = _default_schema()
        return _SCHEMA_CACHE


def _match_item(key: str, info: dict[str, Any], kw: str) -> bool:
    """keyword 是否匹配某工具项（匹配 name/key 与 description）。"""
    if not kw:
        return True
    kw_lower = kw.lower()
    # 匹配 key（工具名）或 name
    if kw_lower in key.lower():
        return True
    name = info.get("name", "") or ""
    if kw_lower in name.lower():
        return True
    # 匹配 description
    desc = info.get("description", "") or ""
    if kw_lower in desc.lower():
        return True
    # 匹配 category
    cat = info.get("category", "") or ""
    if kw_lower in cat.lower():
        return True
    # 匹配 group（qgis）
    group = info.get("group", "") or ""
    if kw_lower in group.lower():
        return True
    return False


def search_tools(
    schema: dict[str, Any],
    keyword: str = "",
    source: str = "all",
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """从 schema 中搜索工具。

    Args:
        schema: load_schema() 返回的缓存 schema。
        keyword: 过滤关键字（匹配 name / description / category，大小写不敏感）。
        source: 引擎筛选，'all' / 'inner' / 'wbt' / 'whitebox' / 'qgis'。

    Returns:
        (items, totals_by_engine)
        items: [{name, engine, category, description}, ...]，已按 keyword 过滤。
        totals_by_engine: 各引擎工具总数（过滤前）。
    """
    kw = (keyword or "").strip().lower()
    src = (source or "all").strip().lower()
    if src == "whitebox":
        src = "wbt"

    engines = schema.get("engines", {})
    items: list[dict[str, Any]] = []
    totals: dict[str, int] = {}

    # inner
    if src in ("all", "inner"):
        inner = engines.get("inner", {})
        totals["inner"] = len(inner)
        for name, info in inner.items():
            if _match_item(name, info, kw):
                items.append({
                    "name": name,
                    "engine": "inner",
                    "category": info.get("category", "内置(纯Python)"),
                    "description": info.get("description", ""),
                })

    # whitebox
    if src in ("all", "wbt"):
        wbt = engines.get("whitebox", {})
        totals["wbt"] = len(wbt)
        for name, info in wbt.items():
            if _match_item(name, info, kw):
                items.append({
                    "name": name,
                    "engine": "wbt",
                    "category": info.get("category", ""),
                    "description": info.get("description", ""),
                })

    # gdal
    if src in ("all", "gdal"):
        gdal = engines.get("gdal", {})
        totals["gdal"] = len(gdal)
        for name, info in gdal.items():
            if _match_item(name, info, kw):
                items.append({
                    "name": name,
                    "engine": "gdal",
                    "category": f"GDAL/{info.get('group', '')}",
                    "description": info.get("description", ""),
                })

    # qgis
    if src in ("all", "qgis"):
        qgis = engines.get("qgis", {})
        totals["qgis"] = len(qgis)
        for name, info in qgis.items():
            if _match_item(name, info, kw):
                items.append({
                    "name": name,
                    "engine": "qgis",
                    "category": f"QGIS/{info.get('provider', '')}/{info.get('group', '')}",
                    "description": info.get("description", ""),
                })

    return items, totals


def suggest_similar(
    schema: dict[str, Any],
    target: str,
    source: str = "all",
    limit: int = 8,
) -> dict[str, list[str]]:
    """对未知工具名给出编辑距离最近的建议（按引擎分组）。"""
    target_norm = target.strip().lower().replace("-", "_").replace(" ", "_")
    engines = schema.get("engines", {})
    result: dict[str, list[str]] = {}

    for eng, eng_key in [("inner", "inner"), ("wbt", "whitebox"),
                         ("gdal", "gdal"), ("qgis", "qgis")]:
        if source not in ("all", eng):
            continue
        tools = list(engines.get(eng_key, {}).keys())
        hits = difflib.get_close_matches(target_norm, tools, n=limit, cutoff=0.3)
        if not hits:
            hits = [t for t in tools if t.startswith(target_norm[:3])][:limit]
        result[eng] = hits

    return result


def is_schema_valid(schema: dict[str, Any]) -> bool:
    """检查 schema 是否有效（有真实工具数据）。"""
    if schema.get("fallback"):
        return False
    engines = schema.get("engines", {})
    return bool(
        engines.get("inner") or engines.get("whitebox")
        or engines.get("gdal") or engines.get("qgis")
    ) and (
        len(engines.get("inner", {}))
        + len(engines.get("whitebox", {}))
        + len(engines.get("gdal", {}))
        + len(engines.get("qgis", {}))
    ) > 0
