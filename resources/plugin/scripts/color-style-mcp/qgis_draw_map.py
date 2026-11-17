# -*- coding: utf-8 -*-
"""QGIS 制图后端 — new_draw_map.py（ArcPy）相同 JSON 契约的 QGIS 实现。

由 color_style_server.py 经 QGIS 自带 Python 子进程调用（Windows:
python-qgis*.bat，o4w_env 已备好 QGIS_PREFIX_PATH/PYTHONPATH；POSIX: python3）：

    echo <map_json> | python-qgis-ltr.bat qgis_draw_map.py

接口保持不变：stdin 读 JSON（tty 时走调试参数），stdout 最后一行 `{` 开头的
JSON 行为结果，字段与 new_draw_map.py 完全一致（success/output_path/message/
added_layers_count/total_layers_count/layer_errors/warnings）。

映射关系（ArcGIS JSON → QGIS）：
  - feature_class "x.gdb/层名" → OGR URI "x.gdb|layername=层名"；shp/gpkg/geojson
    直开；.tif 栅格直开（栅格忽略符号系统，仅按原样显示并记 warning）
  - renderer simple       → QgsSingleSymbolRenderer（几何类型自适应点/线/面符号）
  - renderer unique_value → QgsCategorizedSymbolRenderer（classes 缺省时按字段
    唯一值自动配色）
  - renderer graduated_colors → QgsGraduatedSymbolRenderer（natural_breaks/
    equal_interval/quantile/standard_deviation → Jenks/等间距/分位数/标准差；
    color_scheme.start_color→end_color 线性插值分级色）
  - renderer classed → QgsCategorizedSymbolRenderer + CASE 表达式（不改数据，
    等价 ArcPy 的"先归类再唯一值"）
  - labeling → QgsPalLayerSettings + 白色 halo buffer（宋体/黑色，与 ArcPy 一致）
  - layout.basemap_name → 瓦片拼贴底图（按地图范围抓取 Esri/OSM XYZ 瓦片，拼贴
    PNG+世界文件置于最底层；不支持的名称以 Topographic 近似并记 warning；空值不添加底图）
  - map_elements → QgsLayoutItemLabel(标题) / Picture(指北针 SVG) /
    ScaleBar / Legend；页面尺寸表与 ArcPy 相同；导出 300dpi PNG
"""

import glob
import json
import os
import sys
import traceback
from pathlib import Path

if os.name != "nt":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYTHONUTF8", "1")


def _log(msg):
    print(msg, flush=True)


# ── 调试用默认参数（stdin 无输入时使用；结构与 new_draw_map.py 一致）──
_DEBUG_PARAMS = {
    "layers": [
        {
            "id": "示例图层",
            "feature_class": r"D:\test\01_DataBackup\data.gdb\示例要素类",
            "visible": True,
            "renderer": {
                "type": "unique_value",
                "field": "类型",
                "classes": [
                    {"value": "A", "label": "类别A", "symbol": {"fill_color": [247, 0, 0, 80]}},
                    {"value": "B", "label": "类别B", "symbol": {"fill_color": [51, 101, 138, 80]}},
                ],
            },
            "labeling": {"enabled": True, "field": "名称"},
        }
    ],
    "layout": {
        "orientation": "landscape",
        "output_path": r"D:\test\03_Result\qgis_map.png",
        "page_size": "A4",
        "title": "QGIS 制图示例",
        "basemap_name": "",
    },
    "map_elements": {
        "legend": {"enabled": True, "position": "bottom_right", "title": "图  例"},
        "north_arrow": {"enabled": True, "position": "top_right"},
        "scale_bar": {"enabled": True, "position": "bottom_left"},
    },
}


def _read_params() -> dict:
    if sys.stdin.isatty():
        _log("stdin 是交互式终端，跳过读取，使用调试默认参数")
        return _DEBUG_PARAMS
    raw = sys.stdin.read()
    try:
        return json.loads(raw)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"success": False, "error": f"JSON 解析失败: {e}"}, ensure_ascii=False))
        sys.exit(0)


# ── QGIS 初始化（导入失败立即以 JSON 报错，便于服务器侧透出）──
try:
    from qgis.core import (  # noqa: E402
        Qgis,
        QgsApplication,
        QgsCategorizedSymbolRenderer,
        QgsClassificationEqualInterval,
        QgsClassificationJenks,
        QgsClassificationQuantile,
        QgsClassificationStandardDeviation,
        QgsCoordinateReferenceSystem,
        QgsFillSymbol,
        QgsLayoutExporter,
        QgsPrintLayout,
        QgsLayoutItem,
        QgsLayoutItemLabel,
        QgsLayoutItemLegend,
        QgsLayoutItemMap,
        QgsLayoutItemPicture,
        QgsLayoutItemScaleBar,
        QgsLayoutPoint,
        QgsLayoutSize,
        QgsLineSymbol,
        QgsMarkerSymbol,
        QgsPalLayerSettings,
        QgsProject,
        QgsRasterLayer,
        QgsRectangle,
        QgsRendererCategory,
        QgsSingleSymbolRenderer,
        QgsTextBufferSettings,
        QgsTextFormat,
        QgsUnitTypes,
        QgsVectorLayer,
        QgsVectorLayerSimpleLabeling,
    )
    from qgis.PyQt.QtGui import QColor, QFont  # noqa: E402
