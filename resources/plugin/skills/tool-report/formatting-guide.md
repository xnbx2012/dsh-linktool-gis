# 地理信息分析过程报告 — Word 排版规范

本文件定义报告的全部排版规则及对应的 officecli 命令。生成文档时，直接使用本文件中的命令，无需额外调整参数。

> **注意**：所有 officecli 命令前必须加 `MSYS_NO_PATHCONV=1` 前缀，以保证在 MSYS/Git Bash 环境下路径不被错误转换。

---

## 1. 页面设置

| 项目 | 规格 | 数值（twips） | officecli 参数 |
|------|------|--------------|---------------|
| 纸张大小 | A4 | 21cm × 29.7cm | `pageWidth=11906 pageHeight=16838` |
| 上边距 | 2.54cm | 1440 | `marginTop=1440` |
| 下边距 | 2.54cm | 1440 | `marginBottom=1440` |
| 左边距 | 3.17cm | 1800 | `marginLeft=1800` |
| 右边距 | 3.17cm | 1800 | `marginRight=1800` |
| 默认字体 | 宋体 | — | `defaultFont="宋体"` |

**命令：**

```bash
MSYS_NO_PATHCONV=1 officecli set doc.docx / \
  --prop pageWidth=11906 --prop pageHeight=16838 \
  --prop marginTop=1440 --prop marginBottom=1440 \
  --prop marginLeft=1800 --prop marginRight=1800 \
  --prop defaultFont="宋体"
```

---

## 2. 标题样式定义

以下样式定义必须在添加任何正文内容**之前**执行。定义后，添加标题只需 `--prop style=Heading1`，无需重复设置格式。

### 2.1 一级标题（Heading 1）

| 属性 | 值 | 说明 |
|------|-----|------|
| 中文字体 | 黑体 | SimHei |
| 西文字体 | Times New Roman | 数字与英文 |
| 字号 | 三号 | 16pt |
| 加粗 | 是 | |
| 颜色 | 深蓝色 | 1F3864 |
| 对齐方式 | 左对齐 | |
| 段前间距 | 24pt | 标题前留白 |
| 段后间距 | 12pt | 标题后留白 |
| 行距 | 1.5 倍 | 固定倍率 |
| 与下段同页 | 是 | keepNext，防止标题与正文分离 |

**命令：**

```bash
MSYS_NO_PATHCONV=1 officecli add doc.docx /styles --type style \
  --prop name="Heading 1" --prop id=Heading1 --prop type=paragraph \
  --prop font="Times New Roman" --prop size=16pt \
  --prop bold=true --prop color=1F3864 \
  --prop alignment=left \
  --prop spaceBefore=24pt --prop spaceAfter=12pt \
  --prop lineSpacing=1.5x \
  --prop keepNext=true
```

### 2.2 二级标题（Heading 2）

| 属性 | 值 | 说明 |
|------|-----|------|
| 中文字体 | 黑体 | SimHei |
| 西文字体 | Times New Roman | |
| 字号 | 四号 | 14pt |
| 加粗 | 是 | |
| 颜色 | 深蓝色 | 2E4D87 |
| 对齐方式 | 左对齐 | |
| 段前间距 | 18pt | |
| 段后间距 | 6pt | |
| 行距 | 1.5 倍 | |
| 与下段同页 | 是 | keepNext |

**命令：**

```bash
MSYS_NO_PATHCONV=1 officecli add doc.docx /styles --type style \
  --prop name="Heading 2" --prop id=Heading2 --prop type=paragraph \
  --prop font="Times New Roman" --prop size=14pt \
  --prop bold=true --prop color=2E4D87 \
  --prop alignment=left \
  --prop spaceBefore=18pt --prop spaceAfter=6pt \
  --prop lineSpacing=1.5x \
  --prop keepNext=true
```

### 2.3 三级标题（Heading 3）

| 属性 | 值 | 说明 |
|------|-----|------|
| 中文字体 | 黑体 | SimHei |
| 西文字体 | Times New Roman | |
| 字号 | 小四号 | 12pt |
| 加粗 | 是 | |
| 颜色 | 深蓝色 | 3D5EA0 |
| 对齐方式 | 左对齐 | |
| 段前间距 | 12pt | |
| 段后间距 | 6pt | |
| 行距 | 1.5 倍 | |
| 与下段同页 | 是 | keepNext |

**命令：**

```bash
MSYS_NO_PATHCONV=1 officecli add doc.docx /styles --type style \
  --prop name="Heading 3" --prop id=Heading3 --prop type=paragraph \
  --prop font="Times New Roman" --prop size=12pt \
  --prop bold=true --prop color=3D5EA0 \
  --prop alignment=left \
  --prop spaceBefore=12pt --prop spaceAfter=6pt \
  --prop lineSpacing=1.5x \
  --prop keepNext=true
```

