# 任务数据筛选与清单生成

> 本文件是 `task-data-manage` Skill 的功能模块，负责根据任务类型筛选所需数据并形成标准化清单。

## 0. 功能定位

**输入**：任务类型、分析对象、分析范围（由 task-plan 的 2.4 Interpret Task Requirements 步骤提供）

**输出**：写入 `02_WorkSpace/task_plan.md` 的 `## Data Inventory` 小节

**执行时机**：任务解释之后，参考资料推理之前

## 1. 筛选流程

```
Step 1: 接收任务类型和分析对象
Step 2: 根据任务类型推导所需数据角色
Step 3: 扫描 01_DataBackup/ → 获取所有可用数据文件
Step 4: 获取每个数据的属性 → 调用 get_data_properties / list_gdb_contents
Step 5: 语义匹配 → 将可用数据与所需角色进行匹配
Step 6: 形成数据清单 → 按标准格式写入 task_plan.md
```

## 2. 筛选标准

### 2.1 确定所需数据角色

根据任务类型和用户需求，推导出本任务所需的**数据角色**（例如“耕地图斑”“地形数据”“约束因子图层”等）。数据角色是数据功能的抽象描述，不是具体文件名。

### 2.2 扫描可用数据

- 使用 `Glob` 扫描 `01_DataBackup/` 下所有 `.shp`、`.tif`、`.adf`、`.img` 文件
- 使用 `list_gdb_contents` 获取 `.gdb` 文件中的所有内部要素类和栅格数据集
- 对每个数据调用 `get_data_properties` 获取元数据

### 2.3 语义匹配

将每个可用数据项与所需数据角色进行匹配。匹配标准按优先级排序：

1. **文件名/要素类名称**：是否包含角色关键词（例如“Road”匹配道路网络角色）
2. **几何类型**：是否符合该角色所需的几何类型（例如“Road network”应为 Polyline）
3. **字段列表**：是否包含该角色的关键字段（例如“Farmland parcels”应包含 DLBM）
4. **空间范围**：是否覆盖用户指定的分析范围

匹配结果分为三类：
- **Matched**：数据角色有对应数据，属性基本符合
- **Dubious**：数据名称或属性存在歧义，需要进一步确认（交给 data-doubt-check Skill）
- **Missing**：没有任何数据能匹配该角色

## 3. 数据清单标准格式

### 3.1 清单结构

```markdown
## Data Inventory

> Task Type: [task type]
> Analysis Object: [analysis object]
> Analysis Scope: [analysis scope]
> Generated: [YYYY-MM-DD HH:mm]

---

### Matched Data

| No. | Data Name | Full Path | Format | CRS | WKID | Geometry | Count | Matched Role | Match Basis |
|-----|-----------|-----------|--------|-----|------|----------|-------|-------------|-------------|
| 1 | ... | ... | ... | ... | ... | ... | ... | ... | ... |

### Dubious Data

| No. | Data Name | Full Path | Reason | Needs Confirmation |
|-----|-----------|-----------|--------|-------------------|
| 1 | ... | ... | ... | ... |

### Missing Data

| No. | Required Role | Role Description | Required/Recommended | Suggested Action |
|-----|--------------|-----------------|---------------------|-----------------|
| 1 | ... | ... | ... | ... |
```

### 3.2 字段说明

| Field | Specification |
|-------|--------------|
| Data Name | 要素类名称或文件名，不含路径和扩展名 |
| Full Path | 从 `01_DataBackup/` 开始的完整路径 |
| Format | Shapefile / GDB FeatureClass / GeoTIFF / ESRI Grid / Table |
| CRS | 完整 CRS 名称，例如 `CGCS2000_3_Degree_GK_Zone_39`，不要使用缩写 |
| WKID | EPSG 代码数字，未知时填 `Unknown` |
| Geometry | Point / Polyline / Polygon / Multipoint / Raster / Table |
| Count | 整数；栅格使用 `1024x1024` 之类的维度；表使用记录数 |
| Matched Role | 需求中对应的数据角色名称 |
| Match Basis | 说明匹配依据是文件名、几何类型还是字段列表 |
| Reason | 引用 SKILL.md 中存疑数据标准编号，例如 1.1、1.3 |
| Needs Confirmation | 需要属性表检查或用户询问的具体项 |
| Suggested Action | “Ask user” / “Use alternative data” / “Skip this factor” |

## 4. 格式示例

### 示例 1：选址分析（垃圾转运站）