except Exception as e:  # noqa: BLE001
    print(json.dumps({
        "success": False,
        "error": f"QGIS Python 运行时不可用（需经 python-qgis*.bat 启动）: {type(e).__name__}: {e}",
    }, ensure_ascii=False))
    sys.exit(0)


_MM = QgsUnitTypes.LayoutMillimeters
_PT = QgsUnitTypes.RenderPoints
_WORLD_CIRCUMFERENCE = 40075016.686  # Web 墨卡托全幅宽（米）
_TILE_PX = 256

# ArcGIS Pro 页面尺寸表（毫米），与 new_draw_map.py 一致
PAGE_SIZES = {
    "A4": {"portrait": (210.06, 296.93), "landscape": (296.93, 210.06)},
    "A3": {"portrait": (296.93, 420.12), "landscape": (420.12, 296.93)},
    "Letter": {"portrait": (215.9, 279.4), "landscape": (279.4, 215.9)},
    "Legal": {"portrait": (215.9, 355.6), "landscape": (355.6, 215.9)},
}
PT_TO_MM = 0.3528  # ArcPy 线宽/字号（磅）→ QGIS（毫米）

# ArcGIS 底图名称 → XYZ 瓦片（Esri 公共服务 / OSM）。{z}/{y}/{x} 为 Esri 顺序。
# 底图不使用 QGIS 内置 XYZ 图层：headless 下其瓦片下载器全部重试失败（详见 _download_tile），
# 改为按地图范围抓瓦片拼贴 PNG+世界文件（_add_basemap）。
BASEMAP_TILES = {
    "Imagery": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    "Imagery Hybrid": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    "NAIP Imagery Hybrid": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    "Firefly Imagery Hybrid": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    "Streets": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
    "Navigation": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
    "Navigation (Places)": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
    "Topographic": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
    "Topographic (Vector)": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
    "Terrain with Labels": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Terrain_Base/MapServer/tile/{z}/{y}/{x}",
    "Oceans": "https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}",
    "OpenStreetMap Style": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    "Light Gray Canvas": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    "Outline Map": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    "Enhanced Contrast Map": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    "Dark Gray Canvas": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    "Navigation (Dark)": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    "Navigation (Dark - Places)": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    "Enhanced Contrast Dark Map": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
}
BASEMAP_FALLBACK = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}"

# unique_value 自动配色（classes 缺省时）与 graduated 默认色带
CATEGORY_PALETTE = [
    (166, 206, 227), (31, 120, 180), (178, 223, 138), (51, 160, 44),
    (251, 154, 154), (227, 26, 28), (253, 191, 111), (255, 127, 0),
    (202, 178, 214), (106, 61, 154), (255, 255, 153), (177, 89, 40),
]
GRADUATED_DEFAULT = ((255, 255, 204), (153, 0, 13))  # 类似 RdYlBu 暖端


def _rgba(color_list, default=(0, 0, 0, 100)):
    """ArcPy [R,G,B,(A%)] → QColor（alpha 0-255）。"""
    src = list(color_list) if color_list and len(color_list) >= 3 else list(default)
    alpha = int(round(src[3] if len(src) > 3 else 100))
    return QColor(int(src[0]), int(src[1]), int(src[2]), max(0, min(255, int(alpha * 255 / 100))))


def _fill_symbol(cfg):
    return QgsFillSymbol.createSimple({
        "color": _rgba(cfg.get("fill_color"), (211, 211, 211, 70)).name(),
        "outline_color": _rgba(cfg.get("outline_color"), (100, 100, 100, 100)).name(),
        "outline_width": f"{float(cfg.get('outline_width', 1)) * PT_TO_MM:.3f}",
        "outline_style": "solid",
        "style": "solid",
        "joinstyle": "round",
    })


def _line_symbol(cfg):
    return QgsLineSymbol.createSimple({
        "line_color": _rgba(cfg.get("fill_color"), (31, 120, 180, 100)).name(),
        "line_width": f"{float(cfg.get('outline_width', cfg.get('size', 1))) * PT_TO_MM:.3f}",
        "capstyle": "round",
        "joinstyle": "round",
    })


def _marker_symbol(cfg):
    return QgsMarkerSymbol.createSimple({
        "name": "circle",
        "color": _rgba(cfg.get("fill_color"), (31, 120, 180, 90)).name(),
        "outline_color": _rgba(cfg.get("outline_color"), (100, 100, 100, 100)).name(),
        "outline_width": f"{float(cfg.get('outline_width', 0.4)) * PT_TO_MM:.3f}",
        "size": f"{float(cfg.get('size', 8)) * PT_TO_MM:.3f}",
    })


def _symbol_for_geometry(geom_type, cfg):
    if geom_type == Qgis.GeometryType.Point:
        return _marker_symbol(cfg)
    if geom_type == Qgis.GeometryType.Line:
        return _line_symbol(cfg)
    return _fill_symbol(cfg)


