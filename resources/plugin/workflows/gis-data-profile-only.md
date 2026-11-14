# GIS 数据画像 Workflow

> plan0701 约束：本模板仅限数据摸底/画像，不执行主体 GIS 分析、制图或报告；不得被串联为完整复杂任务的第一段短 Workflow。

> 适用场景：用户仅需要了解数据情况，如数据有哪些图层、字段、坐标系、空间范围，或需要生成数据画像报告，不涉及 GIS 分析执行。

## 流程图

```text
工作空间检查 → 数据实体提取 → 元数据检索 → 数据画像生成 → 报告保存
```

## 输入

- 用户自然语言数据理解需求
- `01_DataBackup/` 中的原始数据

## 输出

- `02_WorkSpace/data_profile.md`：结构化数据画像报告

## 子 Agent 调用关系

| Phase | Agent | 职责 |
|-------|-------|------|
| 数据实体提取 | @data-retrieval | 分析需求文本，识别数据库、表名、字段名、业务术语 |
| 元数据检索 | @data-retrieval | 调用 list_gdb_contents / get_data_properties / query_feature_attributes |
| 知识库辅助 | @data-retrieval | 调用 search_knowledge 获取类似 GIS 案例 |
| 数据画像生成 | @data-retrieval | 整合元数据，输出结构化报告 |

## Workflow 参考脚本

> **使用说明**：`@task-plan` 调用时传入 `args: { userRequirement }`。

```javascript
export const meta = {
  name: 'gis-data-profile',
  description: 'GIS数据画像Workflow',
  whenToUse: '仅需要了解数据情况（图层、字段、坐标系、空间范围），不涉及GIS分析执行',
  phases: [
    { title: 'Profile', detail: '数据实体提取与元数据检索' },
  ],
}

phase('Profile')
const profile = await agent(
  '从用户需求中提取数据实体，检索元数据，生成数据画像报告，保存至 02_WorkSpace/data_profile.md。用户需求：' + args.userRequirement,
  { agentType: 'linktool-plugin:data-retrieval', label: 'DataProfile', phase: 'Profile' }
)
log('数据画像完成')
return profile
```

## 失败处理

- 数据画像失败：向用户报告失败原因和建议。
