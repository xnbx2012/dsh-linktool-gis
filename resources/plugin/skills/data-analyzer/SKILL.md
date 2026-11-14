---
name: data-analyzer
description: 数据分析核心，输出统计数据、文字分析结论和数据洞察。纯 Python 内置库，无需依赖。
---

当执行此任务时，调用 `analyze` 智能体来处理。

## 快速开始

```bash
python plugin/skills/data-analyzer/analyzer.py \
    --mission-id "[任务ID]" \
    --output-dir "./output" \
    --data-sources '{"[数据源名]": "./data.csv"}' \
    --numeric-fields "[字段1],[字段2]" \
    --categorical-fields '{"[数据源]": "[分类字段]"}'
```

---

## 参数说明

| 参数 | 必需 | 说明 | 示例 |
|:---|:---:|:---|:---|
| `--mission-id` | ✅ | 任务标识符 | `"[任务ID]"` |
| `--data-sources` | ✅ | 数据源 JSON | `'{"[数据源名]": "[文件路径]"}'` |
| `--output-dir` | ❌ | 输出目录（默认 ./output） | `"./output"` |
| `--numeric-fields` | ❌ | 数值字段（逗号分隔） | `"[字段1],[字段2]"` |
| `--categorical-fields` | ❌ | 分类字段（JSON） | `'{"[数据源]": "[字段名]"}'` |
| `--thresholds` | ❌ | 阈值配置（JSON） | 见下方 |

---

## 阈值配置（可选）

```bash
--thresholds '{
  "[字段名]": {"optimal_range": [最小值, 最大值], "critical_min": 临界值},
  "[字段名2]": {"optimal_range": [最小值, 最大值]}
}'
```

---

## 输出结果

```
output/
├── report_summary.json           # 完整分析数据
├── conclusions.json              # 文字结论（可直接用于报告）
├── chart_recommendations.json     # 图表推荐配置
└── tables/
    ├── stats_[数据源].csv        # 统计表
    └── cat_[数据源].csv          # 分类表
```

---

## conclusions.json 示例

```json
{
  "sections": {
    "statistics": [
      {
        "field": "[字段名]",
        "source": "[数据源]",
        "text": "[自动生成的分析结论]"
      }
    ],
    "categories": [
      {
        "source": "[数据源]",
        "text": "[分类统计结论]"
      }
    ]
  }
}
```

---

## 图表推荐功能

根据数据特征自动推荐合适的图表类型。

### 推荐规则

| 数据类型 | 条件 | 推荐图表 | 优先级 |
|:---|:---|:---|:---|
| 分类数据 | 类别 ≤ 8 | 柱状图 (column) | 90 |
| 分类数据 | 类别 > 8 | 水平柱状图 (bar) | 85 |
| 数值数据 | 数据量 ≥ 20 | 直方图 (histogram) | 95 |
| 数值数据 | 变异系数 > 0.3 | 箱线图 (box_plot) | 75 |

### chart_recommendations.json

```json
{
  "[数据源]_[字段名]": [
    {
      "chart_type": "histogram",
      "title": "[字段] 分布直方图",
      "data_source": "tables/stats_[数据源].csv",
      "reason": "[推荐理由]",
      "priority": 95
    }
  ]
}
```

---

## 数据洞察内容

- **分布特征**: 变异程度（低/中/高）、偏度判断
- **异常检测**: IQR 方法检测异常值
- **阈值比较**: 与适宜范围、临界值比较
- **文字摘要**: 自动整合所有信息成段落