def _layer_uri(feature_class: str):
    """feature_class → (uri, provider)。GDB 层名转 OGR URI。"""
    fc = feature_class.replace("\\", "/").rstrip("/")
    lower = fc.lower()
    if ".gdb/" in lower:
        path, layer_name = fc.rsplit("/", 1)
        return f"{path}|layername={layer_name}", "ogr"
    if lower.endswith((".shp", ".geojson", ".json", ".gpkg", ".csv")):
        return fc, "ogr"
    if lower.endswith((".tif", ".tiff", ".img", ".png", ".jpg")):
        return fc, "gdal"
    return fc, "ogr"


def _apply_renderer(layer, renderer_cfg, warnings, layer_id):
    rtype = (renderer_cfg.get("type") or "simple").strip()
    geom = layer.geometryType()

    if rtype == "simple":
        layer.setRenderer(QgsSingleSymbolRenderer(_symbol_for_geometry(geom, renderer_cfg.get("symbol") or {})))
        return

    if rtype == "unique_value":
        field = renderer_cfg.get("field", "")
        classes = renderer_cfg.get("classes") or []
        default_cfg = renderer_cfg.get("default_symbol") or {}
        categories = []
        if classes:
            for i, cls in enumerate(classes):
                value = str(cls.get("value", ""))
                label = str(cls.get("label", value))
                symbol = _symbol_for_geometry(geom, cls.get("symbol") or {})
                categories.append(QgsRendererCategory(value, symbol, label))
        else:
            # 未给出 classes：按字段唯一值自动配色
            field_index = layer.fields().indexOf(field) if field else -1
            values = sorted({str(v) for v in layer.uniqueValues(field_index) if v is not None}) if field_index >= 0 else []
            for i, value in enumerate(values):
                color = CATEGORY_PALETTE[i % len(CATEGORY_PALETTE)]
                symbol = _symbol_for_geometry(geom, {"fill_color": list(color) + [80]})
                categories.append(QgsRendererCategory(value, symbol, value))
        try:
            renderer = QgsCategorizedSymbolRenderer(field, categories, _symbol_for_geometry(geom, default_cfg))
        except TypeError:
            # 部分 QGIS LTR 构建未导出 3 参构造/default symbol 绑定
            renderer = QgsCategorizedSymbolRenderer(field, categories)
        layer.setRenderer(renderer)
        return

    if rtype == "graduated_colors":
        field = renderer_cfg.get("field", "")
        method = renderer_cfg.get("classification_method", "natural_breaks")
        class_count = int(renderer_cfg.get("class_count", 5) or 5)
        method_map = {
            "natural_breaks": QgsClassificationJenks,
            "equal_interval": QgsClassificationEqualInterval,
            "quantile": QgsClassificationQuantile,
            "standard_deviation": QgsClassificationStandardDeviation,
        }
        classification = (method_map.get(method) or QgsClassificationJenks)()
        if method not in method_map:
            warnings.append({
                "layer_id": layer_id, "element": "符号系统",
                "reason": f"classification_method '{method}' 在 QGIS 后端按 natural_breaks 近似",
            })
        renderer = QgsGraduatedRendererSafe(classification, field, class_count, layer, renderer_cfg, geom)
        layer.setRenderer(renderer)
        return

    if rtype == "classed":
        field = renderer_cfg.get("field", "")
        classes = renderer_cfg.get("classes") or []
        default_cfg = renderer_cfg.get("default_symbol") or {}
        if not classes:
            layer.setRenderer(QgsSingleSymbolRenderer(_symbol_for_geometry(geom, default_cfg)))
            return
        # ArcPy 的"先归类再唯一值"在 QGIS 用 CASE 表达式实现，不改数据
        whens = " ".join(
            f"WHEN tostring(\"{field}\")='{str(cls.get('value', cls.get('label', '')))}' "
            f"THEN '{str(cls.get('label', cls.get('value', '')))}'"
            for cls in classes
        )
        default_label = str(classes[-1].get("label", "其它"))
        expression = f"CASE {whens} ELSE '{default_label}' END"
        categories = []
        for cls in classes:
            label = str(cls.get("label", cls.get("value", "")))
            categories.append(QgsRendererCategory(label, _symbol_for_geometry(geom, cls.get("symbol") or {}), label))
        categories.append(QgsRendererCategory(default_label, _symbol_for_geometry(geom, default_cfg), default_label))
        try:
            renderer = QgsCategorizedSymbolRenderer(expression, categories, _symbol_for_geometry(geom, default_cfg))
        except TypeError:
            renderer = QgsCategorizedSymbolRenderer(expression, categories)
        layer.setRenderer(renderer)
        return

    warnings.append({
        "layer_id": layer_id, "element": "符号系统",
        "reason": f"renderer.type '{rtype}' 未知，按 simple 处理",
    })
    layer.setRenderer(QgsSingleSymbolRenderer(_symbol_for_geometry(geom, {})))


