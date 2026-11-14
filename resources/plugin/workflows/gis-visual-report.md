# GIS 可视化与报告 Workflow

> plan0701 约束：本模板仅适用于已有结果的后处理交付，不得作为完整复杂任务的第二个独立 Workflow。若任务从数据处理开始，制图与报告必须合并进同一个 `gis-standard-analysis` Workflow 的 Deliver 阶段。

> **委派规则**：可视化与出图任务（包括 color-style-mcp 专题图）必须委派给 `@gis-data-visualisation`，**禁止委派给 `@gis-tool`**。`@gis-tool` 没有 `color-style-mcp` 工具权限，误委派会报"MCP不可用"错误。

> 适用场景：用户已有分析结果数据，只需要生成可视化或报告，不涉及新的 GIS 工具执行。

## 流程图

```text
结果数据检查 → 可视化（如需要）→ 报告（如需要）→ 交付汇总
```

## 输入

- 已有的分析结果数据路径
- 用户对可视化/报告的具体要求

## 输出

- `03_Result/` 中的专题图（PNG/PDF）、报告（Word/MD）

## 子 Agent 调用关系

| Phase | Agent | 职责 |
|-------|-------|------|
| 可视化 | @gis-data-visualisation | GeoJSON 转换 + Leaflet 推送 + 可选 color-style MCP 出图 |
| 报告 | @report | officecli 生成 Word/MD 报告 |

## Workflow 参考脚本

> **使用说明**：`@task-plan` 调用时传入 `args: { dataPaths, needVisualization, needReport, reportType }`。

```javascript
export const meta = {
  name: 'gis-visual-report',
  description: 'GIS可视化与报告Workflow',
  whenToUse: '已有分析结果数据，只需生成可视化或报告，不涉及新的GIS工具执行',
  phases: [
    { title: 'Visualize', detail: '网页可视化' },
    { title: 'Report', detail: '报告生成' },
  ],
}

phase('Visualize')
if (args.needVisualization) {
  await agent('对以下数据生成网页可视化：' + JSON.stringify(args.dataPaths), {
    agentType: 'linktool-plugin:gis-data-visualisation', label: 'Visualize', phase: 'Visualize',
  })
  log('可视化完成')
}

phase('Report')
if (args.needReport) {
  await agent('基于分析结果生成' + args.reportType + '报告。', {
    agentType: 'linktool-plugin:report', label: 'Report', phase: 'Report',
  })
  log('报告完成')
}

return { summary: '可视化与报告Workflow完成' }
```

## 失败处理

- 可视化失败：向用户报告，仍可继续报告生成。
- 报告生成失败：向用户报告失败原因。
