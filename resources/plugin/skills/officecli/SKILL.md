---
name: officecli
description: Creates, inspects, validates, and edits Office files using the bundled officecli CLI.
agent: report
allowed_tools: [officecli]
---

# officecli

## 1. 使用场景

用于创建、检查、修改或验证 `.docx`、`.xlsx`、`.pptx` 文件。

在 `report` Agent 中常见用途：
- 将 Markdown 报告生成正式 DOCX。
- 创建统计表 XLSX。
- 校验已有 Office 文件结构、格式和内容。

## 2. 二进制路径与调用规则

OfficeCLI 已随插件内嵌：

- 首选：`./plugin/bin/officecli.exe`
- 自动定位：`uv run python ./plugin/skills/officecli/scripts/check_officecli.py`

规则：
- 在 Git Bash/MSYS 中处理 Windows 路径时，必要时加 `MSYS_NO_PATHCONV=1`。
- 所有输入输出文件必须位于 `02_WorkSpace/` 或 `03_Result/`。
- 不确定命令语法、属性名、元素路径或值格式时先运行 help，不要猜。

## 3. 执行策略

1. 读取/检查优先用 `view`、`get`、`query`。
2. 普通编辑优先用 `add`、`set`、`remove`。
3. 高层命令无法表达时才用 `raw` / `raw-set`。
4. 同一文件 3 条以上命令时使用 `open` / `close`。
5. 每个结构性操作后检查输出；失败立即停止修正。

常用层级：
- L1 读取：`view`、`get`、`query`、`validate`
- L2 DOM 编辑：`create`、`add`、`set`、`remove`、`move`、`batch`
- L3 原始 XML：`raw`、`raw-set`、`add-part`

## 4. Help 优先原则

不确定时先查 help：

```bash
officecli docx set
officecli docx set paragraph
officecli docx add
officecli xlsx set cell
officecli xlsx add
officecli <format> view
officecli <format> get
officecli <format> query
```

三层导航：
1. `officecli <format> <command>`：查看该命令可处理的元素。
2. `officecli <format> <command> <element>`：查看元素属性。
3. `officecli <format> <command> <element.property>`：查看属性格式和示例。

## 5. 常用命令速查

| 目的 | 命令 |
|---|---|
| 创建 | `officecli create <file>` |
| 驻留打开 | `officecli open <file>` |
| 保存关闭 | `officecli close <file>` |
| 查看结构 | `officecli view <file> outline` |
| 查看文本 | `officecli view <file> text --max-lines 200` |
| 查看问题 | `officecli view <file> issues` |
| 获取节点 | `officecli get <file> <path> --depth N --json` |
| 查询节点 | `officecli query <file> '<selector>'` |
| 添加元素 | `officecli add <file> <parent> --type <type> --prop key=value` |
| 设置属性 | `officecli set <file> <path> --prop key=value` |
| 删除元素 | `officecli remove <file> <path>` |
| 验证 | `officecli validate <file>` |

常用元素：
- DOCX：`paragraph`、`run`、`table`、`row`、`cell`、`image`、`header`、`footer`、`toc`、`pagebreak`。
- XLSX：`sheet`、`row`、`cell`、`chart`、`image`、`table`、`validation`、`autofilter`。

## 6. DOCX 报告工作流

1. `create` 新建文件。
2. `open` 驻留。
3. 设置页面、样式、页脚、封面。
4. 按 Markdown 结构添加标题、正文、表格、图片。
5. `close` 保存并释放文件句柄。
6. `validate`、`view outline`、`view issues`、`view text` 验证。

若需要 LinkTool 报告专用排版命令，按需读取：`plugin/skills/tool-report/formatting-guide.md`。

## 7. XLSX 表格工作流

1. `create` 新建文件。
2. 写入表头和数据。
3. 设置列宽、表头样式、数字格式。
4. 公式必须写公式，不要硬编码计算结果。
5. 添加冻结窗格、筛选或图表。
6. `validate`、`view issues`、抽样 `get` 验证。

## 8. 验证与交付

交付前至少执行：

- `officecli validate <file>`
- `officecli view <file> outline`
- `officecli view <file> issues`
- DOCX：必要时 `officecli view <file> text --max-lines 200`
- XLSX：抽查关键单元格、公式和图表来源

不能只因为文件生成成功就宣布完成。

## 9. 常见陷阱

| 错误 | 正确做法 |
|---|---|
| `--name "x"` | 用 `--prop name="x"` |
| 猜属性名 | 先运行 `officecli <format> set <element>` |
| 路径未加引号 | 引用 `"/body/p[1]"`、`"/Sheet1/A1"` |
| `#FF0000` | 颜色不用 `#`，写 `FF0000` |
| 用空段落做间距 | 用 `spaceBefore` / `spaceAfter` |
| Word/Excel 正打开文件 | 先关闭外部程序 |
| 修改后未 `close` | `open` 后必须 `close` 才落盘 |
| 生成后不验证 | 交付前必须 `validate` 和 `view issues` |

## 10. 按需参考

- DOCX 专项：`plugin/skills/officecli/skills/officecli-docx/SKILL.md`
- XLSX 专项：`plugin/skills/officecli/skills/officecli-xlsx/SKILL.md`
- LinkTool 报告 Word 排版：`plugin/skills/tool-report/formatting-guide.md`