def QgsGraduatedRendererSafe(classification, field, class_count, layer, renderer_cfg, geom):
    """构建分级色彩渲染器（独立函数便于内联异常处理）。"""
    from qgis.core import QgsGraduatedSymbolRenderer

    renderer = QgsGraduatedSymbolRenderer()
    renderer.setClassAttribute(field)
    renderer.setClassificationMethod(classification)
    renderer.updateClasses(layer, class_count)

    scheme = renderer_cfg.get("color_scheme") or {}
    start = scheme.get("start_color")
    end = scheme.get("end_color")
    s = list(start[:3]) if start else list(GRADUATED_DEFAULT[0])
    e = list(end[:3]) if end else list(GRADUATED_DEFAULT[1])
    outline = _rgba(renderer_cfg.get("outline_color", [100, 100, 100, 100]))
    width_mm = float(renderer_cfg.get("outline_width", 1) or 1) * PT_TO_MM

    ranges = list(renderer.ranges())
    count = len(ranges)
    for i, old_range in enumerate(ranges):
        t = i / max(1, count - 1)
        color = QColor(
            int(s[0] + (e[0] - s[0]) * t),
            int(s[1] + (e[1] - s[1]) * t),
            int(s[2] + (e[2] - s[2]) * t),
        )
        color.setAlpha(int(80 * 255 / 100))
        symbol = _symbol_for_geometry(geom, {})
        symbol.setColor(color)
        for lvl in range(symbol.symbolLayerCount()):
            sl = symbol.symbolLayer(lvl)
            if hasattr(sl, "setStrokeColor"):
                sl.setStrokeColor(outline)
            if hasattr(sl, "setStrokeWidth"):
                sl.setStrokeWidth(width_mm)
        label = f"{_fmt_break(old_range.lowerValue())} – {_fmt_break(old_range.upperValue())}"
        renderer.updateRangeSymbol(i, symbol)
        renderer.updateRangeLabel(i, label)
    return renderer


def _fmt_break(value):
    try:
        return f"{float(value):,.2f}".rstrip("0").rstrip(".") if float(value) % 1 else f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return str(value)


def _apply_labeling(layer, labeling_cfg, warnings, layer_id):
    if not labeling_cfg.get("enabled", False) or not labeling_cfg.get("field", ""):
        return
    field = labeling_cfg.get("field", "")
    settings = QgsPalLayerSettings()
    settings.fieldName = f'"{field}"'
    settings.isExpression = True

    font_cfg = labeling_cfg.get("font", {})
    font = QFont(font_cfg.get("family") or "SimSun")
    text_format = QgsTextFormat()
    text_format.setFont(font)
    text_format.setSize(float(font_cfg.get("size", 10) or 10))
    text_format.setSizeUnit(_PT)
    text_format.setColor(_rgba(labeling_cfg.get("color", [0, 0, 0, 100])))

    halo = labeling_cfg.get("halo", {})
    if halo.get("enabled", True):
        buffer = QgsTextBufferSettings()
        buffer.setEnabled(True)
        buffer.setColor(_rgba(halo.get("color", [255, 255, 255, 100])))
        buffer.setSize(float(halo.get("size", 1) or 1))
        buffer.setSizeUnit(_PT)
        text_format.setBuffer(buffer)

    settings.setFormat(text_format)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)


def _download_tile(url, timeout_ms=8000):
    """同步抓取一张瓦片，返回 QImage 或 None。

    不用 QGIS 内置 XYZ provider：其瓦片下载器在 headless 子进程里依赖 GUI 主线程
    常驻事件循环，全部请求重试失败（实测 Esri/OSM 均如此）；而
    QgsNetworkAccessManager 同步请求稳定可用（走系统代理），故底图改为手绘拼贴。
    """
    from qgis.PyQt.QtCore import QEventLoop, QTimer, QUrl
    from qgis.PyQt.QtGui import QImage
    from qgis.PyQt.QtNetwork import QNetworkRequest
    try:
        from qgis.core import QgsNetworkAccessManager
        loop = QEventLoop()
        box = {"img": None}

        def _done():
            try:
                img = QImage()
                if img.loadFromData(bytes(reply.readAll())):
                    box["img"] = img
            finally:
                loop.quit()

        reply = QgsNetworkAccessManager.instance().get(QNetworkRequest(QUrl(url)))
        reply.finished.connect(_done)
        QTimer.singleShot(timeout_ms, loop.quit)
        loop.exec_()
        return box["img"]
    except Exception:  # noqa: BLE001
        return None