### 2.4 标题样式对比速查

| 样式 | 字体 | 字号 | 加粗 | 颜色 | 段前 | 段后 | 行距 |
|------|------|------|------|------|------|------|------|
| Heading 1 | 黑体 | 三号 16pt | 是 | 1F3864 深蓝 | 24pt | 12pt | 1.5 倍 |
| Heading 2 | 黑体 | 四号 14pt | 是 | 2E4D87 蓝 | 18pt | 6pt | 1.5 倍 |
| Heading 3 | 黑体 | 小四 12pt | 是 | 3D5EA0 浅蓝 | 12pt | 6pt | 1.5 倍 |

---

## 3. 正文排版

### 3.1 正文段落（首行缩进）

| 属性 | 值 | 说明 |
|------|-----|------|
| 中文字体 | 宋体 | SimSun |
| 西文字体 | Times New Roman | 数字与英文 |
| 字号 | 小四号 | 12pt |
| 颜色 | 黑色 | 333333 |
| 对齐方式 | 两端对齐 | justify |
| 首行缩进 | 2 字符 | 约 480 twips（12pt × 2） |
| 行距 | 1.5 倍 | |
| 段前间距 | 0pt | |
| 段后间距 | 8pt | 正文段后留白，与下一段落区分 |

**命令：**

```bash
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="此处为正文内容，首行自动缩进 2 字符。" \
  --prop font="Times New Roman" --prop size=12pt \
  --prop color=333333 \
  --prop alignment=justify \
  --prop firstLineIndent=480 \
  --prop spaceAfter=8pt \
  --prop lineSpacing=1.5x
```

### 3.2 无缩进段落（列表项、子项说明等）

与正文段落相同，但**无首行缩进**，且段后间距为 0：

```bash
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="- 任务目标：提取特定区域的土地利用类型" \
  --prop font="Times New Roman" --prop size=12pt \
  --prop color=333333 \
  --prop alignment=justify \
  --prop spaceAfter=0pt \
  --prop lineSpacing=1.5x
```

### 3.3 正文内加粗强调

在段落中插入加粗文本，使用 run：

```bash
# 先添加完整段落文本（普通格式）
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="使用 ArcGIS 的 Buffer 工具，设置缓冲距离为 500 米，目的是分析特定区域周边的要素分布情况，得到的缓冲区为 buffer_500m.shp。" \
  --prop font="Times New Roman" --prop size=12pt \
  --prop color=333333 \
  --prop alignment=justify \
  --prop firstLineIndent=480 \
  --prop spaceAfter=8pt \
  --prop lineSpacing=1.5x

# 然后格式化特定文本为加粗
MSYS_NO_PATHCONV=1 officecli set doc.docx "/body/p[current]" \
  --prop find="Buffer" --prop bold=true --prop color=1F3864
```

---

## 4. 图片与图注

### 4.1 图片

| 属性 | 值 | 说明 |
|------|-----|------|
| 宽度 | 15cm | 约页面内容区 85% |
| 对齐 | 居中 | 通过段落 alignment 控制 |
| 与上文间距 | 12pt | |
| 替代文本 | 图片内容描述 | alt text |

**命令：**

```bash
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type picture \
  --prop src="C:/path/to/image.png" \
  --prop width=15cm \
  --prop alt="缓冲区分析结果示意图"
```

### 4.2 图注

| 属性 | 值 | 说明 |
|------|-----|------|
| 中文字体 | 宋体 | SimSun |
| 西文字体 | Times New Roman | |
| 字号 | 五号 | 10pt |
| 颜色 | 灰色 | 666666 |
| 斜体 | 是 | |
| 对齐方式 | 居中 | |
| 段前间距 | 6pt | 与图片间距 |
| 段后间距 | 18pt | 与正文间距（图片后留大空白更美观） |
| 行距 | 1.5 倍 | |
| 编号规则 | "图 N: 描述" | N 从 1 开始连续编号 |

**命令：**

```bash
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="图 1: 某区域 500 米缓冲区分析结果" \
  --prop font="Times New Roman" --prop size=10pt \
  --prop italic=true --prop color=666666 \
  --prop alignment=center \
  --prop spaceBefore=6pt --prop spaceAfter=18pt \
  --prop lineSpacing=1.5x
```

### 4.3 图片 + 图注组合命令

