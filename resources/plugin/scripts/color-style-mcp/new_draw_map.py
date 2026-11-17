# ── 启动提示（必须在 arcpy 导入之前，让 PyCharm 等 IDE 立即看到进度） ──
import sys

try:
    # 输出走 UTF-8（服务器侧不再传 PYTHONIOENCODING：显式 env 块会破坏 arcpy 子进程）
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass
print("[START] full_export.py 启动中...", flush=True)
print("[START] 正在加载 arcpy（ArcGIS Pro SDK，首次加载约 30~50 秒）...", flush=True)

import arcpy
import json
import os
import traceback

print("[START] arcpy 加载完成", flush=True)

# ── 调试用默认参数（stdin 无输入时使用）──
_DEBUG_PARAMS = {
    "aprx_path": r"D:\02_User_Files\02项目文件\20260116_LinkTool\LinkTool-ClaudeCode\plugin\scripts\color-style-mcp\catagraphy_project\LinkTool.aprx",
    "layers": [
        {
            "feature_class": r"D:\02_User_Files\02项目文件\20260116_LinkTool\07调试过程存档\test0621\03_Result\441223广宁县\4数据库成果\广宁县第三次全国土壤普查耕地质量等级评价数据库.gdb\广宁县江屯镇第三次全国土壤普查耕地质量等级评价单元图",
            "id": "广宁县耕地质量等级",
            "layer_name": "耕地质量等级",
            "visible": True,
            "labeling": {
                "enabled": False,
                "field": "ZLDJ",
                "color": [0, 0, 0, 100],
                "font": {
                    "family": "SimSun（宋体）",
                    "size": 12
                },
                "halo": {
                    "color": [255, 255, 255, 100],
                    "size": 0.2
                }
            },
            "renderer": {
                "type": "unique_value",
                "field": "ZLDJ",
                "classes": [
                    {
                        "value": "3",
                        "label": "三级耕地",
                        "symbol": {
                            "fill_color": [247, 0, 0, 80],
                            "outline_color": [100, 100, 100, 100],
                            "outline_width": 0.2
                        }
                    },
                    {
                        "value": "4",
                        "label": "四级耕地",
                        "symbol": {
                            "fill_color": [47, 72, 88, 80],
                            "outline_color": [100, 100, 100, 100],
                            "outline_width": 0.2
                        }
                    },
                    {
                        "value": "5",
                        "label": "五级耕地",
                        "symbol": {
                            "fill_color": [51, 101, 138, 80],
                            "outline_color": [100, 100, 100, 100],
                            "outline_width": 0.2
                        }
                    },
                    {
                        "value": "6",
                        "label": "六级耕地",
                        "symbol": {
                            "fill_color": [134, 187, 216, 80],
                            "outline_color": [100, 100, 100, 100],
                            "outline_width": 0.2
                        }
                    },
                    {
                        "value": "7",
                        "label": "七级耕地",
                        "symbol": {
                            "fill_color": [246, 174, 45, 80],
                            "outline_color": [100, 100, 100, 100],
                            "outline_width": 0.2
                        }
                    }
                ],
                "default_symbol": {
                    "fill_color": [45, 34, 30, 80],
                    "outline_color": [100, 100, 100, 100],
                    "outline_width": 1
                }
            }
        }
    ],
    "layout": {
        "orientation": "landscape",
        "output_path": r"D:\11_ClaudeCode\arcpy-map-test\output.png",
        "page_size": "A4",
        "title": "耕地质量等级图",
        "basemap_name": ""
    },
    "map_elements": {
        "legend": {
            "enabled": True,
            "position": "bottom_right",
            "title": "图  例  示  例"
        },
        "north_arrow": {
            "enabled": True,
            "position": "top_right"
        },
        "scale_bar": {
            "enabled": True,
            "position": "bottom_left"
        }
    }
}

def _log(msg):
    """立即刷新输出，确保进度信息实时可见。"""
    print(msg, flush=True)

# ── 核心任务：读取输入参数 ──
_log("[1/9] 读取输入参数...")
try:
    # 仅在 stdin 是管道/重定向（如 MCP 工具通过 subprocess 传参）时才读取；
    # 若 stdin 是交互式终端（PyCharm Run console），isatty() 为 True，
    # 此时 read() 会无限阻塞等待 EOF，直接走默认参数。
    if sys.stdin.isatty():
        print("stdin 是交互式终端，跳过读取，使用调试默认参数")
        _log("[1/9] stdin 是交互式终端，跳过读取，使用调试默认参数")
        params = _DEBUG_PARAMS
    else:
        input_json = sys.stdin.read()
        params = json.loads(input_json)
        _log("[1/9] 从 stdin 读取参数成功")
