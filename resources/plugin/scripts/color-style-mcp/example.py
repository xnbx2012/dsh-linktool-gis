import arcpy
import json
import sys
import os

# 读取输入参数
try:
    #input_json = sys.stdin.read()
    #params = json.loads(input_json)
    print
except Exception as e:
    print(json.dumps({
        "success": False,
        "error": f"读取输入参数失败: {str(e)}"
    }))
    sys.exit(0)

try:
    params = {
                "layout": {
                    "title": "江屯镇高标图",
                    "output_path": "D:/02_User_Files/02项目文件/20260116_LinkTool/LinkTool-ClaudeCode/test/02_WorkSpace/test.png",
                    "page_size": "A4",
                    "orientation": "landscape"
                },
                "layers": [
                    {
                        "id": "行政区名",
                        "feature_class": "D:/02_User_Files/02项目文件/20260116_LinkTool/LinkTool-ClaudeCode/test/01_DataBackup/三普耕地质量/江屯镇数据.gdb/XZQ",
                        "visible": True,
                        "renderer": {
                            "type": "simple",
                            "symbol": {
                            "type": "polygon",
                            "fill_color": [255, 200, 100, 100],
                            "outline_color": [255, 200, 100, 100],
                            "outline_width": 3
                            }
                        },
                        "labeling": {
                            "enabled": True,
                            "field": "XZQMC",
                            "font": {
                            "family": "Arial",
                            "size": 12
                            },
                            "color": [0, 0, 0, 100],
                            "halo": {
                            "color": [255, 255, 255, 100],
                            "size": 1
                            }
                        }
                    }
                ],
                "map_elements": {
                    "north_arrow": {
                    "enabled": True,
                    "position": "top_left"
                    },
                    "legend": {
                    "enabled": True,
                    "position": "bottom_left",
                    "title": "图  例"
                    },
                    "scale_bar": {
                    "enabled": True
                    }
                }
            }
    layers_config = params.get("layers", [])
    layout_config = params.get("layout", {})
    map_elements = params.get("map_elements", {})

    output_path = layout_config.get("output_path", "")
    aprx_path = r"D:\02_User_Files\02项目文件\20260116_LinkTool\LinkTool-ClaudeCode\plugin\scripts\color-style-mcp\catagraphy_project\LinkTool.aprx"

    if not layers_config:
        print(json.dumps({
            "success": False,
            "error": "缺少图层配置: layers不能为空"
        }))
        sys.exit(0)

    if not output_path:
        print(json.dumps({
            "success": False,
            "error": "缺少输出路径: layout.output_path不能为空"
        }))
        sys.exit(0)

    # 验证所有数据路径
    for layer_cfg in layers_config:
        fc_path = layer_cfg.get("feature_class", "")
        if fc_path and not arcpy.Exists(fc_path):
            print(json.dumps({
                "success": False,
                "error": f"数据路径不存在: {fc_path}"
            }))
            sys.exit(0)

    # 创建工程
    aprx = arcpy.mp.ArcGISProject(aprx_path)
    map_obj = aprx.createMap("地图", "MAP")

    # 添加所有图层并设置符号系统和标注
    added_layers = []
    for layer_cfg in layers_config:
        fc_path = layer_cfg.get("feature_class", "")
        visible = layer_cfg.get("visible", True)
        renderer_cfg = layer_cfg.get("renderer", {})
        labeling_cfg = layer_cfg.get("labeling", {})

        if not fc_path:
            continue

        layer = map_obj.addDataFromPath(fc_path)
        layer.visible = visible
        added_layers.append(layer)

        # 设置符号系统
        try:
            sym = layer.symbology
            renderer_type = renderer_cfg.get("type", "simple")

            if renderer_type == "simple":
                sym.updateRenderer('SimpleRenderer')
                symbol_config = renderer_cfg.get("symbol", {})
                if "fill_color" in symbol_config:
                    sym.renderer.symbol.color = {'RGB': symbol_config["fill_color"]}
                if "outline_color" in symbol_config:
                    sym.renderer.symbol.outlineColor = {'RGB': symbol_config["outline_color"]}
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
                            sym.renderer.defaultSymbol.color = {'RGB': default_sym_config["fill_color"]}
                        if "outline_color" in default_sym_config:
                            sym.renderer.defaultSymbol.outlineColor = {'RGB': default_sym_config["outline_color"]}
                    except Exception:
                        pass

                classes = renderer_cfg.get("classes", [])
                for cls in classes:
                    try:
                        value = cls.get("value", "")
                        label = cls.get("label", value)
                        sym_config = cls.get("symbol", {})

                        for grp in sym.renderer.groups:
                            for itm in grp.items:
                                if itm.values and itm.values[0] == value:
                                    itm.label = label
                                    if "fill_color" in sym_config:
                                        itm.symbol.color = {'RGB': sym_config["fill_color"]}
                                    if "outline_color" in sym_config:
                                        itm.symbol.outlineColor = {'RGB': sym_config["outline_color"]}
                                    if "outline_width" in sym_config:
                                        itm.symbol.outlineWidth = sym_config["outline_width"]
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

                    outline_color = renderer_cfg.get("outline_color", [100, 100, 100, 100])
                    outline_width = renderer_cfg.get("outline_width", 1)
                    try:
                        for brk in sym.renderer.classBreaks:
                            brk.symbol.outlineColor = {'RGB': outline_color}
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
                                sym.renderer.defaultSymbol.color = {'RGB': default_sym_config["fill_color"]}
                            if "outline_color" in default_sym_config:
                                sym.renderer.defaultSymbol.outlineColor = {'RGB': default_sym_config["outline_color"]}
                        except Exception:
                            pass

                    for cls in classes:
                        try:
                            label = cls.get("label", "")
                            sym_config = cls.get("symbol", {})

                            for grp in sym.renderer.groups:
                                for itm in grp.items:
                                    if itm.values and itm.values[0] == label:
                                        itm.label = label
                                        if "fill_color" in sym_config:
                                            itm.symbol.color = {'RGB': sym_config["fill_color"]}
                                        if "outline_color" in sym_config:
                                            itm.symbol.outlineColor = {'RGB': sym_config["outline_color"]}
                                        if "outline_width" in sym_config:
                                            itm.symbol.outlineWidth = sym_config["outline_width"]
                                        break
                        except Exception:
                            pass

            layer.symbology = sym

        except Exception as e:
            # 符号系统设置失败，继续
            pass

        # 设置标注
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
                        # 没有现有 LabelClass，尝试通过 CIM 创建
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
                        # 使用 Arcade 表达式（ArcGIS Pro 默认引擎）
                        lbl_class.expression = f"$feature.{label_field}"

                        # 字体设置
                        font = labeling_cfg.get("font", {})
                        if font.get("family"):
                            lbl_class.fontName = font["family"]
                        else:
                            lbl_class.fontName = "SimSun"
                        if font.get("size"):
                            lbl_class.fontSize = font["size"]

                        # 颜色设置
                        color = labeling_cfg.get("color", [0, 0, 0, 100])
                        lbl_class.color = {'RGB': color}

                        # 轮廓设置
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
        except Exception as e:
            print(json.dumps({"debug_label_error": str(e)}))
            pass

    # 页面尺寸映射（A4横版，单位：毫米）
    page_sizes = {
        "A4": (296.93, 210.06),
        "A3": (420.12, 296.93),
        "Letter": (279.4, 215.9),
    }

    # 获取页面尺寸
    page_size = layout_config.get("page_size", "A4")
    width, height = page_sizes.get(page_size, (296.93, 210.06))

    # 创建布局
    layout = aprx.createLayout(width, height, "MILLIMETER")

    # 地图框参数（单位：毫米）
    mf_x = 5
    mf_y = 5
    mf_width = 286.93
    mf_height = 190

    # 添加地图框 (使用5个点创建闭合矩形)
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

    # 设置地图范围：遍历所有已添加图层，计算联合范围并四边外扩10%作为边距
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
    except Exception:
        pass

    # 添加标题（如果提供）
    title_text = layout_config.get("title", "")
    if title_text:
        try:
            title_elem = aprx.createTextElement(
                layout,
                arcpy.Point(layout.pageWidth / 2, mf_y + mf_height + 1),
                "POINT",
                title_text,
                24,
                "Arial",
                "Bold",
                None,
                "标题"
            )
            title_elem.setAnchor("BOTTOM_MID_POINT")
            title_elem.elementPositionX = layout.pageWidth / 2
        except Exception:
            pass

    # 获取整饰要素样式项
    na_styles = aprx.listStyleItems('ArcGIS 2D', 'North_Arrow', '*')
    sb_styles = aprx.listStyleItems('ArcGIS 2D', 'Scale_Bar', '*Double Alternating*')
    leg_styles = aprx.listStyleItems('ArcGIS 2D', 'Legend', '*')

    # 添加指北针
    north_arrow_cfg = map_elements.get("north_arrow", {})
    if north_arrow_cfg.get("enabled", True):
        try:
            na_style = na_styles[0] if na_styles else None
            na = layout.createMapSurroundElement(
                arcpy.Point(mf_x + 0.05 * mf_width, mf_y + mf_height - 0.05 * mf_height - 20.32),
                'NORTH_ARROW', mf, na_style
            )
            na.elementWidth = 20.32
            na.elementHeight = 20.32
        except Exception:
            pass

    # 添加图例
    legend_cfg = map_elements.get("legend", {})
    if legend_cfg.get("enabled", True):
        try:
            leg_style = leg_styles[0] if leg_styles else None
            leg = layout.createMapSurroundElement(
                arcpy.Point(mf_x, mf_y),
                'LEGEND', mf, leg_style
            )
            leg.title = legend_cfg.get("title", "图  例")
            leg.titleFontName = "Arial"
            leg.titleFontSize = 14
            leg.showTitle = True
            leg.elementWidth = 76.2
            leg.elementHeight = 50.8
            leg.autoSize = True
            leg.setAnchor("BOTTOM_LEFT_CORNER")
            leg.elementPositionX = mf_x + 5
            leg.elementPositionY = mf_y + 5
            # 通过CIM设置边框(1pt黑色)和背景(白色)
            try:
                cim_leg = leg.getDefinition('V2')
                frame = cim_leg.frame
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
                    frame.background = bg_ref
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
                    frame.border = brd_ref
                leg.setDefinition(cim_leg)
            except Exception:
                pass
        except Exception:
            pass

    # 添加比例尺
    scale_bar_cfg = map_elements.get("scale_bar", {})
    if scale_bar_cfg.get("enabled", True):
        try:
            sb_style = sb_styles[3] if sb_styles else None
            sb = layout.createMapSurroundElement(
                arcpy.Point(mf_x + mf_width - 0.05 * mf_width - 101.6, mf_y + 0.05 * mf_height),
                'SCALE_BAR', mf, sb_style
            )
            sb.elementWidth = 101.6
            sb.elementHeight = 10.16
        except Exception:
            pass

    # 导出PNG
    layout.exportToPNG(output_path, resolution=300)

    print(json.dumps({
        "success": True,
        "output_path": output_path,
        "message": "地图创建成功"
    }))

except Exception as e:
    import traceback
    print(json.dumps({
        "success": False,
        "error": str(e),
        "traceback": traceback.format_exc()
    }))