```bash
# 插入图片（图片前添加空白段落产生间距）
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph --prop text="" --prop spaceBefore=12pt --prop spaceAfter=0pt

MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type picture \
  --prop src="C:/path/to/image.png" \
  --prop width=15cm \
  --prop alt="分析结果示意图"

# 紧接图注
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="图 1: 某区域 500 米缓冲区分析结果" \
  --prop font="Times New Roman" --prop size=10pt \
  --prop italic=true --prop color=666666 \
  --prop alignment=center \
  --prop spaceBefore=6pt --prop spaceAfter=18pt \
  --prop lineSpacing=1.5x
```

---

## 5. 表格排版

### 5.1 表格整体

| 属性 | 值 | 说明 |
|------|-----|------|
| 宽度 | 100% | 页面内容区满宽 |
| 边框 | 外框深蓝，内线浅灰 | |
| 表格样式 | TableGrid | officecli 内置 |

**创建表格命令（以 5 列为例）：**

```bash
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type table \
  --prop rows=4 --prop cols=5 \
  --prop width="100%" --prop style=TableGrid

MSYS_NO_PATHCONV=1 officecli set doc.docx "/body/tbl[1]" \
  --prop border.top="single;8;1F3864;0" \
  --prop border.bottom="single;8;1F3864;0" \
  --prop border.left="single;8;1F3864;0" \
  --prop border.right="single;8;1F3864;0" \
  --prop border.insideH="single;4;CCCCCC;0" \
  --prop border.insideV="single;4;CCCCCC;0"
```

### 5.2 表头行

| 属性 | 值 | 说明 |
|------|-----|------|
| 中文字体 | 黑体 | SimHei |
| 西文字体 | Times New Roman | |
| 字号 | 小四号 | 12pt |
| 加粗 | 是 | |
| 颜色 | 白色 | FFFFFF |
| 对齐 | 居中 | |
| 背景色 | 深蓝 | 1F3864 |
| 单元格内边距 | 上下 50 左右 100 | twips |

**表头设置命令（5 列表头）：**

> **重要**：必须使用 `tc[N]` 路径逐单元格设置文本和格式。**禁止**使用 `--prop c1="..." c2="..."` 简写方式，该方式会在已有单元格中新增空单元格，导致表格列数翻倍。

```bash
# 逐个设置表头单元格文本 + 格式（每条命令同时写文字和样式）
MSYS_NO_PATHCONV=1 officecli set doc.docx "/body/tbl[1]/tr[1]/tc[1]" \
  --prop text="数据项" \
  --prop bold=true --prop font="Times New Roman" --prop size=12pt \
  --prop color=FFFFFF --prop alignment=center \
  --prop shd=1F3864 \
  --prop padding.top=50 --prop padding.bottom=50 \
  --prop padding.left=100 --prop padding.right=100

MSYS_NO_PATHCONV=1 officecli set doc.docx "/body/tbl[1]/tr[1]/tc[2]" \
  --prop text="路径" \
  --prop bold=true --prop font="Times New Roman" --prop size=12pt \
  --prop color=FFFFFF --prop alignment=center \
  --prop shd=1F3864 \
  --prop padding.top=50 --prop padding.bottom=50 \
  --prop padding.left=100 --prop padding.right=100

MSYS_NO_PATHCONV=1 officecli set doc.docx "/body/tbl[1]/tr[1]/tc[3]" \
  --prop text="坐标系 (WKID)" \
  --prop bold=true --prop font="Times New Roman" --prop size=12pt \
  --prop color=FFFFFF --prop alignment=center \
  --prop shd=1F3864 \
  --prop padding.top=50 --prop padding.bottom=50 \
  --prop padding.left=100 --prop padding.right=100

MSYS_NO_PATHCONV=1 officecli set doc.docx "/body/tbl[1]/tr[1]/tc[4]" \
  --prop text="要素类型" \
  --prop bold=true --prop font="Times New Roman" --prop size=12pt \
  --prop color=FFFFFF --prop alignment=center \
  --prop shd=1F3864 \
  --prop padding.top=50 --prop padding.bottom=50 \
  --prop padding.left=100 --prop padding.right=100

MSYS_NO_PATHCONV=1 officecli set doc.docx "/body/tbl[1]/tr[1]/tc[5]" \
  --prop text="关键字段" \
  --prop bold=true --prop font="Times New Roman" --prop size=12pt \
  --prop color=FFFFFF --prop alignment=center \
  --prop shd=1F3864 \
  --prop padding.top=50 --prop padding.bottom=50 \
  --prop padding.left=100 --prop padding.right=100
```

### 5.3 数据行（斑马纹样式）

| 属性 | 值 | 说明 |
|------|-----|------|
| 中文字体 | 宋体 | SimSun |
| 西文字体 | Times New Roman | |
| 字号 | 五号 | 10.5pt |
| 颜色 | 黑色 | 333333 |
| 对齐 | 居中（路径列左对齐） | |
| 单元格内边距 | 上下 40 左右 100 | twips |
| 斑马纹 | 奇数行白色，偶数行浅蓝灰 | FFFFFF / F2F7FF |