def _add_basemap(project, basemap_name, warnings, map_extent):
    """底图：按可见范围抓取 XYZ 瓦片拼贴为 PNG+世界文件，置于图层树最底层。

    map_extent 为地图框最终范围（数据坐标系）；无法转换到 Web 墨卡托或瓦片
    全部下载失败时记 warning 并跳过底图。
    """
    import math
    import tempfile

    if not basemap_name:
        return None
    url = BASEMAP_TILES.get(basemap_name)
    if url is None:
        warnings.append({
            "element": "底图",
            "reason": f"basemap_name '{basemap_name}' 在 QGIS 后端无同名瓦片，以 Topographic 近似",
        })
        url = BASEMAP_FALLBACK
    if map_extent is None or map_extent.width() <= 0 or map_extent.height() <= 0:
        warnings.append({"element": "底图", "reason": "无有效地图范围，跳过底图"})
        return None

    merc = QgsCoordinateReferenceSystem("EPSG:3857")
    try:
        if project.crs().isValid() and project.crs() != merc:
            transform = QgsCoordinateTransformSafe(project.crs(), merc, project)
            extent = transform.transformBoundingBox(map_extent)
        else:
            extent = map_extent
    except Exception as e:  # noqa: BLE001
        warnings.append({"element": "底图", "reason": f"地图范围转 Web 墨卡托失败，跳过底图: {e}"})
        return None

    north = _WORLD_CIRCUMFERENCE / 2
    extent = QgsRectangle(
        max(extent.xMinimum(), -north), max(extent.yMinimum(), -north * 0.999),
        min(extent.xMaximum(), north), min(extent.yMaximum(), north * 0.999),
    )
    # 选择瓦片总数不超过 8x8 的最高缩放级
    zoom = 0
    for cand in range(18, -1, -1):
        tile_m = _WORLD_CIRCUMFERENCE / (2 ** cand)
        if max(math.ceil(extent.width() / tile_m), math.ceil(extent.height() / tile_m)) <= 8:
            zoom = cand
            break
    n_tiles = 2 ** zoom
    tile_m = _WORLD_CIRCUMFERENCE / n_tiles
    x0 = max(0, math.floor((extent.xMinimum() + north) / tile_m))
    x1 = min(n_tiles - 1, math.floor((extent.xMaximum() + north) / tile_m))
    y0 = max(0, math.floor((north - extent.yMaximum()) / tile_m))
    y1 = min(n_tiles - 1, math.floor((north - extent.yMinimum()) / tile_m))
    _log(f"  底图瓦片: z={zoom} 行 {y0}-{y1} 列 {x0}-{x1}")

    from qgis.PyQt.QtGui import QColor, QPainter, QImage
    mosaic = QImage((x1 - x0 + 1) * _TILE_PX, (y1 - y0 + 1) * _TILE_PX, QImage.Format_RGB32)
    mosaic.fill(QColor(255, 255, 255))
    painter = QPainter(mosaic)
    fetched, failed = 0, 0
    for ty in range(y0, y1 + 1):
        for tx in range(x0, x1 + 1):
            tile_url = url.replace("{z}", str(zoom)).replace("{x}", str(tx)).replace("{y}", str(ty))
            img = _download_tile(tile_url)
            if img is None:
                failed += 1
                continue
            painter.drawImage((tx - x0) * _TILE_PX, (ty - y0) * _TILE_PX, img)
            fetched += 1
    painter.end()
    if fetched == 0:
        warnings.append({"element": "底图", "reason": "瓦片全部下载失败（网络不可达或代理拦截），底图为空白"})
        return None
    if failed:
        warnings.append({"element": "底图", "reason": f"{failed} 张瓦片下载失败，底图局部空白"})

    out_dir = Path(tempfile.gettempdir()) / "linktool_basemap"
    out_dir.mkdir(parents=True, exist_ok=True)
    png_path = out_dir / f"basemap_{zoom}_{x0}_{y0}_{x1}_{y1}.png"
    mosaic.save(str(png_path), "PNG")
    res = tile_m / _TILE_PX
    (png_path.with_suffix(".pgw")).write_text("\n".join([
        repr(res), "0", "0", repr(-res),
        repr(-north + x0 * tile_m), repr(north - y0 * tile_m),
    ]), encoding="ascii")

    layer = QgsRasterLayer(str(png_path), f"底图-{basemap_name}")
    layer.setCrs(merc)
    if not layer.isValid():
        warnings.append({"element": "底图", "reason": "拼贴底图图层无效（GDAL 加载失败）"})
        return None
    project.addMapLayer(layer)
    root = project.layerTreeRoot()
    node = root.findLayer(layer.id())
    if node is not None:
        # 追加到末尾 = 面板最底 = 最先绘制（专题图层在其上）；
        # index 0 是最顶层，会盖住全部专题图层（QGIS 树首节点绘制在最上）
        clone = node.clone()
        root.addChildNode(clone)
        root.removeChildNode(node)
    _log(f"  [OK] 底图拼贴完成: {fetched} 张瓦片 (z{zoom})")
    return layer


