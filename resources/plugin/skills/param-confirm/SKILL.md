---
name: param-confirm
description: 当用户要执行 ArcGIS 工具但关键业务参数缺失或有歧义时，查文档补参。仅限 gis-tool Agent 使用。
argument-hint: 工具名称及已知参数
allowed-tools: bing-search, WebFetch
agent: gis-tool
context: fork
---

核对 $ARGUMENTS 的参数是否满足执行要求，补齐缺失项。

# 步骤

1. **查文档**：用 `bing-search` 搜索 `site:pro.arcgis.com $ARGUMENTS`，提取参数表（参数名、类型、是否必填、默认值）
2. **对比输入**：将文档参数与用户已提供的值逐项匹配
3. **补缺**：
   - 有默认值 → 直接使用
   - 需用户选择 → 提供 A/B/C 选项
   - 需用户输入 → 简短提问，避免开放式问题
4. **确认字段名**（当操作涉及新建/计算字段时）：
   - 合同声明了 `output_field_names` → 验证每个字段名与合同一致
   - 无合同 → 向用户确认将创建的字段名称
   - 引用技术规范时，核实规范规定的字段编码
5. **输出**：整理后的完整参数列表，准备执行