**数据行设置命令：**

> **重要**：同样使用 `tc[N]` 路径逐单元格设置。**禁止**使用 `--prop c1="..." c2="..."`。

```bash
# 填充并格式化第一行数据（白色背景）
MSYS_NO_PATHCONV=1 officecli set doc.docx "/body/tbl[1]/tr[2]/tc[1]" \
  --prop text="土地利用图层" \
  --prop font="Times New Roman" --prop size=10.5pt \
  --prop color=333333 --prop alignment=center \
  --prop shd=FFFFFF \
  --prop padding.top=40 --prop padding.bottom=40 \
  --prop padding.left=100 --prop padding.right=100

MSYS_NO_PATHCONV=1 officecli set doc.docx "/body/tbl[1]/tr[2]/tc[2]" \
  --prop text="/data/landuse.shp" \
  --prop font="Times New Roman" --prop size=10.5pt \
  --prop color=333333 --prop alignment=left \
  --prop shd=FFFFFF \
  --prop padding.top=40 --prop padding.bottom=40 \
  --prop padding.left=100 --prop padding.right=100

MSYS_NO_PATHCONV=1 officecli set doc.docx "/body/tbl[1]/tr[2]/tc[3]" \
  --prop text="CGCS2000 (4490)" \
  --prop font="Times New Roman" --prop size=10.5pt \
  --prop color=333333 --prop alignment=center \
  --prop shd=FFFFFF \
  --prop padding.top=40 --prop padding.bottom=40 \
  --prop padding.left=100 --prop padding.right=100

MSYS_NO_PATHCONV=1 officecli set doc.docx "/body/tbl[1]/tr[2]/tc[4]" \
  --prop text="Polygon" \
  --prop font="Times New Roman" --prop size=10.5pt \
  --prop color=333333 --prop alignment=center \
  --prop shd=FFFFFF \
  --prop padding.top=40 --prop padding.bottom=40 \
  --prop padding.left=100 --prop padding.right=100

MSYS_NO_PATHCONV=1 officecli set doc.docx "/body/tbl[1]/tr[2]/tc[5]" \
  --prop text="type, area" \
  --prop font="Times New Roman" --prop size=10.5pt \
  --prop color=333333 --prop alignment=center \
  --prop shd=FFFFFF \
  --prop padding.top=40 --prop padding.bottom=40 \
  --prop padding.left=100 --prop padding.right=100

# 第二行（浅蓝斑马纹 F2F7FF）— 命令结构相同，仅 shd 和 text 不同
MSYS_NO_PATHCONV=1 officecli set doc.docx "/body/tbl[1]/tr[3]/tc[1]" \
  --prop text="道路网络" \
  --prop font="Times New Roman" --prop size=10.5pt \
  --prop color=333333 --prop alignment=center \
  --prop shd=F2F7FF \
  --prop padding.top=40 --prop padding.bottom=40 \
  --prop padding.left=100 --prop padding.right=100
# ... tc[2] ~ tc[5] 同理
```

### 5.4 表格索引与多表格注意事项

**表格索引规则**：
- 第一个表格为 `tbl[1]`，第二个为 `tbl[2]`，以此类推
- **添加新内容前必须确认当前表格索引**，避免操作错误的表格
- 建议每添加一个表格后，在待办清单中记录该表格的索引编号

**添加新行**：创建表格时如果行数不够，使用 `--type row` 添加新行，然后用 `tc[N]` 逐单元格设置内容：

```bash
# 添加新行（仅添加空行，不填充内容）
MSYS_NO_PATHCONV=1 officecli add doc.docx "/body/tbl[1]" --type row

# 然后用 tc[N] 逐单元格设置文本和格式（与 5.3 节数据行格式一致）
MSYS_NO_PATHCONV=1 officecli set doc.docx "/body/tbl[1]/tr[3]/tc[1]" \
  --prop text="道路网络" \
  --prop font="Times New Roman" --prop size=10.5pt \
  --prop color=333333 --prop alignment=center \
  --prop shd=F2F7FF \
  --prop padding.top=40 --prop padding.bottom=40 \
  --prop padding.left=100 --prop padding.right=100

MSYS_NO_PATHCONV=1 officecli set doc.docx "/body/tbl[1]/tr[3]/tc[2]" \
  --prop text="/data/roads.shp" \
  --prop font="Times New Roman" --prop size=10.5pt \
  --prop color=333333 --prop alignment=left \
  --prop shd=F2F7FF \
  --prop padding.top=40 --prop padding.bottom=40 \
  --prop padding.left=100 --prop padding.right=100

# tc[3] ~ tc[5] 同理...
```