except Exception:
    # stdin 无有效输入时，使用调试默认参数
    params = _DEBUG_PARAMS
    _log("[1/9] stdin 读取失败或为空，使用调试默认参数")

try:
    layers_config = params.get("layers", [])
    layout_config = params.get("layout", {})
    map_elements = params.get("map_elements", {})

    output_path = layout_config.get("output_path", "")
    aprx_path = params.get("aprx_path", "")

    # ── 校验必要配置 ──
    if not layers_config:
        print(json.dumps({
            "success": False,
            "error": "缺少图层配置: layers不能为空"
        }, ensure_ascii=False))
        sys.exit(0)

    if not output_path:
        print(json.dumps({
            "success": False,
            "error": "缺少输出路径: layout.output_path不能为空"
        }, ensure_ascii=False))
        sys.exit(0)

    _log(f"[1/9] 参数校验通过，共 {len(layers_config)} 个图层，输出路径: {output_path}")

    # ── 核心任务：创建工程 ──
    _log(f"[2/9] 创建 ArcGIS 工程: {aprx_path}")
    try:
        aprx = arcpy.mp.ArcGISProject(aprx_path)
        map_obj = aprx.createMap("地图", "MAP")
        _log("[2/9] ArcGIS 工程创建成功")
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": f"创建ArcGIS工程失败: {str(e)}"
        }, ensure_ascii=False))
        sys.exit(0)

    # ── 逐图层处理 ──
    added_layers = []
    layer_errors = []    # 导致图层完全无法添加的错误
    layer_warnings = []  # 图层添加成功但符号系统/标注设置失败

    for i, layer_cfg in enumerate(layers_config):
        layer_id = layer_cfg.get("id", f"layer_{i}")
        fc_path = layer_cfg.get("feature_class", "")
        visible = layer_cfg.get("visible", True)
        renderer_cfg = layer_cfg.get("renderer", {})
        labeling_cfg = layer_cfg.get("labeling", {})

        _log(f"[3/9] 处理图层 [{i+1}/{len(layers_config)}]: {layer_id}")

        if not fc_path:
            _log(f"  [FAIL] feature_class 为空，跳过")
            layer_errors.append({
                "layer_id": layer_id,
                "layer_index": i,
                "reason": "feature_class为空"
            })
            continue

        # 验证数据路径
        _log(f"  验证数据路径: {fc_path}")
        try:
            if not arcpy.Exists(fc_path):
                _log(f"  [FAIL] 数据路径不存在，跳过")
                layer_errors.append({
                    "layer_id": layer_id,
                    "layer_index": i,
                    "feature_class": fc_path,
                    "reason": f"数据路径不存在: {fc_path}"
                })
                continue
            _log(f"  [OK] 数据路径验证通过")
        except Exception as e:
            _log(f"  [FAIL] 验证数据路径出错: {e}")
            layer_errors.append({
                "layer_id": layer_id,
                "layer_index": i,
                "feature_class": fc_path,
                "reason": f"验证数据路径失败: {str(e)}"
            })
            continue

        # 添加图层
        _log(f"  添加图层到地图...")
        try:
            layer = map_obj.addDataFromPath(fc_path)
            layer.visible = visible
            configured_layer_name = layer_cfg.get("layer_name", "")
            if configured_layer_name:
                layer.name = configured_layer_name
                _log(f"  [OK] 图层添加成功，名称设置为: {configured_layer_name}")
            else:
                _log(f"  [OK] 图层添加成功，使用默认名称: {layer.name}")
            added_layers.append(layer)
        except Exception as e:
            _log(f"  [FAIL] 添加图层失败: {e}")
            layer_errors.append({
                "layer_id": layer_id,
                "layer_index": i,
                "feature_class": fc_path,
                "reason": f"添加图层失败: {str(e)}"
            })
            continue

        # 设置符号系统
        renderer_type = renderer_cfg.get("type", "simple")
        _log(f"  设置符号系统 (type={renderer_type})...")
        try:
            sym = layer.symbology

            def _to_rgb(color_list):
                """Convert [R,G,B,(alpha)] -> {'RGB': [R,G,B,100]}"""
                if not color_list:
                    return None
                if len(color_list) >= 3:
                    return {'RGB': [color_list[0], color_list[1], color_list[2], 100]}
                return None

            if renderer_type == "simple":
                sym.updateRenderer('SimpleRenderer')
                symbol_config = renderer_cfg.get("symbol", {})
                if "fill_color" in symbol_config:
                    sym.renderer.symbol.color = _to_rgb(symbol_config["fill_color"])
                if "outline_color" in symbol_config:
                    sym.renderer.symbol.outlineColor = _to_rgb(symbol_config["outline_color"])
                if "outline_width" in symbol_config:
                    sym.renderer.symbol.outlineWidth = symbol_config["outline_width"]
                if "size" in symbol_config:
                    sym.renderer.symbol.size = symbol_config["size"]

            elif renderer_type == "unique_value":
                sym.updateRenderer('UniqueValueRenderer')
                field = renderer_cfg.get("field", "")
                if field:
                    sym.renderer.fields = [field]

                default_sym_config = renderer_cfg.get("default_symbol", {})
                if default_sym_config:
                    try:
                        if "fill_color" in default_sym_config:
                            sym.renderer.defaultSymbol.color = _to_rgb(default_sym_config["fill_color"])
                        if "outline_color" in default_sym_config:
                            sym.renderer.defaultSymbol.outlineColor = _to_rgb(default_sym_config["outline_color"])
                        if "outline_width" in default_sym_config:
                            sym.renderer.defaultSymbol.outlineWidth = default_sym_config["outline_width"]
                    except Exception:
                        pass

                classes = renderer_cfg.get("classes", [])
                _log(f"  应用 {len(classes)} 个分类颜色...")
                for cls in classes:
                    try:
                        value = cls.get("value", "")
                        value_str = str(value)
                        label = cls.get("label", value)
                        sym_config = cls.get("symbol", {})

                        matched = False
                        for grp in sym.renderer.groups:
                            if matched:
                                break
                            for itm in grp.items:
                                if itm.values and itm.values[0]:
                                    itm_val = itm.values[0][0]
                                    if str(itm_val) == value_str:
                                        itm.label = label
                                        if "fill_color" in sym_config:
                                            itm.symbol.color = _to_rgb(sym_config["fill_color"])
                                        if "outline_color" in sym_config:
                                            itm.symbol.outlineColor = _to_rgb(sym_config["outline_color"])
                                        if "outline_width" in sym_config:
                                            itm.symbol.outlineWidth = sym_config["outline_width"]
                                        matched = True
                                        break
                    except Exception:
                        pass

            elif renderer_type == "graduated_colors":
                sym.updateRenderer('GraduatedColorsRenderer')
                field = renderer_cfg.get("field", "")
                if field:
                    sym.renderer.classificationField = field
                    method = renderer_cfg.get("classification_method", "natural_breaks")
                    method_map = {
                        "natural_breaks": "NaturalBreaks",
                        "equal_interval": "EqualInterval",
                        "quantile": "Quantile",
                        "geometric_interval": "GeometricInterval",
                        "standard_deviation": "StandardDeviation",
                        "defined_interval": "DefinedInterval",
                        "manual_interval": "ManualInterval"
                    }
                    if method in method_map:
                        try:
                            sym.renderer.classificationMethod = method_map[method]
                        except Exception:
                            pass
                    class_count = renderer_cfg.get("class_count", 5)
                    try:
                        sym.renderer.breakCount = class_count
                    except Exception:
                        pass
                    color_scheme = renderer_cfg.get("color_scheme", {})
                    if color_scheme:
                        try:
                            scheme_name = color_scheme.get("name", "")
                            if scheme_name:
                                color_ramps = aprx.listColorRamps(scheme_name)
                                if color_ramps:
                                    sym.renderer.colorRamp = color_ramps[0]
                        except Exception:
                            pass
                        start_color = color_scheme.get("start_color")
                        end_color = color_scheme.get("end_color")
                        if start_color and end_color:
                            try:
                                s = list(start_color[:3])
                                e = list(end_color[:3])
                                count = len(sym.renderer.classBreaks)
                                if count > 1:
                                    for i, brk in enumerate(sym.renderer.classBreaks):
                                        t = i / float(count - 1)
                                        interp = [int(s[k] + (e[k] - s[k]) * t) for k in range(3)]
                                        interp.append(100)
                                        brk.symbol.color = {'RGB': interp}
                            except Exception:
                                pass
                    outline_color = renderer_cfg.get("outline_color", [100, 100, 100, 100])
                    outline_width = renderer_cfg.get("outline_width", 1)
                    try:
                        oc_rgb = _to_rgb(outline_color)
                        for brk in sym.renderer.classBreaks:
                            if oc_rgb:
                                brk.symbol.outlineColor = oc_rgb
                            brk.symbol.outlineWidth = outline_width
                    except Exception:
                        pass

            elif renderer_type == "classed":
                sym.updateRenderer('UniqueValueRenderer')
                field = renderer_cfg.get("field", "")
                classes = renderer_cfg.get("classes", [])
                if field and classes:
                    classify_field = f"{field}_classified"
                    sym.renderer.fields = [classify_field]
                    default_sym_config = renderer_cfg.get("default_symbol", {})
                    if default_sym_config:
                        try:
                            if "fill_color" in default_sym_config:
                                sym.renderer.defaultSymbol.color = _to_rgb(default_sym_config["fill_color"])
                            if "outline_color" in default_sym_config:
                                sym.renderer.defaultSymbol.outlineColor = _to_rgb(default_sym_config["outline_color"])
                        except Exception:
                            pass
                    for cls in classes:
                        try:
                            label = cls.get("label", "")
                            sym_config = cls.get("symbol", {})
                            for grp in sym.renderer.groups:
                                for itm in grp.items:
                                    match_label = itm.values and itm.values[0] and itm.values[0][0]
                                    if match_label and (str(match_label) == str(label) or str(match_label) == str(cls.get("value", ""))):
                                        itm.label = label
                                        if "fill_color" in sym_config:
                                            fc_rgb = _to_rgb(sym_config["fill_color"])
                                            if fc_rgb:
                                                itm.symbol.color = fc_rgb
                                        if "outline_color" in sym_config:
                                            oc_rgb = _to_rgb(sym_config["outline_color"])
                                            if oc_rgb:
                                                itm.symbol.outlineColor = oc_rgb
                                        if "outline_width" in sym_config:
                                            itm.symbol.outlineWidth = sym_config["outline_width"]
                                        break
                        except Exception:
                            pass

            layer.symbology = sym
            _log(f"  [OK] 符号系统设置完成")

        except Exception as e:
            _log(f"  [FAIL] 符号系统设置失败: {e}")
            layer_warnings.append({
                "layer_id": layer_id,
                "layer_index": i,
                "feature_class": fc_path,
                "element": "符号系统",
                "reason": f"设置符号系统失败: {str(e)}"
            })

        # 设置标注
        _log(f"  设置标注 (enabled={labeling_cfg.get('enabled', False)})...")
        try:
            if labeling_cfg.get("enabled", False):
                label_field = labeling_cfg.get("field", "")
                if label_field:
                    layer.showLabels = True
                    lbl_classes = layer.listLabelClasses()
                    for lc in lbl_classes:
                        lc.visible = False
                    if lbl_classes:
                        lbl_class = lbl_classes[0]
                    else:
                        try:
                            cim_lyr = layer.getDefinition('V2')
                            new_lc = arcpy.cim.CreateCIMObjectFromClassName('CIMLabelClass', 'V2')
                            new_lc.name = "默认"
                            new_lc.visible = True
                            cim_lyr.labelClasses.append(new_lc)
                            layer.setDefinition(cim_lyr)
                            lbl_class = layer.listLabelClasses()[0]
                        except Exception:
                            lbl_class = None
                    if lbl_class:
                        lbl_class.visible = True
                        lbl_class.expression = f"$feature.{label_field}"
                        font = labeling_cfg.get("font", {})
                        if font.get("family"):
                            lbl_class.fontName = font["family"]
                        else:
                            lbl_class.fontName = "SimSun"
                        if font.get("size"):
                            lbl_class.fontSize = font["size"]
                        color = labeling_cfg.get("color", [0, 0, 0, 100])
                        lbl_class.color = {'RGB': color}
                        halo = labeling_cfg.get("halo", {})
                        if halo.get("enabled", True):
                            lbl_class.showHalo = True
                            if halo.get("color"):
                                lbl_class.haloColor = {'RGB': halo["color"]}
                            else:
                                lbl_class.haloColor = {'RGB': [255, 255, 255, 100]}
                            if halo.get("size"):
                                lbl_class.haloSize = halo["size"]
                            else:
                                lbl_class.haloSize = 1
                _log(f"  [OK] 标注设置完成")
            else:
                _log(f"  - 标注已禁用，跳过")
        except Exception as e:
            _log(f"  [FAIL] 标注设置失败: {e}")
            layer_warnings.append({
                "layer_id": layer_id,
                "layer_index": i,
                "feature_class": fc_path,
                "element": "标注",
                "reason": f"设置标注失败: {str(e)}"
            })

    # ── 判断：所有图层都失败则返回失败 ──
    _log(f"[3/9] 图层处理完成，成功添加 {len(added_layers)}/{len(layers_config)} 个图层")
    if not added_layers:
        print(json.dumps({
            "success": False,
            "error": "所有图层添加失败，图中无专题地图数据",
            "layer_errors": layer_errors
        }, ensure_ascii=False))
        sys.exit(0)

    # ── 核心任务：创建布局 ──
    page_sizes = {
        "A4": {"portrait": (210.06, 296.93), "landscape": (296.93, 210.06)},
        "A3": {"portrait": (296.93, 420.12), "landscape": (420.12, 296.93)},
        "Letter": {"portrait": (215.9, 279.4), "landscape": (279.4, 215.9)},
        "Legal": {"portrait": (215.9, 355.6), "landscape": (355.6, 215.9)},
    }
    page_size = layout_config.get("page_size", "A4")
    orientation = layout_config.get("orientation", "landscape")
    if page_size in page_sizes:
        width, height = page_sizes[page_size][orientation]
    else:
        width, height = 296.93, 210.06

    _log(f"[4/9] 创建布局 ({page_size} {orientation}, {width}x{height}mm)...")
    try:
        layout = aprx.createLayout(width, height, "MILLIMETER")
        _log("[4/9] 布局创建成功")
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": f"创建布局失败: {str(e)}",
            "added_layers_count": len(added_layers)
        }, ensure_ascii=False))
        sys.exit(0)

    # ── 核心任务：添加地图框 ──
    page_width = layout.pageWidth
    page_height = layout.pageHeight
    mf_width = page_width * 0.95
    mf_height = page_height * 0.95
    mf_x = (page_width - mf_width) / 2
    mf_y = (page_height - mf_height) / 2

    title = layout_config.get("title", "")
    if title:
        mf_height = (page_height - 10) * 0.95
        mf_y = (page_height - mf_height) / 2 - 5

    _log(f"[5/9] 创建地图框 ({mf_width:.1f}x{mf_height:.1f}mm, 位置 x={mf_x:.1f} y={mf_y:.1f})...")
    try:
        mf = layout.createMapFrame(
            arcpy.Polygon(arcpy.Array([
                arcpy.Point(mf_x, mf_y),
                arcpy.Point(mf_x + mf_width, mf_y),
                arcpy.Point(mf_x + mf_width, mf_y + mf_height),
                arcpy.Point(mf_x, mf_y + mf_height),
                arcpy.Point(mf_x, mf_y)
            ])),
            map_obj,
            "地图框"
        )
        _log("[5/9] 地图框创建成功")
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": f"创建地图框失败: {str(e)}",
            "added_layers_count": len(added_layers)
        }, ensure_ascii=False))
        sys.exit(0)

    # ── 非核心：设置地图范围 ──
    _log("[5/9] 计算并设置地图显示范围...")
    extent_warning = None
    try:
        if added_layers:
            xmins, ymins, xmaxs, ymaxs = [], [], [], []
            for lyr in added_layers:
                try:
                    lyr_ext = mf.getLayerExtent(lyr)
                    xmins.append(lyr_ext.XMin)
                    ymins.append(lyr_ext.YMin)
                    xmaxs.append(lyr_ext.XMax)
                    ymaxs.append(lyr_ext.YMax)
                except Exception:
                    continue
            if xmins:
                union_ext = arcpy.Extent(
                    min(xmins), min(ymins), max(xmaxs), max(ymaxs)
                )
                dx = union_ext.XMax - union_ext.XMin
                dy = union_ext.YMax - union_ext.YMin
                margin = layout_config.get("extent_margin", 0.10)
                mf.camera.setExtent(arcpy.Extent(
                    union_ext.XMin - dx * margin,
                    union_ext.YMin - dy * margin,
                    union_ext.XMax + dx * margin,
                    union_ext.YMax + dy * margin
                ))
                _log(f"  [OK] 地图范围设置完成（margin={margin}）")
                # ── 设置底图 ──
                _VALID_BASEMAPS = {
                    'Imagery', 'Imagery Hybrid', 'Streets', 'Topographic',
                    'Navigation', 'Streets (Night)', 'Terrain with Labels',
                    'Light Gray Canvas', 'Dark Gray Canvas', 'Outdoor',
                    'Oceans', 'National Geographic Style Map',
                    'OpenStreetMap Style', 'Topographic (Vector)',
                    'Outline Map', 'NAIP Imagery Hybrid',
                    'USGS National Map', 'USA Topo Maps',
                    'Charted Territory Map', 'Community Map',
                    'Navigation (Dark)', 'Newspaper Map',
                    'Human Geography Map', 'Human Geography Dark Map',
                    'Modern Antique Map', 'Mid-Century Map', 'Nova Map',
                    'Colored Pencil Map', 'Firefly Imagery Hybrid',
                    'Blueprint', 'Environment Map',
                    'Enhanced Contrast Map', 'Enhanced Contrast Dark Map',
                    'Navigation (Places)', 'Navigation (Dark - Places)',
                }
                basemap_name = layout_config.get("basemap_name", "")
                if basemap_name and basemap_name in _VALID_BASEMAPS:
                    try:
                        map_obj.addBasemap(basemap_name)
                        _log(f"  [OK] 底图设置完成: {basemap_name}")
                    except Exception as e:
                        _log(f"  [FAIL] 底图设置失败: {e}")
                else:
                    # 空值或不匹配可选值时，移除所有底图图层
                    if basemap_name:
                        _log(f"  [WARN] basemap_name '{basemap_name}' 不在可选列表中，移除底图")
                    else:
                        _log("  - basemap_name 为空，移除底图")
                    try:
                        for lyr in map_obj.listLayers():
                            if lyr.isBasemapLayer:
                                map_obj.removeLayer(lyr)
                        _log("  [OK] 底图已移除")
                    except Exception as e:
                        _log(f"  [FAIL] 移除底图失败: {e}")
    except Exception as e:
        extent_warning = f"设置地图范围失败: {str(e)}"
        _log(f"  [FAIL] {extent_warning}")

    element_warnings = []

    # ── 非核心：添加标题 ──
    if title:
        _log(f"[6/9] 添加标题: {title}")
        try:
            title_elem = aprx.createTextElement(
                layout,
                arcpy.Point(page_width / 2, mf_y + mf_height + 1),
                "POINT",
                title,
                24,
                "Arial",
                "Bold",
                None,
                "标题"
            )
            title_elem.setAnchor("BOTTOM_MID_POINT")
            title_elem.elementPositionX = layout.pageWidth / 2
            _log("[6/9] 标题添加成功")
        except Exception as e:
            _log(f"[6/9] [FAIL] 标题添加失败: {e}")
            element_warnings.append({
                "element": "标题",
                "reason": f"添加标题失败: {str(e)}"
            })
    else:
        _log("[6/9] 无标题配置，跳过")

    # ── 非核心：获取整饰要素样式项 ──
    _log("[6/9] 获取整饰要素样式项...")
    na_styles = aprx.listStyleItems('ArcGIS 2D', 'North_Arrow', 'ArcGIS North 2')
    sb_styles = aprx.listStyleItems('ArcGIS 2D', 'Scale_Bar', 'Alternating Scale Bar*')
    leg_styles = aprx.listStyleItems('ArcGIS 2D', 'Legend', '*')
    _log(f"  指北针样式: {len(na_styles)} 个，比例尺样式: {len(sb_styles)} 个，图例样式: {len(leg_styles)} 个")

    # ── 非核心：添加指北针 ──
    north_arrow_cfg = map_elements.get("north_arrow", {})
    if north_arrow_cfg.get("enabled", True):
        _log(f"[7/9] 添加指北针 (位置={north_arrow_cfg.get('position', 'top_left')})...")
        try:
            na_style = na_styles[0] if na_styles else None
            na_position = north_arrow_cfg.get("position", "top_left")
            na_margin_x = 0.05 * mf_width
            na_margin_y = 0.05 * mf_height
            na_size = 20.32
            na_pos_map = {
                "top_left":     ("TOP_LEFT_CORNER",     mf_x + na_margin_x,              mf_y + mf_height - na_margin_y),
                "top_right":    ("TOP_RIGHT_CORNER",    mf_x + mf_width - na_margin_x,   mf_y + mf_height - na_margin_y),
                "bottom_left":  ("BOTTOM_LEFT_CORNER",  mf_x + na_margin_x,              mf_y + na_margin_y),
                "bottom_right": ("BOTTOM_RIGHT_CORNER", mf_x + mf_width - na_margin_x,   mf_y + na_margin_y),
            }
            na_anchor, na_px, na_py = na_pos_map.get(na_position, na_pos_map["top_left"])
            na = layout.createMapSurroundElement(
                arcpy.Point(na_px, na_py),
                'NORTH_ARROW', mf, na_style
            )
            na.elementWidth = na_size
            na.elementHeight = na_size
            na.setAnchor(na_anchor)
            na.elementPositionX = na_px
            na.elementPositionY = na_py
            _log("[7/9] 指北针添加成功")
        except Exception as e:
            _log(f"[7/9] [FAIL] 指北针添加失败: {e}")
            element_warnings.append({
                "element": "指北针",
                "reason": f"添加指北针失败: {str(e)}"
            })
    else:
        _log("[7/9] 指北针已禁用，跳过")

    # ── 非核心：添加图例 ──
    legend_cfg = map_elements.get("legend", {})
    if legend_cfg.get("enabled", True):
        _log(f"[8/9] 添加图例 (位置={legend_cfg.get('position', 'bottom_left')})...")
        try:
            leg_style = leg_styles[0] if leg_styles else None
            position = legend_cfg.get("position", "bottom_left")
            margin_x = 0.05 * mf_width
            margin_y = 0.05 * mf_height
            pos_map = {
                "top_left":     ("TOP_LEFT_CORNER",     mf_x + margin_x,              mf_y + mf_height - margin_y),
                "top_right":    ("TOP_RIGHT_CORNER",    mf_x + mf_width - margin_x,   mf_y + mf_height - margin_y),
                "bottom_left":  ("BOTTOM_LEFT_CORNER",  mf_x + margin_x,              mf_y + margin_y),
                "bottom_right": ("BOTTOM_RIGHT_CORNER", mf_x + mf_width - margin_x,   mf_y + margin_y),
            }
            anchor, px, py = pos_map.get(position, pos_map["bottom_left"])

            leg = layout.createMapSurroundElement(
                arcpy.Point(px, py),
                'LEGEND', mf, leg_style
            )
            _log("  图例元素已创建，配置属性...")
            leg.title = legend_cfg.get("title", "图  例")
            leg.titleFontName = "Arial"
            leg.titleFontSize = 14
            leg.showTitle = True
            leg.elementWidth = 76.2
            leg.elementHeight = 50.8
            leg.autoSize = True
            leg.setAnchor(anchor)
            leg.elementPositionX = px
            leg.elementPositionY = py

            # 通过CIM设置边框和背景
            _log("  通过 CIM 设置图例边框和背景...")
            try:
                cim_leg = leg.getDefinition('V2')
                frame = getattr(cim_leg, 'graphicFrame', None) or getattr(cim_leg, 'frame', None)
                if frame is not None:
                    # 白色背景
                    bg_fill = arcpy.cim.CreateCIMObjectFromClassName('CIMSolidFill', 'V2')
                    bg_color = arcpy.cim.CreateCIMObjectFromClassName('CIMRGBColor', 'V2')
                    bg_color.values = [255, 255, 255, 100]
                    bg_fill.color = bg_color
                    bg_fill.enable = True
                    bg_poly = arcpy.cim.CreateCIMObjectFromClassName('CIMPolygonSymbol', 'V2')
                    bg_poly.symbolLayers = [bg_fill]
                    bg_ref = arcpy.cim.CreateCIMObjectFromClassName('CIMSymbolReference', 'V2')
                    bg_ref.symbol = bg_poly
                    frame.backgroundSymbol = bg_ref
                    frame.backgroundGapX = getattr(frame, 'borderGapX', 0)
                    frame.backgroundGapY = getattr(frame, 'borderGapY', 0)

                    # 1pt黑色边框
                    brd_stroke = arcpy.cim.CreateCIMObjectFromClassName('CIMSolidStroke', 'V2')
                    brd_color = arcpy.cim.CreateCIMObjectFromClassName('CIMRGBColor', 'V2')
                    brd_color.values = [0, 0, 0, 100]
                    brd_stroke.color = brd_color
                    brd_stroke.width = 0.3528
                    brd_stroke.enable = True
                    brd_line = arcpy.cim.CreateCIMObjectFromClassName('CIMLineSymbol', 'V2')
                    brd_line.symbolLayers = [brd_stroke]
                    brd_ref = arcpy.cim.CreateCIMObjectFromClassName('CIMSymbolReference', 'V2')
                    brd_ref.symbol = brd_line
                    frame.borderSymbol = brd_ref

                    # 隐藏所有图例项的 Headings，只显示 Label
                    if hasattr(cim_leg, 'items') and cim_leg.items:
                        for item in cim_leg.items:
                            if hasattr(item, 'showHeading'):
                                item.showHeading = False
                            if hasattr(item, 'showLabel'):
                                item.showLabel = True
                    _log("  [OK] CIM 图例边框/背景/标题设置完成")
                else:
                    _log("  - frame 为 None，跳过 CIM 设置")
                leg.setDefinition(cim_leg)
            except Exception as e:
                _log(f"  [FAIL] CIM 图例设置失败: {e}")
                traceback.print_exc()
            _log("[8/9] 图例添加成功")
        except Exception as e:
            _log(f"[8/9] [FAIL] 图例添加失败: {e}")
            element_warnings.append({
                "element": "图例",
                "reason": f"添加图例失败: {str(e)}"
            })
    else:
        _log("[8/9] 图例已禁用，跳过")

    # ── 非核心：添加比例尺 ──
    scale_bar_cfg = map_elements.get("scale_bar", {})
    if scale_bar_cfg.get("enabled", True):
        _log(f"[8/9] 添加比例尺 (位置={scale_bar_cfg.get('position', 'bottom_right')})...")
        try:
            sb_style = sb_styles[0] if sb_styles else None
            sb_position = scale_bar_cfg.get("position", "bottom_right")
            sb_margin_x = 0.05 * mf_width
            sb_margin_y = 0.05 * mf_height
            sb_width = 101.6
            sb_height = 10.16
            sb_pos_map = {
                "top_left":     ("TOP_LEFT_CORNER",     mf_x + sb_margin_x,              mf_y + mf_height - sb_margin_y),
                "top_right":    ("TOP_RIGHT_CORNER",    mf_x + mf_width - sb_margin_x,   mf_y + mf_height - sb_margin_y),
                "bottom_left":  ("BOTTOM_LEFT_CORNER",  mf_x + sb_margin_x,              mf_y + sb_margin_y),
                "bottom_right": ("BOTTOM_RIGHT_CORNER", mf_x + mf_width - sb_margin_x,   mf_y + sb_margin_y),
            }
            sb_anchor, sb_px, sb_py = sb_pos_map.get(sb_position, sb_pos_map["bottom_right"])
            sb = layout.createMapSurroundElement(
                arcpy.Point(sb_px, sb_py),
                'SCALE_BAR', mf, sb_style
            )
            sb.elementWidth = sb_width
            sb.elementHeight = sb_height
            sb.setAnchor(sb_anchor)
            sb.elementPositionX = sb_px
            sb.elementPositionY = sb_py
            _log("[8/9] 比例尺添加成功")
        except Exception as e:
            _log(f"[8/9] [FAIL] 比例尺添加失败: {e}")
            element_warnings.append({
                "element": "比例尺",
                "reason": f"添加比例尺失败: {str(e)}"
            })
    else:
        _log("[8/9] 比例尺已禁用，跳过")

    # ── 核心任务：导出PNG ──
    _log(f"[9/9] 导出 PNG 到: {output_path} (300dpi)...")
    try:
        layout.exportToPNG(output_path, resolution=300)
        _log("[9/9] [OK] PNG 导出成功")
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": f"导出PNG失败: {str(e)}",
            "added_layers_count": len(added_layers)
        }, ensure_ascii=False))
        sys.exit(0)

    # ── 汇总结果 ──
    all_warnings = []
    if extent_warning:
        all_warnings.append({"element": "地图范围", "reason": extent_warning})
    all_warnings.extend(element_warnings)
    all_warnings.extend(layer_warnings)

    result = {
        "success": True,
        "output_path": output_path,
        "message": "地图创建成功",
        "added_layers_count": len(added_layers),
        "total_layers_count": len(layers_config)
    }
    if layer_errors:
        result["layer_errors"] = layer_errors
    if all_warnings:
        result["warnings"] = all_warnings

    print(json.dumps(result, ensure_ascii=False))

except Exception as e:
    print(json.dumps({
        "success": False,
        "error": str(e),
        "traceback": traceback.format_exc()
    }, ensure_ascii=False))
