# 负面提示词库（Negative Prompt）

本文件供 Claude Code 在拼装 prompt 时按需取用。

**核心原则**：
- 全部使用**英文名词/形容词短语**，逗号分隔
- 根据当前底图风格和场景，从下方类别中选择**最相关的 5-10 个词**
- 单次负面提示词总长度 **≤200 个英文字符**
- 避免堆砌全部词汇导致注意力稀释

---

## 分类词表

### 1. 地理变形（Geographic Distortion）
适用：所有地图
```
distorted boundaries, changed waterways, skewed roads, mutated terrain,
fake geography, redrawn coastlines, displaced regions, warped shapes
```

### 2. 三维与场景入侵（3D & Scene Intrusion）
适用：所有地图（强制二维平面）
```
3d scene, perspective view, isometric view, tilt-shift, angled camera,
display board, easel, exhibition booth, indoor environment,
outdoor landscape behind map, picture frame, wooden frame
```

### 3. 裁剪与旋转（Crop & Rotation）
适用：所有地图（保持完整图幅）
```
cropped map, zoomed-in partial map, rotated map, tilted map, skewed perspective
```

### 4. 文字与符号乱码（Text & Symbol Corruption）
适用：含标注/标题的地图
```
distorted chinese characters, garbled text, unreadable symbols,
fake letters, random glyphs, misspelled words
```

### 5. 抽象污染与色带（Abstract Contamination）
适用：科学/统计类地图
```
abstract colorful blobs replacing map, simplified silhouette of continent,
rainbow color ramp, jet colormap
```

### 6. 水印与标识（Watermark & Logo）
适用：所有地图
```
hand-drawn signature, watermark, qr code, logo overlay,
stock photo overlay, photographic backdrop
```

---

## 选取原则（通用，不针对任何特定风格）

从上方 6 类词中**按需选取**，遵循以下逻辑：

1. **基线必选（所有地图）**：从第 1 类（地理变形）和第 3 类（裁剪旋转）各选 1-2 个词
2. **根据主题追加**：
   - 含文字标注/标题 → 追加第 4 类（文字乱码）1-2 个词
   - 科学统计/数值场 → 追加第 5 类（抽象污染）1-2 个词
3. **根据"是否强制二维平面"追加**：
   - 所有地图理论上都应追加第 2 类（三维场景）1-2 个词，防止模型把地图画进三维场景里
4. **通用收尾**：第 6 类（水印标识）选 1 个词

**反面教材**：不要把 6 类词全部 40+ 个都堆上去，会导致注意力稀释。控制总长度 ≤200 字符。

**示例**（仅示范格式，非标准答案）：
```
distorted boundaries, fake geography, 3d scene, cropped map, garbled text, watermark
```
（约 90 字符，达标）