---

## 6. 页脚

### 6.1 页脚（页码）

| 属性 | 值 |
|------|-----|
| 格式 | 第 X 页 |
| 首页 | 空白（封面不需要页码） |
| 字体 | 宋体 |
| 字号 | 五号 10.5pt |
| 颜色 | 灰色 999999 |
| 对齐 | 居中 |

```bash
# 步骤 1：首页空白页脚
MSYS_NO_PATHCONV=1 officecli add doc.docx / --type footer --prop type=first --prop text=""

# 步骤 2：默认页脚，"第 " + 页码 + " 页"
MSYS_NO_PATHCONV=1 officecli add doc.docx / --type footer \
  --prop text="第 " --prop type=default \
  --prop alignment=center --prop size=10.5pt --prop font="宋体" --prop color=999999

# 步骤 3：添加页码字段
MSYS_NO_PATHCONV=1 officecli add doc.docx /footer[2]/p[1] --type pagenum

# 步骤 4：添加" 页"文本
MSYS_NO_PATHCONV=1 officecli add doc.docx /footer[2]/p[1] --type run \
  --prop text=" 页" --prop size=10.5pt --prop font="宋体" --prop color=999999
```

---

## 7. 封面页

### 7.1 封面设计原则

封面应简洁大方，突出报告标题。使用深蓝色系体现专业性。

### 7.2 封面内容规则

| 元素 | 字体 | 字号 | 加粗 | 颜色 | 对齐 | 说明 |
|------|------|------|------|------|------|------|
| 顶部装饰色条 | — | — | — | 1F3864 | — | 顶部装饰线，高度 8pt |
| 上间距 | — | — | — | — | — | 约 80pt |
| 报告主标题 | 黑体 | 二号 22pt | 是 | 1F3864 | 居中 | 地理信息分析过程报告 |
| 副标题/任务ID | 宋体 | 三号 16pt | 否 | 555555 | 居中 | Mission ID |
| 装饰分隔线 | — | — | — | BFBFBF | — | 细线，1pt |
| 编制信息区 | — | — | — | — | — | 包含单位、日期 |
| 编制单位 | 宋体 | 小四 12pt | 否 | 666666 | 居中 | LinkTool 自动化地理信息分析平台 |
| 编制日期 | 宋体 | 小四 12pt | 否 | 666666 | 居中 | YYYY-MM-DD |
| 底部装饰色条 | — | — | — | 1F3864 | — | 底部装饰线，高度 8pt |

### 7.3 封面页命令

```bash
# ─── 封面页 ────────────────────────────────────────────────────────

# 顶部深蓝色装饰条
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="" --prop shd=1F3864 \
  --prop spaceBefore=0pt --prop spaceAfter=0pt --prop size=8pt

# 上间距（创造视觉空白）
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="" --prop spaceBefore=80pt --prop spaceAfter=0pt

# 报告主标题
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="地理信息分析过程报告" \
  --prop font="黑体" --prop size=22pt \
  --prop bold=true --prop color=1F3864 \
  --prop alignment=center --prop spaceAfter=16pt

# 副标题（Mission ID）
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="Mission ID: GIS-2026-001" \
  --prop font="宋体" --prop size=16pt \
  --prop color=555555 \
  --prop alignment=center --prop spaceAfter=40pt

# 分隔线
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="" --prop border.bottom="single;1;BFBFBF;0" \
  --prop spaceBefore=0pt --prop spaceAfter=40pt

# 编制单位
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="LinkTool 自动化地理信息分析平台" \
  --prop font="宋体" --prop size=12pt \
  --prop color=666666 \
  --prop alignment=center --prop spaceAfter=12pt

# 编制日期
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="2026-04-24" \
  --prop font="宋体" --prop size=12pt \
  --prop color=666666 \
  --prop alignment=center --prop spaceAfter=80pt

# 底部深蓝色装饰条
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="" --prop shd=1F3864 \
  --prop size=8pt --prop spaceBefore=0pt --prop spaceAfter=0pt

# 分页符（封面结束）
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type pagebreak
```

---

## 8. 目录（TOC）

### 8.1 目录设置

| 属性 | 值 |
|------|-----|
| 标题 | 目录 |
| 样式 | Heading1 样式的深蓝色 |
| 前导点 | 是 |
| 制表符前导 | 是 |

```bash
# 目录标题
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="目录" \
  --prop style=Heading1

# 添加 TOC 字段
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="" \
  --prop alignment=center
```

### 8.2 手动目录（在 officecli TOC 功能有限时）

建议在文档生成后，由用户在 Word/WPS 中自动更新目录域。如需手动创建目录结构，可按以下方式：

