---
name: visual-check
description: 对面状覆盖类 GIS 结果做视觉核验，发现空隙、孔洞、碎屑、覆盖缺失等空间形态问题。仅限 gis-tool Agent 在 result-confirm 阶段调用。
agent: gis-tool
context: fork
---

通过出图 + 原生 Read 读图，发现属性/几何核验查不出的空间形态问题。配套参考库：同目录 `operation-checks.md`。

铁律：只判数据问题，绝不评价美观/配色/排版。

# 0. 门控

满足任一条件才执行，否则返回 `SKIP`：

**触发**（面状 + 易产生空间缺陷的操作）：
- 叠加/裁切类：Clip、Erase、Intersect、Union、Identity
- 融合/分区类：Dissolve 融合面、评价分区、专题制图面
- 已融合缓冲：Buffer + `dissolve=ALL/LIST`
- 合同 `validation_criteria` 明确含视觉/空间要求

**跳过**：
- 独立缓冲（`dissolve=NONE`）、投影、复制、类型转换
- 纯属性/表格计算、字段增删、统计汇总
- 点要素、线要素、栅格（除非合同明确要求）

> 判据：逐要素独立、构造即确定的结果 → SKIP；多要素间有拓扑/覆盖关系的面状成果 → 执行。

# 1. 出图

调用 `create_map` 渲染 PNG，输出到 `02_WorkSpace/_visual_check/<结果名>_check.png`：

- 结果层：`simple` 符号，半透明填充 + 清晰轮廓（`fill_color:[120,200,120,70]`，`outline_color:[60,60,60,100]`）
- 参考层：查 `operation-checks.md` 取本次操作的必叠参考层（Clip→裁剪要素、Intersect→两输入层、Dissolve→研究区范围等），红色轮廓叠加渲染
- 出图失败 → 返回 `SKIP`

# 2. 拟定检查清单

查 `operation-checks.md` 取本次 `operation_type` 的正面信号、负面信号、交叉项，结合合同 `validation_criteria` 组装逐条比对清单。未列出的工具用通用症状库兜底。

# 3. 读图 + 数据交叉

用原生 `Read` 读取 PNG，对照清单逐条检查：

1. 确认正面信号是否齐全，缺失记为疑点
2. 排查负面信号（空隙/孔洞/碎屑/不连续/错位/覆盖缺失/缺角/形变）
3. 命中可疑点时，执行数据交叉印证：
   - 碎屑/缝隙 → `query_feature_attributes`（`sql_where: Shape_Area < 阈值`）
   - 错位/形变 → `get_data_properties` 比对 CRS/extent
   - 覆盖缺失 → `get_data_properties` 比对 feature_count/extent

读图失败 → 返回 `SKIP`。

# 4. 判定与返回

- 命中负面信号且数据交叉印证异常 → **FAIL**
- 正面信号齐全、无异常 → **PASS**

**FAIL 处理**：调用 `/tool-retry`，携带工具全名、症状、根因推测、建议修复动作。视觉问题无真实错误码，不写入 memory-server。

**返回格式**：

```markdown
## Visual Check Result
- status: PASS | FAIL | SKIP
- operation_type: <操作类型>
- image: 02_WorkSpace/_visual_check/<...>.png
- findings: [命中的负面信号]
- traceability:
  - symptom: <异常描述>
    data_evidence: <交叉验证结果>
    probable_cause: <根因推测>
    suggested_fix: <修复建议>
- conclusion: [一句话结论]
```