def _north_arrow_svg():
    prefix = (os.environ.get("QGIS_PREFIX_PATH") or "").replace("\\", "/").rstrip("/")
    candidates = []
    if prefix:
        candidates.append(f"{prefix}/svg/arrows/NorthArrow_02.svg")
    root = prefix.rsplit("/apps/", 1)[0] if "/apps/" in prefix else None
    if root:
        candidates += sorted(glob.glob(f"{root}/apps/qgis*/svg/arrows/NorthArrow_02.svg"))
    candidates += sorted(glob.glob(r"C:\Program Files\QGIS *\apps\qgis*\svg\arrows\NorthArrow_02.svg"))
    for c in candidates:
        if os.path.isfile(c.replace("/", os.sep) if os.name == "nt" else c):
            return c
    return None


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    params = _read_params()
    layers_config = params.get("layers", [])
    layout_config = params.get("layout", {})
    map_elements = params.get("map_elements", {})
    output_path = layout_config.get("output_path", "")

    if not layers_config:
        print(json.dumps({"success": False, "error": "缺少图层配置: layers不能为空"}, ensure_ascii=False))
        sys.exit(0)
    if not output_path:
        print(json.dumps({"success": False, "error": "缺少输出路径: layout.output_path不能为空"}, ensure_ascii=False))
        sys.exit(0)

    _log(f"[1/9] 参数校验通过，共 {len(layers_config)} 个图层，输出路径: {output_path}")

    # ── QGIS 运行时 ──
    prefix = (os.environ.get("QGIS_PREFIX_PATH") or "").replace("\\", "/")
    if prefix:
        QgsApplication.setPrefixPath(prefix, True)
    app = QgsApplication([], False)
    app.initQgis()

    added_layers = []
    layer_errors = []
    layer_warnings = []
    basemap_layer = None

    try:
        project = QgsProject.instance()

        # ── 逐图层处理 ──
        for i, layer_cfg in enumerate(layers_config):
            layer_id = layer_cfg.get("id", f"layer_{i}")
            fc_path = layer_cfg.get("feature_class", "")
            visible = layer_cfg.get("visible", True)
            _log(f"[3/9] 处理图层 [{i + 1}/{len(layers_config)}]: {layer_id}")

            if not fc_path:
                layer_errors.append({"layer_id": layer_id, "layer_index": i, "reason": "feature_class为空"})
                continue

            uri, provider = _layer_uri(fc_path)
            if provider == "gdal":
                layer = QgsRasterLayer(uri, layer_cfg.get("layer_name") or layer_id)
            else:
                layer = QgsVectorLayer(uri, layer_cfg.get("layer_name") or layer_id, provider)
            if not layer.isValid():
                layer_errors.append({
                    "layer_id": layer_id, "layer_index": i, "feature_class": fc_path,
                    "reason": f"图层无效或路径不存在: {fc_path}",
                })
                continue

            project.addMapLayer(layer)
            node = project.layerTreeRoot().findLayer(layer.id())
            if node is not None:
                node.setItemVisibilityChecked(bool(visible))
            added_layers.append(layer)

            # 栅格不做符号系统/标注
            if provider == "gdal":
                layer_warnings.append({
                    "layer_id": layer_id, "layer_index": i,
                    "reason": "栅格图层按原样渲染，忽略符号系统与标注配置",
                })
                continue

            try:
                _apply_renderer(layer, layer_cfg.get("renderer", {}) or {}, layer_warnings, layer_id)
                layer.triggerRepaint()
                _log("  [OK] 符号系统设置完成")
            except Exception as e:  # noqa: BLE001
                layer_warnings.append({
                    "layer_id": layer_id, "layer_index": i, "element": "符号系统",
                    "reason": f"设置符号系统失败: {e}",
                })
            try:
                _apply_labeling(layer, layer_cfg.get("labeling", {}) or {}, layer_warnings, layer_id)
                _log(f"  [OK] 标注设置完成 (enabled={bool((layer_cfg.get('labeling') or {}).get('enabled'))})")
            except Exception as e:  # noqa: BLE001
                layer_warnings.append({
                    "layer_id": layer_id, "layer_index": i, "element": "标注",
                    "reason": f"设置标注失败: {e}",
                })

        if not added_layers:
            print(json.dumps({
                "success": False,
                "error": "所有图层添加失败，图中无专题地图数据",
                "layer_errors": layer_errors,
            }, ensure_ascii=False))
            sys.exit(0)
        _log(f"[3/9] 图层处理完成，成功添加 {len(added_layers)}/{len(layers_config)} 个图层")

        # ── 页面与布局 ──
        page_size = layout_config.get("page_size", "A4")
        orientation = layout_config.get("orientation", "landscape")
        width, height = PAGE_SIZES.get(page_size, PAGE_SIZES["A4"]).get(orientation, PAGE_SIZES["A4"]["landscape"])
        _log(f"[4/9] 创建布局 ({page_size} {orientation}, {width}x{height}mm)...")

        layout = QgsPrintLayout(project)
        layout.initializeDefaults()
        layout.pageCollection().page(0).setPageSize(QgsLayoutSize(width, height, _MM))
        project.layoutManager().addLayout(layout)

        # ── 警告收集（底图在地图范围确定后抓取拼贴）──
        warnings = []

        # ── 地图框（页面坐标原点在左上）──
        title = layout_config.get("title", "")
        fw = width * 0.95
        fh = height * 0.95
        fx = (width - fw) / 2
        fy = (height - fh) / 2
        if title:
            fh = (height - 10) * 0.95
            fy = (height - fh) / 2 + 5

        _log(f"[5/9] 创建地图框 ({fw:.1f}x{fh:.1f}mm, 位置 x={fx:.1f} y={fy:.1f})...")
        map_item = QgsLayoutItemMap(layout)
        map_item.setRect(0, 0, fw, fh)
        layout.addLayoutItem(map_item)
        map_item.attemptMove(QgsLayoutPoint(fx, fy, _MM))
        map_item.attemptResize(QgsLayoutSize(fw, fh, _MM))
        map_item.setFrameEnabled(True)
        map_item.setFrameStrokeColor(QColor(0, 0, 0))
        map_item.setFrameStrokeWidth(QgsLayoutMeasurementSafe(0.4))

        # ── 地图 CRS（ArcPy 语义：以首个专题图层坐标系为准，底图在线重投影）──
        try:
            for layer in added_layers:
                if hasattr(layer, "crs") and layer.crs().isValid():
                    map_item.setCrs(layer.crs())
                    project.setCrs(layer.crs())
                    _log(f"  地图 CRS 锚定图层坐标系: {layer.crs().authid()}")
                    break
        except Exception as e:  # noqa: BLE001
            _log(f"  [WARN] 地图 CRS 锚定失败: {e}")

        # ── 地图范围（图层联合范围外扩 margin）──
        extent_warning = None
        extent_span = None
        basemap_extent = None
        try:
            rects = [layer.extent() for layer in added_layers if hasattr(layer, "extent")]
            if rects:
                union = rects[0]
                for r in rects[1:]:
                    union.combineExtentWith(r)
                # 目标 CRS 差异时变换到工程 CRS（单图层/同 CRS 时为恒等）
                dest_crs = project.crs()
                for layer in added_layers:
                    if hasattr(layer, "crs") and layer.crs().isValid() and dest_crs.isValid() and layer.crs() != dest_crs:
                        transform = QgsCoordinateTransformSafe(layer.crs(), dest_crs, project)
                        union = transform.transformBoundingBox(layer.extent())
                        break
                dx = union.xMaximum() - union.xMinimum()
                dy = union.yMaximum() - union.yMinimum()
                extent_span = dx
                margin = float(layout_config.get("extent_margin", 0.10) or 0.10)
                union = QgsRectangle(
                    union.xMinimum() - dx * margin,
                    union.yMinimum() - dy * margin,
                    union.xMaximum() + dx * margin,
                    union.yMaximum() + dy * margin,
                )
                map_item.zoomToExtent(union)
                basemap_extent = union
                _log(f"  [OK] 地图范围设置完成（margin={margin}）")
        except Exception as e:  # noqa: BLE001
            extent_warning = f"设置地图范围失败: {e}"
            _log(f"  [FAIL] {extent_warning}")

        # ── 底图（按最终地图范围抓取瓦片拼贴，置于最底层）──
        try:
            basemap_layer = _add_basemap(project, layout_config.get("basemap_name", ""), warnings, basemap_extent)
            if basemap_layer is not None:
                _log(f"  [OK] 底图设置完成: {layout_config.get('basemap_name', '')}")
        except Exception as e:  # noqa: BLE001
            warnings.append({"element": "底图", "reason": f"底图设置失败: {e}"})

        element_warnings = []

        # ── 标题 ──
        if title:
            _log(f"[6/9] 添加标题: {title}")
            try:
                label = QgsLayoutItemLabel(layout)
                font = QFont("Arial", 24)
                font.setBold(True)
                label.setFont(font)
                label.setText(title)
                layout.addLayoutItem(label)
                label.attemptResize(QgsLayoutSize(fw * 0.9, 12, _MM))
                label.attemptMove(QgsLayoutPoint((width - fw * 0.9) / 2, 2.0, _MM))
                label.setFrameEnabled(False)
            except Exception as e:  # noqa: BLE001
                element_warnings.append({"element": "标题", "reason": f"添加标题失败: {e}"})

        # ── 公共锚点：按角位显式计算目标左上角后放置（含 5% 边距）──
        # 不用 attemptMove 的 PagePosition 枚举参数：3.44 LTR 绑定中部分项按
        # 左上角语义落位，导致图例越出页面右下缘（实测）。
        def place(item, position, w, h):
            mx = 0.05 * fw
            my = 0.05 * fh
            px, py = {
                "top_left": (fx + mx, fy + my),
                "top_right": (fx + fw - mx - w, fy + my),
                "bottom_left": (fx + mx, fy + fh - my - h),
                "bottom_right": (fx + fw - mx - w, fy + fh - my - h),
            }.get(position, (fx + mx, fy + fh - my - h))
            item.attemptMove(QgsLayoutPoint(px, py, _MM))

        # ── 指北针 ──
        north_cfg = map_elements.get("north_arrow", {})
        if north_cfg.get("enabled", True):
            _log(f"[7/9] 添加指北针 (位置={north_cfg.get('position', 'top_left')})...")
            try:
                svg = _north_arrow_svg()
                if not svg:
                    raise RuntimeError("未找到指北针 SVG（NorthArrow_02.svg）")
                na = QgsLayoutItemPicture(layout)
                na.setPicturePath(svg)
                layout.addLayoutItem(na)
                na.attemptResize(QgsLayoutSize(20.32, 20.32, _MM))
                place(na, north_cfg.get("position", "top_left"), 20.32, 20.32)
                na.setFrameEnabled(False)
            except Exception as e:  # noqa: BLE001
                element_warnings.append({"element": "指北针", "reason": f"添加指北针失败: {e}"})

        # ── 图例 ──
        legend_cfg = map_elements.get("legend", {})
        if legend_cfg.get("enabled", True):
            _log(f"[8/9] 添加图例 (位置={legend_cfg.get('position', 'bottom_left')})...")
            try:
                legend = QgsLayoutItemLegend(layout)
                legend.setTitle(legend_cfg.get("title", "图  例"))
                legend.setLinkedMap(map_item)
                legend.setAutoUpdateModel(True)
                legend.setResizeToContents(True)  # 内容自适应；place() 已显式固定左上角，增长不会越界
                legend.setBackgroundEnabled(True)
                legend.setBackgroundColor(QColor(255, 255, 255))
                legend.setFrameEnabled(True)
                legend.setFrameStrokeColor(QColor(0, 0, 0))
                legend.setFrameStrokeWidth(QgsLayoutMeasurementSafe(0.35))
                layout.addLayoutItem(legend)
                legend.attemptResize(QgsLayoutSize(76.2, 50.8, _MM))
                place(legend, legend_cfg.get("position", "bottom_left"), 76.2, 50.8)
                # 冻结图例模型并在其私有副本上剔除底图（与 ArcPy 底图不入图例一致）
                legend.setAutoUpdateModel(False)
                legend_root = legend.model().rootGroup()
                for child in list(legend_root.children()):
                    if child.name().startswith("底图-"):
                        legend_root.removeChildNode(child)
            except Exception as e:  # noqa: BLE001
                element_warnings.append({"element": "图例", "reason": f"添加图例失败: {e}"})

        # ── 比例尺 ──
        scale_cfg = map_elements.get("scale_bar", {})
        if scale_cfg.get("enabled", True):
            _log(f"[8/9] 添加比例尺 (位置={scale_cfg.get('position', 'bottom_right')})...")
            try:
                sb = QgsLayoutItemScaleBar(layout)
                sb.setStyle("Single Box")
                sb.setLinkedMap(map_item)
                sb.applyDefaultSize(QgsUnitTypes.DistanceMeters)
                # 单位自适应：地理坐标系用度，投影坐标系按数据跨度选 m/km
                if extent_span is not None and map_item.crs().isGeographic():
                    sb.setUnits(QgsUnitTypes.DistanceDegrees)
                    sb.setUnitLabel("°")
                elif extent_span is not None and 0 < extent_span < 2000:
                    sb.setUnits(QgsUnitTypes.DistanceMeters)
                    sb.setUnitLabel("m")
                else:
                    sb.setUnits(QgsUnitTypes.DistanceKilometers)
                    sb.setUnitLabel("km")
                sb.setBackgroundEnabled(True)
                sb.setBackgroundColor(QColor(255, 255, 255))
                sb.setFrameEnabled(True)
                sb.setFrameStrokeColor(QColor(0, 0, 0))
                layout.addLayoutItem(sb)
                sb.attemptResize(QgsLayoutSize(101.6, 10.16, _MM))
                place(sb, scale_cfg.get("position", "bottom_right"), 101.6, 10.16)
            except Exception as e:  # noqa: BLE001
                element_warnings.append({"element": "比例尺", "reason": f"添加比例尺失败: {e}"})

        # ── 导出 PNG（300dpi）──
        _log(f"[9/9] 导出 PNG 到: {output_path} (300dpi)...")
        out_dir = os.path.dirname(os.path.abspath(output_path))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        exporter = QgsLayoutExporter(layout)
        settings = QgsLayoutExporter.ImageExportSettings()
        settings.dpi = 300
        export_result = exporter.exportToImage(output_path, settings)
        if export_result != QgsLayoutExporter.Success:
            raise RuntimeError(f"QgsLayoutExporter 返回码 {export_result}")
        _log("[9/9] [OK] PNG 导出成功")

        all_warnings = []
        if extent_warning:
            all_warnings.append({"element": "地图范围", "reason": extent_warning})
        all_warnings.extend(element_warnings)
        all_warnings.extend(layer_warnings)
        all_warnings.extend(warnings)

        result = {
            "success": True,
            "output_path": output_path,
            "message": "地图创建成功",
            "added_layers_count": len(added_layers),
            "total_layers_count": len(layers_config),
        }
        if layer_errors:
            result["layer_errors"] = layer_errors
        if all_warnings:
            result["warnings"] = all_warnings
        print(json.dumps(result, ensure_ascii=False))
    finally:
        try:
            app.exitQgis()
        except Exception:  # noqa: BLE001
            pass


def QgsLayoutMeasurementSafe(width_mm):
    from qgis.core import QgsLayoutMeasurement
    return QgsLayoutMeasurement(width_mm, _MM)


def QgsCoordinateTransformSafe(src_crs, dst_crs, project):
    from qgis.core import QgsCoordinateTransform, QgsCoordinateTransformContext
    return QgsCoordinateTransform(src_crs, dst_crs, project)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 —— 兜底：任何未捕获异常都以 JSON 退出，契约不破
        print(json.dumps({
            "success": False,
            "error": f"QGIS 制图失败: {traceback.format_exc(limit=4)}",
        }, ensure_ascii=False))
        sys.exit(0)