```bash
# 目录项示例（使用 Tab 字符连接标题和页码）
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="1. 任务概述" \
  --prop font="宋体" --prop size=12pt \
  --prop color=333333 \
  --prop spaceAfter=6pt \
  --prop lineSpacing=1.5x

MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="2. 数据准备与环境" \
  --prop font="宋体" --prop size=12pt \
  --prop color=333333 \
  --prop spaceAfter=6pt \
  --prop lineSpacing=1.5x

# ... 其他目录项
```

---

## 9. 完整文档初始化命令序列

以下命令按顺序执行，完成从创建到初始化的全部准备工作。后续只需按内容结构添加段落、表格和图片。

```bash
# ════════════════════════════════════════════════════════════════════
# 地理信息分析过程报告 — 文档初始化序列
# 执行顺序：1. 创建 → 2. 删除默认段落 → 3. 页面设置 → 4. 样式定义 → 5. 页脚 → 6. 封面
# ════════════════════════════════════════════════════════════════════

# ─── 1. 创建 & 打开 ────────────────────────────────────────────────
MSYS_NO_PATHCONV=1 officecli create doc.docx
MSYS_NO_PATHCONV=1 officecli open doc.docx

# ─── 1b. 删除默认空段落（防止生成空白首页）─────────────────────────────
MSYS_NO_PATHCONV=1 officecli remove doc.docx '/body/p[1]'

# ─── 2. 页面设置 ────────────────────────────────────────────────────
MSYS_NO_PATHCONV=1 officecli set doc.docx / \
  --prop pageWidth=11906 --prop pageHeight=16838 \
  --prop marginTop=1440 --prop marginBottom=1440 \
  --prop marginLeft=1800 --prop marginRight=1800 \
  --prop defaultFont="宋体"

# ─── 3. 标题样式定义 ────────────────────────────────────────────────
# Heading 1 — 黑体 三号 16pt 加粗 深蓝色 1F3864
MSYS_NO_PATHCONV=1 officecli add doc.docx /styles --type style \
  --prop name="Heading 1" --prop id=Heading1 --prop type=paragraph \
  --prop font="Times New Roman" --prop size=16pt \
  --prop bold=true --prop color=1F3864 \
  --prop alignment=left \
  --prop spaceBefore=24pt --prop spaceAfter=12pt \
  --prop lineSpacing=1.5x \
  --prop keepNext=true

# Heading 2 — 黑体 四号 14pt 加粗 深蓝色 2E4D87
MSYS_NO_PATHCONV=1 officecli add doc.docx /styles --type style \
  --prop name="Heading 2" --prop id=Heading2 --prop type=paragraph \
  --prop font="Times New Roman" --prop size=14pt \
  --prop bold=true --prop color=2E4D87 \
  --prop alignment=left \
  --prop spaceBefore=18pt --prop spaceAfter=6pt \
  --prop lineSpacing=1.5x \
  --prop keepNext=true

# Heading 3 — 黑体 小四 12pt 加粗 浅蓝色 3D5EA0
MSYS_NO_PATHCONV=1 officecli add doc.docx /styles --type style \
  --prop name="Heading 3" --prop id=Heading3 --prop type=paragraph \
  --prop font="Times New Roman" --prop size=12pt \
  --prop bold=true --prop color=3D5EA0 \
  --prop alignment=left \
  --prop spaceBefore=12pt --prop spaceAfter=6pt \
  --prop lineSpacing=1.5x \
  --prop keepNext=true

# ─── 4. 页脚设置 ────────────────────────────────────────────────────
# 5a. 首页空白页脚（封面不需要页码）
MSYS_NO_PATHCONV=1 officecli add doc.docx / --type footer --prop type=first --prop text=""

# 5b. 默认页脚（第 X 页）
MSYS_NO_PATHCONV=1 officecli add doc.docx / --type footer \
  --prop text="第 " --prop type=default \
  --prop alignment=center --prop size=10.5pt --prop font="宋体" --prop color=999999

# 5c. 添加页码字段
MSYS_NO_PATHCONV=1 officecli add doc.docx /footer[2]/p[1] --type pagenum

# 5d. 添加" 页"文本
MSYS_NO_PATHCONV=1 officecli add doc.docx /footer[2]/p[1] --type run \
  --prop text=" 页" --prop size=10.5pt --prop font="宋体" --prop color=999999

# ─── 5. 封面页 ──────────────────────────────────────────────────────
# 5a. 顶部深蓝色装饰条
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="" --prop shd=1F3864 \
  --prop spaceBefore=0pt --prop spaceAfter=0pt --prop size=8pt

# 5b. 上间距
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="" --prop spaceBefore=80pt --prop spaceAfter=0pt

# 5c. 报告主标题
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="地理信息分析过程报告" \
  --prop font="黑体" --prop size=22pt \
  --prop bold=true --prop color=1F3864 \
  --prop alignment=center --prop spaceAfter=16pt

# 5d. 副标题（Mission ID）
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="Mission ID: GIS-2026-001" \
  --prop font="宋体" --prop size=16pt \
  --prop color=555555 \
  --prop alignment=center --prop spaceAfter=40pt

# 5e. 分隔线
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="" --prop border.bottom="single;1;BFBFBF;0" \
  --prop spaceBefore=0pt --prop spaceAfter=40pt

# 5f. 编制单位
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="LinkTool 自动化地理信息分析平台" \
  --prop font="宋体" --prop size=12pt \
  --prop color=666666 \
  --prop alignment=center --prop spaceAfter=12pt

# 5g. 编制日期
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="2026-04-24" \
  --prop font="宋体" --prop size=12pt \
  --prop color=666666 \
  --prop alignment=center --prop spaceAfter=80pt

# 5h. 底部深蓝色装饰条
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="" --prop shd=1F3864 \
  --prop size=8pt --prop spaceBefore=0pt --prop spaceAfter=0pt

# 5i. 分页符（封面结束）
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type pagebreak

# ════════════════════════════════════════════════════════════════════
# 初始化完成 — 后续按报告内容结构添加标题、正文、表格、图片
# ════════════════════════════════════════════════════════════════════
```