```markdown
## Data Inventory

> Task Type: Site Selection Analysis
> Analysis Object: Waste Transfer Station
> Analysis Scope: Entire XX City
> Generated: 2025-01-15 10:30

---

### Matched Data

| No. | Data Name | Full Path | Format | CRS | WKID | Geometry | Count | Matched Role | Match Basis |
|-----|-----------|-----------|--------|-----|------|----------|-------|-------------|-------------|
| 1 | CandidateSites | 01_DataBackup/CandidateSites.shp | Shapefile | CGCS2000_3_Degree_GK_Zone_39 | 4547 | Point | 15 | Target facility locations | Filename directly matches "candidate sites", geometry is Point |
| 2 | Roads | 01_DataBackup/Roads.shp | Shapefile | CGCS2000_3_Degree_GK_Zone_39 | 4547 | Polyline | 3842 | Constraint factor - Roads | Filename matches "Roads", geometry is Polyline |
| 3 | Waterways | 01_DataBackup/Waterways.shp | Shapefile | CGCS2000_3_Degree_GK_Zone_39 | 4547 | Polyline | 567 | Constraint factor - Rivers | Filename matches "Waterways", geometry is Polyline |
| 4 | AdminBoundary | 01_DataBackup/AdminBoundary.shp | Shapefile | CGCS2000_3_Degree_GK_Zone_39 | 4547 | Polygon | 1 | Study area boundary | Filename matches "AdminBoundary", 1 record = city boundary |

### Dubious Data

| No. | Data Name | Full Path | Reason | Needs Confirmation |
|-----|-----------|-----------|--------|-------------------|
| 1 | POIData | 01_DataBackup/POIData.gdb | Generic name (1.2) — unclear if contains population density info | Check internal feature class list for population-related data |

### Missing Data

| No. | Required Role | Role Description | Required/Recommended | Suggested Action |
|-----|--------------|-----------------|---------------------|-----------------|
| 1 | Existing waste stations | Currently operating waste transfer station locations, to avoid proximity | Recommended | Ask user if available, or skip this factor |
```

### 示例 2：耕地质量评价

```markdown
## Data Inventory

> Task Type: Farmland Quality Evaluation
> Analysis Object: Farmland
> Analysis Scope: XX County
> Generated: 2025-01-15 14:00

---

### Matched Data

| No. | Data Name | Full Path | Format | CRS | WKID | Geometry | Count | Matched Role | Match Basis |
|-----|-----------|-----------|--------|-----|------|----------|-------|-------------|-------------|
| 1 | LandParcel | 01_DataBackup/SurveyData.gdb/DLTB | GDB FeatureClass | CGCS2000_3_Degree_GK_Zone_39 | 4547 | Polygon | 52340 | Farmland parcels | Feature class "DLTB" (land parcel), contains DLBM field for filtering farmland |
| 2 | DEM | 01_DataBackup/dem.tif | GeoTIFF | CGCS2000_3_Degree_GK_Zone_39 | 4547 | Raster | 2048x2048 | Terrain data | Filename matches "DEM", format is GeoTIFF |
| 3 | SoilType | 01_DataBackup/SoilData.gdb/TR | GDB FeatureClass | CGCS2000_3_Degree_GK_Zone_39 | 4547 | Polygon | 1230 | Soil data | Feature class "TR" (soil), contains soil type fields |
| 4 | AdminBoundary | 01_DataBackup/AdminBoundary.shp | Shapefile | CGCS2000_3_Degree_GK_Zone_39 | 4547 | Polygon | 18 | Study area boundary | Filename matches "AdminBoundary", 18 records = county townships |

### Dubious Data

| No. | Data Name | Full Path | Reason | Needs Confirmation |
|-----|-----------|-----------|--------|-------------------|
| 1 | LandParcel | 01_DataBackup/SurveyData.gdb/DLTB | Unknown classification system (1.5) — DLBM coding rules not in field alias | Check DLBM unique values, confirm if standard land use classification codes |

### Missing Data

| No. | Required Role | Role Description | Required/Recommended | Suggested Action |
|-----|--------------|-----------------|---------------------|-----------------|
| 1 | Water facilities | Irrigation canals, reservoirs, etc., for irrigation condition evaluation | Recommended | Ask user if available |
| 2 | Meteorological data | Precipitation, accumulated temperature, etc., for climate condition evaluation | Recommended | Ask user if available |
```

## 5. 清单后续动作

| Inventory Status | Follow-up Action |
|-----------------|------------------|
| All matched, no dubious, no missing | Return to caller, proceed to next step |
| Dubious data exists | Call data-doubt-check Skill criteria to confirm each item, update inventory |
| Missing required data | Call `AskUserQuestion` to ask user for action (provide alternative / skip factor) |
| Missing recommended data | Record in inventory, don't block flow, mark as "optional" during task decomposition |