---

## 10. 内容添加命令模板

初始化完成后，使用以下模板按内容结构添加正文。

### 10.1 一级标题（使用样式）

```bash
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="1. 任务概述" \
  --prop style=Heading1
```

### 10.2 二级标题（使用样式）

```bash
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="3.1 分析目的" \
  --prop style=Heading2
```

### 10.3 三级标题（使用样式）

```bash
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="3.1.1 Step 1: 缓冲区分析" \
  --prop style=Heading3
```

### 10.4 正文段落（首行缩进 + 段后间距）

**重要**：正文段落必须设置首行缩进 480 twips（2字符）和段后间距 8pt，否则会有格式问题。

```bash
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="使用 ArcGIS 的 Buffer 工具，设置缓冲距离为 500 米，目的是分析特定区域周边的要素分布情况，得到的缓冲区为 buffer_500m.shp。" \
  --prop font="Times New Roman" --prop size=12pt \
  --prop color=333333 \
  --prop alignment=justify \
  --prop firstLineIndent=480 \
  --prop spaceAfter=8pt \
  --prop lineSpacing=1.5x
```

### 10.5 无缩进段落（列表项、子项说明）

```bash
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="- 任务目标：提取特定区域的土地利用类型" \
  --prop font="Times New Roman" --prop size=12pt \
  --prop color=333333 \
  --prop alignment=justify \
  --prop spaceAfter=0pt \
  --prop lineSpacing=1.5x
```

### 10.6 关键词加粗

在正文段落添加后，使用 `find` 属性格式化关键词：

```bash
# 先添加完整段落
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="使用 ArcGIS 的 Buffer 工具，设置缓冲距离为 500 米。" \
  --prop font="Times New Roman" --prop size=12pt \
  --prop color=333333 \
  --prop alignment=justify \
  --prop firstLineIndent=480 \
  --prop spaceAfter=8pt \
  --prop lineSpacing=1.5x

# 格式化工具名称为加粗深蓝色
MSYS_NO_PATHCONV=1 officecli set doc.docx "/body/p[current]" \
  --prop find="Buffer" --prop bold=true --prop color=1F3864
```

### 10.7 图片 + 图注

```bash
# 图片前间距段落
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="" --prop spaceBefore=12pt --prop spaceAfter=0pt

# 图片
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type picture \
  --prop src="C:/path/to/buffer_result.png" \
  --prop width=15cm \
  --prop alt="缓冲区分析结果"

# 图注
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="图 1: 某区域 500 米缓冲区分析结果" \
  --prop font="Times New Roman" --prop size=10pt \
  --prop italic=true --prop color=666666 \
  --prop alignment=center \
  --prop spaceBefore=6pt --prop spaceAfter=18pt \
  --prop lineSpacing=1.5x
```

### 10.8 完整步骤段落（标题 + 正文 + 图片 + 图注）

```bash
# 三级标题
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="3.1.1 Step 1: 缓冲区分析" \
  --prop style=Heading3

# 正文描述（必须设置首行缩进！）
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="使用 ArcGIS 的 Buffer 工具，设置缓冲距离为 500 米，目的是分析特定区域周边的要素分布情况，得到的缓冲区为 buffer_500m.shp。" \
  --prop font="Times New Roman" --prop size=12pt \
  --prop color=333333 \
  --prop alignment=justify \
  --prop firstLineIndent=480 \
  --prop spaceAfter=8pt \
  --prop lineSpacing=1.5x

# 格式化关键词
MSYS_NO_PATHCONV=1 officecli set doc.docx "/body/p[current]" \
  --prop find="Buffer" --prop bold=true --prop color=1F3864

# 图片前间距
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="" --prop spaceBefore=12pt --prop spaceAfter=0pt

# 图片
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type picture \
  --prop src="C:/path/to/buffer_result.png" \
  --prop width=15cm \
  --prop alt="缓冲区分析结果"

# 图注
MSYS_NO_PATHCONV=1 officecli add doc.docx /body --type paragraph \
  --prop text="图 1: 某区域 500 米缓冲区分析结果" \
  --prop font="Times New Roman" --prop size=10pt \
  --prop italic=true --prop color=666666 \
  --prop alignment=center \
  --prop spaceBefore=6pt --prop spaceAfter=18pt \
  --prop lineSpacing=1.5x
```

---

## 11. 文档收尾

### 11.1 保存关闭（必须优先执行）

```bash
MSYS_NO_PATHCONV=1 officecli close doc.docx
```

> **重要**：`officecli create` 默认以后台驻留模式打开文件。必须先执行 `close` 释放文件句柄，再进行后续验证。若遗漏 `close`，officecli 后台进程会持续占用文档，导致其他程序无法打开。

### 11.2 验证

```bash
MSYS_NO_PATHCONV=1 officecli validate doc.docx
MSYS_NO_PATHCONV=1 officecli view doc.docx outline
MSYS_NO_PATHCONV=1 officecli view doc.docx issues --type format
```

---

## 12. 常见问题排查

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 正文无首行缩进 | 缺少 `firstLineIndent=480` | 添加该属性 |
| 段落间距不均匀 | 未设置 `spaceAfter` | 正文段落设置 `spaceAfter=8pt` |
| 表格无边框 | 未设置 border 属性 | 设置 `border.top/bottom/left/right="single;8;1F3864;0"` |
| 表头不是深蓝色 | 单元格未设置 `shd=1F3864` | 为表头所有单元格设置背景色 |
| **表格列数翻倍** | **使用了 `--prop c1= c2=` 简写填充已有表格** | **改用 `tc[N]` 路径逐单元格 `--prop text="..."` 设置，添加新行后也必须用 `tc[N]` 填充** |
| **操作了错误的表格** | **多表格场景下 `tbl[N]` 索引搞混** | **每添加一个表格后记录索引编号，操作前确认索引** |
| 表头内容为空 | 单元格只设置了格式没设文字 | 使用 `tc[N]` 路径同时设置 `--prop text="标题" --prop shd=...` |
| 图片显示异常 | 路径不是绝对路径 | 使用 `C:/path/to/image.png` |
| 标题层级不清晰 | 颜色区分不明显 | Heading1/2/3 使用深蓝系渐变色 |
| 文档第一页空白 | `create` 后默认空段落未删除 | 在 `open` 后立即执行 `remove doc.docx '/body/p[1]'` |
| 无页码 | 页脚未正确设置 | 检查 footer type=first 和 type=default |

---

## 13. 格式规范速查表

| 元素 | 字体 | 字号 | 颜色 | 特殊格式 |
|------|------|------|------|----------|
| 封面标题 | 黑体 | 22pt | 1F3864 | 加粗，居中 |
| 封面副标题 | 宋体 | 16pt | 555555 | 居中 |
| 封面信息 | 宋体 | 12pt | 666666 | 居中 |
| H1 一级标题 | 黑体 | 16pt | 1F3864 | 加粗，段前24pt段后12pt |
| H2 二级标题 | 黑体 | 14pt | 2E4D87 | 加粗，段前18pt段后6pt |
| H3 三级标题 | 黑体 | 12pt | 3D5EA0 | 加粗，段前12pt段后6pt |
| 正文段落 | 宋体 | 12pt | 333333 | 首行缩进2字符，段后8pt |
| 无缩进段落 | 宋体 | 12pt | 333333 | 无缩进 |
| 关键词加粗 | 宋体 | 12pt | 1F3864 | 加粗（与正文区分） |
| 图片 | — | — | — | 宽度15cm，居中 |
| 图注 | 宋体 | 10pt | 666666 | 斜体，居中 |
| 表头 | 黑体 | 12pt | FFFFFF | 加粗，居中，深蓝背景 |
| 表格数据 | 宋体 | 10.5pt | 333333 | 居中，斑马纹 |
| 页码 | 宋体 | 10.5pt | 999999 | 居中 |
| 封面装饰条 | — | 8pt | 1F3864 | 顶部/底部 |
