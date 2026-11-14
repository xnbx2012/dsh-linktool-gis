"""
ArcPy制图脚本模块

封装所有通过ArcGIS Pro Python解释器执行的制图脚本。
"""


def create_simple_renderer_script() -> str:
    """创建简单符号系统的ArcPy脚本"""
    return '''
import arcpy
import json
import sys
import os

# 读取输入参数
try:
    input_json = sys.stdin.read()
    params = json.loads(input_json)
except Exception as e:
    print(json.dumps({
        "success": False,
        "error": f"读取输入参数失败: {str(e)}"
    }))
    sys.exit(0)

try:
    try:
        data_path = params["data_path"]
        style = params["style"]
        output_path = params["output_path"]
        aprx_path = params["aprx_path"]
    except KeyError as e:
        print(json.dumps({
            "success": False,
            "error": f"缺少必要参数: {str(e)}"
        }))
        sys.exit(0)

    # 验证数据路径
    try:
        if not arcpy.Exists(data_path):
            print(json.dumps({
                "success": False,
                "error": f"数据路径不存在: {data_path}"
            }))
            sys.exit(0)
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": f"验证数据路径失败: {str(e)}"
        }))
        sys.exit(0)

    try:
        # 创建临时工程
        aprx = arcpy.mp.ArcGISProject(aprx_path)
        try:
            map_obj = aprx.createMap("地图", "MAP")

            # 添加图层
            layer = map_obj.addDataFromPath(data_path)
        except Exception as e:
            print(json.dumps({
                "success": False,
                "error": f"添加图层失败: {str(e)}"
            }))
            sys.exit(0)

    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": f"创建工程失败: {str(e)}"
        }))
        sys.exit(0)

    # 设置简单符号系统
    try:
        sym = layer.symbology

        # 更新渲染器为SimpleRenderer
        sym.updateRenderer('SimpleRenderer')

        # 获取渲染器配置
        renderer = style.get("renderer", {})
        symbol_config = renderer.get("symbol", {})

        # 设置符号属性
        try:
            if "fill_color" in symbol_config:
                sym.renderer.symbol.color = {'RGB': symbol_config["fill_color"]}
            if "outline_color" in symbol_config:
                sym.renderer.symbol.outlineColor = {'RGB': symbol_config["outline_color"]}
            if "outline_width" in symbol_config:
                sym.renderer.symbol.outlineWidth = symbol_config["outline_width"]
            if "size" in symbol_config:
                sym.renderer.symbol.size = symbol_config["size"]
        except Exception:
            pass

        # 应用符号系统到图层
        layer.symbology = sym

    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": f"设置符号系统失败: {str(e)}"
        }))
        sys.exit(0)

    # 设置标注
    try:
        labeling = style.get("labeling", {})
        if labeling.get("enabled", False):
            label_field = labeling.get("field", "")
            if label_field:
                layer.showLabels = True
                for lbl_class in layer.listLabelClasses():
                    lbl_class.visible = False

                lbl_class = layer.listLabelClasses()[0]
                lbl_class.visible = True
                lbl_class.expression = f"!{label_field}!"

                # 字体设置
                font = labeling.get("font", {})
                if font.get("family"):
                    lbl_class.fontName = font["family"]
                if font.get("size"):
                    lbl_class.fontSize = font["size"]

                # 颜色设置
                color = labeling.get("color", [0, 0, 0, 100])
                lbl_class.color = {'RGB': color}

                # 轮廓设置
                halo = labeling.get("halo", {})
                if halo.get("enabled", True):
                    lbl_class.showHalo = True
                    if halo.get("color"):
                        lbl_class.haloColor = {'RGB': halo["color"]}
                    if halo.get("size"):
                        lbl_class.haloSize = halo["size"]
    except Exception as e:
        # 标注失败不影响整体流程
        pass

    # 保存输出路径
    if output_path:
        try:
            # 页面尺寸映射（A4横版，单位：毫米）
            page_sizes = {
                "A4": (296.93, 210.06),
                "A3": (420.12, 296.93),
                "Letter": (279.4, 215.9),
            }

            # 获取页面尺寸
            page_size = style.get("layout", {}).get("page_size", "A4")
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

            # 设置地图范围：获取图层范围并四边外扩10%作为边距
            ext = mf.getLayerExtent(layer)
            dx = ext.XMax - ext.XMin
            dy = ext.YMax - ext.YMin
            margin = style.get("layout", {}).get("extent_margin", 0.10)
            mf.camera.setExtent(arcpy.Extent(
                ext.XMin - dx * margin,
                ext.YMin - dy * margin,
                ext.XMax + dx * margin,
                ext.YMax + dy * margin
            ))

            # 添加标题（如果提供）
            title_text = style.get("layout", {}).get("title", "地图标题")
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

            # 添加指北针 - 地图框左上角内侧，5%边距
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

            # 添加图例 - 地图框左下角内侧，锚点重合，自适应
            try:
                leg_style = leg_styles[0] if leg_styles else None
                leg = layout.createMapSurroundElement(
                    arcpy.Point(mf_x, mf_y),
                    'LEGEND', mf, leg_style
                )
                leg.title = "图  例"
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

            # 添加比例尺 - 地图框右下角内侧，5%边距
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
        except Exception as e:
            print(json.dumps({
                "success": False,
                "error": f"导出布局失败: {str(e)}"
            }))
            sys.exit(0)

    print(json.dumps({
        "success": True,
        "output_path": output_path,
        "message": "简单符号系统地图创建成功"
    }))

except Exception as e:
    import traceback
    print(json.dumps({
        "success": False,
        "error": str(e),
        "traceback": traceback.format_exc()
    }))
'''


def create_unique_value_renderer_script() -> str:
    """创建唯一值符号系统的ArcPy脚本"""
    return '''
import arcpy
import json
import sys
import os

# 读取输入参数
try:
    input_json = sys.stdin.read()
    params = json.loads(input_json)
except Exception as e:
    print(json.dumps({
        "success": False,
        "error": f"读取输入参数失败: {str(e)}"
    }))
    sys.exit(0)

try:
    try:
        data_path = params["data_path"]
        style = params["style"]
        output_path = params["output_path"]
        aprx_path = params["aprx_path"]
    except KeyError as e:
        print(json.dumps({
            "success": False,
            "error": f"缺少必要参数: {str(e)}"
        }))
        sys.exit(0)

    # 验证数据路径
    try:
        if not arcpy.Exists(data_path):
            print(json.dumps({
                "success": False,
                "error": f"数据路径不存在: {data_path}"
            }))
            sys.exit(0)
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": f"验证数据路径失败: {str(e)}"
        }))
        sys.exit(0)

    try:
        # 创建临时工程
        aprx = arcpy.mp.ArcGISProject(aprx_path)
        map_obj = aprx.createMap("地图", "MAP")

        # 添加图层
        layer = map_obj.addDataFromPath(data_path)
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": f"创建工程或添加图层失败: {str(e)}"
        }))
        sys.exit(0)

    # 设置唯一值符号系统
    try:
        sym = layer.symbology

        # 更新渲染器为UniqueValueRenderer
        sym.updateRenderer('UniqueValueRenderer')

        # 获取渲染器配置
        renderer = style.get("renderer", {})
        field = renderer.get("field", "")

        if field:
            # 设置字段（必须是列表）
            sym.renderer.fields = [field]

            # 设置默认符号
            default_sym_config = renderer.get("default_symbol", {})
            if default_sym_config:
                try:
                    if "fill_color" in default_sym_config:
                        sym.renderer.defaultSymbol.color = {'RGB': default_sym_config["fill_color"]}
                    if "outline_color" in default_sym_config:
                        sym.renderer.defaultSymbol.outlineColor = {'RGB': default_sym_config["outline_color"]}
                except Exception:
                    pass

            # 设置类别符号
            classes = renderer.get("classes", [])
            for cls in classes:
                try:
                    value = cls.get("value", "")
                    label = cls.get("label", value)
                    sym_config = cls.get("symbol", {})

                    # 遍历组查找匹配的值
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

        # 应用符号系统到图层
        layer.symbology = sym

    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": f"设置符号系统失败: {str(e)}"
        }))
        sys.exit(0)

    # 设置标注
    try:
        labeling = style.get("labeling", {})
        if labeling.get("enabled", False):
            label_field = labeling.get("field", field)
            if label_field:
                layer.showLabels = True
                for lbl_class in layer.listLabelClasses():
                    lbl_class.visible = False

                lbl_class = layer.listLabelClasses()[0]
                lbl_class.visible = True
                lbl_class.expression = f"!{label_field}!"

                # 字体设置
                font = labeling.get("font", {})
                if font.get("family"):
                    lbl_class.fontName = font["family"]
                if font.get("size"):
                    lbl_class.fontSize = font["size"]

                # 颜色设置
                color = labeling.get("color", [0, 0, 0, 100])
                lbl_class.color = {'RGB': color}

                # 轮廓设置
                halo = labeling.get("halo", {})
                if halo.get("enabled", True):
                    lbl_class.showHalo = True
                    if halo.get("color"):
                        lbl_class.haloColor = {'RGB': halo["color"]}
                    if halo.get("size"):
                        lbl_class.haloSize = halo["size"]
    except Exception as e:
        # 标注失败不影响整体流程
        pass

    # 保存输出路径
    if output_path:
        try:
            # 页面尺寸映射（A4横版，单位：毫米）
            page_sizes = {
                "A4": (296.93, 210.06),
                "A3": (420.12, 296.93),
                "Letter": (279.4, 215.9),
            }

            # 获取页面尺寸
            page_size = style.get("layout", {}).get("page_size", "A4")
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

            # 设置地图范围：获取图层范围并四边外扩10%作为边距
            ext = mf.getLayerExtent(layer)
            dx = ext.XMax - ext.XMin
            dy = ext.YMax - ext.YMin
            margin = style.get("layout", {}).get("extent_margin", 0.10)
            mf.camera.setExtent(arcpy.Extent(
                ext.XMin - dx * margin,
                ext.YMin - dy * margin,
                ext.XMax + dx * margin,
                ext.YMax + dy * margin
            ))

            # 添加标题（如果提供）
            title_text = style.get("layout", {}).get("title", "地图标题")
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

            # 添加指北针 - 地图框左上角内侧，5%边距
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

            # 添加图例 - 地图框左下角内侧，锚点重合，自适应
            try:
                leg_style = leg_styles[0] if leg_styles else None
                leg = layout.createMapSurroundElement(
                    arcpy.Point(mf_x, mf_y),
                    'LEGEND', mf, leg_style
                )
                leg.title = "图  例"
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

            # 添加比例尺 - 地图框右下角内侧，5%边距
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
        except Exception as e:
            print(json.dumps({
                "success": False,
                "error": f"导出布局失败，请检查输出路径所在目录是否存在: {str(e)}"
            }))
            sys.exit(0)

    print(json.dumps({
        "success": True,
        "output_path": output_path,
        "message": "唯一值符号系统地图创建成功"
    }))

except Exception as e:
    import traceback
    print(json.dumps({
        "success": False,
        "error": str(e),
        "traceback": traceback.format_exc()
    }))
'''


def create_graduated_colors_renderer_script() -> str:
    """创建分级符号系统的ArcPy脚本"""
    return '''
import arcpy
import json
import sys
import os

# 读取输入参数
try:
    input_json = sys.stdin.read()
    params = json.loads(input_json)
except Exception as e:
    print(json.dumps({
        "success": False,
        "error": f"读取输入参数失败: {str(e)}"
    }))
    sys.exit(0)

try:
    try:
        data_path = params["data_path"]
        style = params["style"]
        output_path = params["output_path"]
        aprx_path = params["aprx_path"]
    except KeyError as e:
        print(json.dumps({
            "success": False,
            "error": f"缺少必要参数: {str(e)}"
        }))
        sys.exit(0)

    # 验证数据路径
    try:
        if not arcpy.Exists(data_path):
            print(json.dumps({
                "success": False,
                "error": f"数据路径不存在: {data_path}"
            }))
            sys.exit(0)
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": f"验证数据路径失败: {str(e)}"
        }))
        sys.exit(0)

    try:
        # 创建临时工程
        aprx = arcpy.mp.ArcGISProject(aprx_path)
        map_obj = aprx.createMap("地图", "MAP")

        # 添加图层
        layer = map_obj.addDataFromPath(data_path)
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": f"创建工程或添加图层失败: {str(e)}"
        }))
        sys.exit(0)

    # 设置分级符号系统
    try:
        sym = layer.symbology

        # 更新渲染器为GraduatedColorsRenderer
        sym.updateRenderer('GraduatedColorsRenderer')

        # 获取渲染器配置
        renderer = style.get("renderer", {})
        field = renderer.get("field", "")

        if field:
            # 设置分类字段
            sym.renderer.classificationField = field

            # 分级方法
            method = renderer.get("classification_method", "natural_breaks")
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

            # 分级数量
            class_count = renderer.get("class_count", 5)
            try:
                sym.renderer.breakCount = class_count
            except Exception:
                pass

            # 颜色方案 - 使用工程中的色带
            color_scheme = renderer.get("color_scheme", {})
            if color_scheme:
                try:
                    scheme_name = color_scheme.get("name", "")
                    if scheme_name:
                        # 从工程中查找色带
                        color_ramps = aprx.listColorRamps(scheme_name)
                        if color_ramps:
                            sym.renderer.colorRamp = color_ramps[0]
                except Exception:
                    pass

            # 轮廓设置
            outline_color = renderer.get("outline_color", [100, 100, 100, 100])
            outline_width = renderer.get("outline_width", 1)

            try:
                for brk in sym.renderer.classBreaks:
                    brk.symbol.outlineColor = {'RGB': outline_color}
                    brk.symbol.outlineWidth = outline_width
            except Exception:
                pass

        # 应用符号系统到图层
        layer.symbology = sym

    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": f"设置符号系统失败: {str(e)}"
        }))
        sys.exit(0)

    # 设置标注
    try:
        labeling = style.get("labeling", {})
        if labeling.get("enabled", False):
            label_field = labeling.get("field", field)
            if label_field:
                layer.showLabels = True
                for lbl_class in layer.listLabelClasses():
                    lbl_class.visible = False

                lbl_class = layer.listLabelClasses()[0]
                lbl_class.visible = True
                lbl_class.expression = f"!{label_field}!"

                # 字体设置
                font = labeling.get("font", {})
                if font.get("family"):
                    lbl_class.fontName = font["family"]
                if font.get("size"):
                    lbl_class.fontSize = font["size"]

                # 颜色设置
                color = labeling.get("color", [0, 0, 0, 100])
                lbl_class.color = {'RGB': color}

                # 轮廓设置
                halo = labeling.get("halo", {})
                if halo.get("enabled", True):
                    lbl_class.showHalo = True
                    if halo.get("color"):
                        lbl_class.haloColor = {'RGB': halo["color"]}
                    if halo.get("size"):
                        lbl_class.haloSize = halo["size"]
    except Exception as e:
        # 标注失败不影响整体流程
        pass

    # 保存输出路径
    if output_path:
        try:
            # 页面尺寸映射（A4横版，单位：毫米）
            page_sizes = {
                "A4": (296.93, 210.06),
                "A3": (420.12, 296.93),
                "Letter": (279.4, 215.9),
            }

            # 获取页面尺寸
            page_size = style.get("layout", {}).get("page_size", "A4")
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

            # 设置地图范围：获取图层范围并四边外扩10%作为边距
            ext = mf.getLayerExtent(layer)
            dx = ext.XMax - ext.XMin
            dy = ext.YMax - ext.YMin
            margin = style.get("layout", {}).get("extent_margin", 0.10)
            mf.camera.setExtent(arcpy.Extent(
                ext.XMin - dx * margin,
                ext.YMin - dy * margin,
                ext.XMax + dx * margin,
                ext.YMax + dy * margin
            ))

            # 添加标题（如果提供）
            title_text = style.get("layout", {}).get("title", "地图标题")
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

            # 添加指北针 - 地图框左上角内侧，5%边距
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

            # 添加图例 - 地图框左下角内侧，锚点重合，自适应
            try:
                leg_style = leg_styles[0] if leg_styles else None
                leg = layout.createMapSurroundElement(
                    arcpy.Point(mf_x, mf_y),
                    'LEGEND', mf, leg_style
                )
                leg.title = "图  例"
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

            # 添加比例尺 - 地图框右下角内侧，5%边距
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
        except Exception as e:
            print(json.dumps({
                "success": False,
                "error": f"导出布局失败: {str(e)}"
            }))
            sys.exit(0)

    print(json.dumps({
        "success": True,
        "output_path": output_path,
        "message": "分级符号系统地图创建成功"
    }))

except Exception as e:
    import traceback
    print(json.dumps({
        "success": False,
        "error": str(e),
        "traceback": traceback.format_exc()
    }))
'''


def create_classed_renderer_script() -> str:
    """创建分类符号系统的ArcPy脚本"""
    return '''
import arcpy
import json
import sys
import os

# 读取输入参数
try:
    input_json = sys.stdin.read()
    params = json.loads(input_json)
except Exception as e:
    print(json.dumps({
        "success": False,
        "error": f"读取输入参数失败: {str(e)}"
    }))
    sys.exit(0)

try:
    try:
        data_path = params["data_path"]
        style = params["style"]
        output_path = params["output_path"]
    except KeyError as e:
        print(json.dumps({
            "success": False,
            "error": f"缺少必要参数: {str(e)}"
        }))
        sys.exit(0)

    # 验证数据路径
    try:
        if not arcpy.Exists(data_path):
            print(json.dumps({
                "success": False,
                "error": f"数据路径不存在: {data_path}"
            }))
            sys.exit(0)
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": f"验证数据路径失败: {str(e)}"
        }))
        sys.exit(0)

    try:
        # 创建临时工程
        aprx = arcpy.mp.ArcGISProject("D:/Color-Style/LinkToolProject/LinkToolProject.aprx")
        map_obj = aprx.createMap("地图", "MAP")

        # 添加图层
        layer = map_obj.addDataFromPath(data_path)
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": f"创建工程或添加图层失败: {str(e)}"
        }))
        sys.exit(0)

    # 设置分类符号系统（使用唯一值渲染器）
    try:
        sym = layer.symbology

        # 更新渲染器为UniqueValueRenderer
        sym.updateRenderer('UniqueValueRenderer')

        # 获取渲染器配置
        renderer = style.get("renderer", {})
        field = renderer.get("field", "")
        classes = renderer.get("classes", [])

        if classes:
            # 使用分类字段
            classify_field = f"{field}_classified"

            # 设置字段（必须是列表）
            sym.renderer.fields = [classify_field]

            # 设置默认符号
            default_sym_config = renderer.get("default_symbol", {})
            if default_sym_config:
                try:
                    if "fill_color" in default_sym_config:
                        sym.renderer.defaultSymbol.color = {'RGB': default_sym_config["fill_color"]}
                    if "outline_color" in default_sym_config:
                        sym.renderer.defaultSymbol.outlineColor = {'RGB': default_sym_config["outline_color"]}
                except Exception:
                    pass

            # 设置类别符号
            for cls in classes:
                try:
                    label = cls.get("label", "")
                    sym_config = cls.get("symbol", {})

                    # 遍历组查找匹配的值
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

        # 应用符号系统到图层
        layer.symbology = sym

    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": f"设置符号系统失败: {str(e)}"
        }))
        sys.exit(0)

    # 设置标注
    try:
        labeling = style.get("labeling", {})
        if labeling.get("enabled", False):
            label_field = labeling.get("field", field)
            if label_field:
                layer.showLabels = True
                for lbl_class in layer.listLabelClasses():
                    lbl_class.visible = False

                lbl_class = layer.listLabelClasses()[0]
                lbl_class.visible = True
                lbl_class.expression = f"!{label_field}!"

                # 字体设置
                font = labeling.get("font", {})
                if font.get("family"):
                    lbl_class.fontName = font["family"]
                if font.get("size"):
                    lbl_class.fontSize = font["size"]

                # 颜色设置
                color = labeling.get("color", [0, 0, 0, 100])
                lbl_class.color = {'RGB': color}

                # 轮廓设置
                halo = labeling.get("halo", {})
                if halo.get("enabled", True):
                    lbl_class.showHalo = True
                    if halo.get("color"):
                        lbl_class.haloColor = {'RGB': halo["color"]}
                    if halo.get("size"):
                        lbl_class.haloSize = halo["size"]
    except Exception as e:
        # 标注失败不影响整体流程
        pass

    # 保存输出路径
    if output_path:
        try:
            # 页面尺寸映射（A4横版，单位：毫米）
            page_sizes = {
                "A4": (296.93, 210.06),
                "A3": (420.12, 296.93),
                "Letter": (279.4, 215.9),
            }

            # 获取页面尺寸
            page_size = style.get("layout", {}).get("page_size", "A4")
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

            # 设置地图范围：获取图层范围并四边外扩10%作为边距
            ext = mf.getLayerExtent(layer)
            dx = ext.XMax - ext.XMin
            dy = ext.YMax - ext.YMin
            margin = style.get("layout", {}).get("extent_margin", 0.10)
            mf.camera.setExtent(arcpy.Extent(
                ext.XMin - dx * margin,
                ext.YMin - dy * margin,
                ext.XMax + dx * margin,
                ext.YMax + dy * margin
            ))

            # 添加标题（如果提供）
            title_text = style.get("layout", {}).get("title", "地图标题")
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

            # 添加指北针 - 地图框左上角内侧，5%边距
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

            # 添加图例 - 地图框左下角内侧，锚点重合，自适应
            try:
                leg_style = leg_styles[0] if leg_styles else None
                leg = layout.createMapSurroundElement(
                    arcpy.Point(mf_x, mf_y),
                    'LEGEND', mf, leg_style
                )
                leg.title = "图  例"
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

            # 添加比例尺 - 地图框右下角内侧，5%边距
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
        except Exception as e:
            print(json.dumps({
                "success": False,
                "error": f"导出布局失败: {str(e)}"
            }))
            sys.exit(0)

    print(json.dumps({
        "success": True,
        "output_path": output_path,
        "message": "分类符号系统地图创建成功"
    }))

except Exception as e:
    import traceback
    print(json.dumps({
        "success": False,
        "error": str(e),
        "traceback": traceback.format_exc()
    }))
'''


def create_layout_export_script() -> str:
    """创建完整布局导出的ArcPy脚本（包含指北针、图例、比例尺）"""
    return '''
import arcpy
import json
import sys
import os

# 读取输入参数
try:
    input_json = sys.stdin.read()
    params = json.loads(input_json)
except Exception as e:
    print(json.dumps({
        "success": False,
        "error": f"读取输入参数失败: {str(e)}"
    }))
    sys.exit(0)

try:
    try:
        data_path = params["data_path"]
        style = params["style"]
        output_path = params["output_path"]
    except KeyError as e:
        print(json.dumps({
            "success": False,
            "error": f"缺少必要参数: {str(e)}"
        }))
        sys.exit(0)

    # 验证数据路径
    try:
        if not arcpy.Exists(data_path):
            print(json.dumps({
                "success": False,
                "error": f"数据路径不存在: {data_path}"
            }))
            sys.exit(0)
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": f"验证数据路径失败: {str(e)}"
        }))
        sys.exit(0)

    try:
        # 创建临时工程
        aprx = arcpy.mp.ArcGISProject("D:/Color-Style/LinkToolProject/LinkToolProject.aprx")
        map_obj = aprx.createMap("地图", "MAP")

        # 添加图层
        layer = map_obj.addDataFromPath(data_path)
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": f"创建工程或添加图层失败: {str(e)}"
        }))
        sys.exit(0)

    # 设置符号系统（根据类型）
    try:
        sym = layer.symbology
        renderer = style.get("renderer", {})
        renderer_type = renderer.get("type", "simple")

        if renderer_type == "simple":
            sym.updateRenderer('SimpleRenderer')
            # 设置符号
            symbol_config = renderer.get("symbol", {})
            if "fill_color" in symbol_config:
                sym.renderer.symbol.color = {'RGB': symbol_config["fill_color"]}
            if "outline_color" in symbol_config:
                sym.renderer.symbol.outlineColor = {'RGB': symbol_config["outline_color"]}

        elif renderer_type == "unique_value":
            sym.updateRenderer('UniqueValueRenderer')
            field = renderer.get("field", "")
            if field:
                sym.renderer.fields = [field]

        elif renderer_type == "graduated_colors":
            sym.updateRenderer('GraduatedColorsRenderer')
            field = renderer.get("field", "")
            if field:
                sym.renderer.classificationField = field

        elif renderer_type == "classed":
            sym.updateRenderer('UniqueValueRenderer')
            field = renderer.get("field", "")
            if field:
                sym.renderer.fields = [f"{field}_classified"]

        layer.symbology = sym
    except Exception as e:
        # 符号系统设置失败，继续执行
        pass

    # 设置标注
    try:
        labeling = style.get("labeling", {})
        if labeling.get("enabled", False):
            field = renderer.get("field", "")
            label_field = labeling.get("field", field)
            if label_field:
                layer.showLabels = True
                for lbl_class in layer.listLabelClasses():
                    lbl_class.visible = False

                lbl_class = layer.listLabelClasses()[0]
                lbl_class.visible = True
                lbl_class.expression = f"!{label_field}!"

                # 字体设置 - 宋体
                font = labeling.get("font", {})
                if font.get("family"):
                    lbl_class.fontName = font["family"]
                else:
                    lbl_class.fontName = "SimSun"
                if font.get("size"):
                    lbl_class.fontSize = font["size"]

                # 颜色设置 - 黑色
                color = labeling.get("color", [0, 0, 0, 100])
                lbl_class.color = {'RGB': color}

                # 轮廓设置 - 白色
                halo = labeling.get("halo", {})
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
        # 标注失败不影响整体流程
        pass

    # 获取布局配置
    try:
        layout_config = style.get("layout", {})
        page_size = layout_config.get("page_size", "A4")
        orientation = layout_config.get("orientation", "landscape")
        title = layout_config.get("title", "")

        if not output_path:
            print(json.dumps({
                "success": False,
                "error": "未指定输出路径"
            }))
            sys.exit(0)

        # 页面尺寸映射（单位：毫米）
        page_sizes = {
            "A4": {"portrait": (210.06, 296.93), "landscape": (296.93, 210.06)},
            "A3": {"portrait": (296.93, 420.12), "landscape": (420.12, 296.93)},
            "Letter": {"portrait": (215.9, 279.4), "landscape": (279.4, 215.9)},
            "Legal": {"portrait": (215.9, 355.6), "landscape": (355.6, 215.9)},
        }

        # 获取页面尺寸
        if page_size in page_sizes:
            width, height = page_sizes[page_size][orientation]
        else:
            # 默认A4横版
            width, height = 296.93, 210.06

        # 创建布局
        layout = aprx.createLayout(width, height, "MILLIMETER")

        # 添加地图框
        page_width = layout.pageWidth
        page_height = layout.pageHeight

        # 创建地图框（居中，单位：毫米）
        mf_width = page_width * 0.8
        mf_height = page_height * 0.7
        mf_x = (page_width - mf_width) / 2
        mf_y = (page_height - mf_height) / 2

        # 使用5个点创建闭合矩形
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

        # 设置地图范围以适应所有数据
        mf.camera.setExtent(mf.getLayerExtent(layer))

        # 添加标题（如果提供）
        if title:
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
            except Exception:
                pass

        # 获取整饰要素样式项
        na_styles = aprx.listStyleItems('ArcGIS 2D', 'North_Arrow', '*')
        sb_styles = aprx.listStyleItems('ArcGIS 2D', 'Scale_Bar', '*Double Alternating*')
        leg_styles = aprx.listStyleItems('ArcGIS 2D', 'Legend', '*')

        # 添加指北针 - 地图框左上角内侧，5%边距
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

        # 添加图例 - 地图框左下角内侧，锚点重合，自适应
        try:
            leg_style = leg_styles[0] if leg_styles else None
            leg = layout.createMapSurroundElement(
                arcpy.Point(mf_x, mf_y),
                'LEGEND', mf, leg_style
            )
            leg.title = "图  例"
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

        # 添加比例尺 - 地图框右下角内侧，5%边距
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

        # 导出PNG (300dpi)
        layout.exportToPNG(output_path, resolution=300)

        print(json.dumps({
            "success": True,
            "output_path": output_path,
            "message": "地图创建成功"
        }))
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": f"创建布局失败: {str(e)}"
        }))
        sys.exit(0)

except Exception as e:
    import traceback
    print(json.dumps({
        "success": False,
        "error": str(e),
        "traceback": traceback.format_exc()
    }))
'''


def create_unified_map_script() -> str:
    """创建统一的多图层地图ArcPy脚本（含分层错误处理）"""
    return '''
import arcpy
import json
import sys
import os
import traceback

# ── 核心任务：读取输入参数 ──
try:
    input_json = sys.stdin.read()
    params = json.loads(input_json)
except Exception as e:
    print(json.dumps({
        "success": False,
        "error": f"读取输入参数失败: {str(e)}"
    }))
    sys.exit(0)

try:
    layers_config = params.get("layers", [])
    layout_config = params.get("layout", {})
    map_elements = params.get("map_elements", {})

    output_path = layout_config.get("output_path", "")
    aprx_path = params.get("aprx_path", "")

    # ── 核心任务：校验必要配置 ──
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

    # ── 核心任务：创建工程 ──
    try:
        aprx = arcpy.mp.ArcGISProject(aprx_path)
        map_obj = aprx.createMap("地图", "MAP")
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": f"创建ArcGIS工程失败: {str(e)}"
        }))
        sys.exit(0)

    # ── 逐图层处理（收集各图层的成功/失败信息） ──
    added_layers = []
    layer_errors = []    # 导致图层完全无法添加的错误
    layer_warnings = []  # 图层添加成功但符号系统/标注设置失败

    for i, layer_cfg in enumerate(layers_config):
        layer_id = layer_cfg.get("id", f"layer_{i}")
        fc_path = layer_cfg.get("feature_class", "")
        visible = layer_cfg.get("visible", True)
        renderer_cfg = layer_cfg.get("renderer", {})
        labeling_cfg = layer_cfg.get("labeling", {})

        if not fc_path:
            layer_errors.append({
                "layer_id": layer_id,
                "layer_index": i,
                "reason": "feature_class为空"
            })
            continue

        # 验证数据路径
        try:
            if not arcpy.Exists(fc_path):
                layer_errors.append({
                    "layer_id": layer_id,
                    "layer_index": i,
                    "feature_class": fc_path,
                    "reason": f"数据路径不存在: {fc_path}"
                })
                continue
        except Exception as e:
            layer_errors.append({
                "layer_id": layer_id,
                "layer_index": i,
                "feature_class": fc_path,
                "reason": f"验证数据路径失败: {str(e)}"
            })
            continue

        # 添加图层
        try:
            layer = map_obj.addDataFromPath(fc_path)
            layer.visible = visible
            added_layers.append(layer)
        except Exception as e:
            layer_errors.append({
                "layer_id": layer_id,
                "layer_index": i,
                "feature_class": fc_path,
                "reason": f"添加图层失败: {str(e)}"
            })
            continue

        # 设置符号系统（非核心：失败时记录warning，不影响图层存在）
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
                    custom_colors = []
                    if color_scheme:
                        try:
                            def _normalize_rgba(color):
                                if not isinstance(color, (list, tuple)) or len(color) not in (3, 4):
                                    return None
                                rgba = []
                                for idx, value in enumerate(color):
                                    try:
                                        number = float(value)
                                    except Exception:
                                        return None
                                    if idx < 3:
                                        rgba.append(max(0, min(255, int(round(number)))))
                                    else:
                                        rgba.append(max(0, min(100, int(round(number)))))
                                if len(rgba) == 3:
                                    rgba.append(100)
                                return rgba

                            def _interpolate_colors(start_color, end_color, count):
                                if count <= 1:
                                    return [start_color]
                                colors = []
                                for idx in range(count):
                                    ratio = idx / (count - 1)
                                    colors.append([
                                        int(round(start_color[channel] + (end_color[channel] - start_color[channel]) * ratio))
                                        for channel in range(4)
                                    ])
                                return colors

                            colors = color_scheme.get("colors", [])
                            if isinstance(colors, list):
                                custom_colors = [c for c in (_normalize_rgba(color) for color in colors) if c]

                            if not custom_colors:
                                start_color = _normalize_rgba(color_scheme.get("start_color"))
                                end_color = _normalize_rgba(color_scheme.get("end_color"))
                                if start_color and end_color:
                                    custom_colors = _interpolate_colors(start_color, end_color, class_count)

                            if custom_colors:
                                class_breaks = list(sym.renderer.classBreaks)
                                if len(custom_colors) == 1 and len(class_breaks) > 1:
                                    custom_colors = custom_colors * len(class_breaks)
                                elif len(custom_colors) != len(class_breaks) and len(custom_colors) >= 2:
                                    custom_colors = _interpolate_colors(
                                        custom_colors[0], custom_colors[-1], len(class_breaks)
                                    )
                                for idx, brk in enumerate(class_breaks):
                                    brk.symbol.color = {'RGB': custom_colors[min(idx, len(custom_colors) - 1)]}
                            else:
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
            layer_warnings.append({
                "layer_id": layer_id,
                "layer_index": i,
                "feature_class": fc_path,
                "element": "符号系统",
                "reason": f"设置符号系统失败: {str(e)}"
            })

        # 设置标注（非核心：失败时记录warning）
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
        except Exception as e:
            layer_warnings.append({
                "layer_id": layer_id,
                "layer_index": i,
                "feature_class": fc_path,
                "element": "标注",
                "reason": f"设置标注失败: {str(e)}"
            })

    # ── 判断：所有图层都失败则返回失败 ──
    if not added_layers:
        print(json.dumps({
            "success": False,
            "error": "所有图层添加失败，图中无专题地图数据",
            "layer_errors": layer_errors
        }, ensure_ascii=False))
        sys.exit(0)

    # ── 核心任务：创建布局 ──
    page_sizes = {
        "A4": (296.93, 210.06),
        "A3": (420.12, 296.93),
        "Letter": (279.4, 215.9),
    }
    page_size = layout_config.get("page_size", "A4")
    width, height = page_sizes.get(page_size, (296.93, 210.06))

    try:
        layout = aprx.createLayout(width, height, "MILLIMETER")
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": f"创建布局失败: {str(e)}",
            "added_layers_count": len(added_layers)
        }, ensure_ascii=False))
        sys.exit(0)

    # ── 核心任务：添加地图框 ──
    mf_x = 5
    mf_y = 5
    mf_width = 286.93
    mf_height = 190

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
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": f"创建地图框失败: {str(e)}",
            "added_layers_count": len(added_layers)
        }, ensure_ascii=False))
        sys.exit(0)

    # ── 非核心：设置地图范围 ──
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
    except Exception as e:
        extent_warning = f"设置地图范围失败: {str(e)}"

    element_warnings = []

    # ── 非核心：添加标题 ──
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
        except Exception as e:
            element_warnings.append({
                "element": "标题",
                "reason": f"添加标题失败: {str(e)}"
            })

    # ── 非核心：获取整饰要素样式项 ──
    na_styles = aprx.listStyleItems('ArcGIS 2D', 'North_Arrow', '*')
    sb_styles = aprx.listStyleItems('ArcGIS 2D', 'Scale_Bar', '*Double Alternating*')
    leg_styles = aprx.listStyleItems('ArcGIS 2D', 'Legend', '*')

    # ── 非核心：添加指北针 ──
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
        except Exception as e:
            element_warnings.append({
                "element": "指北针",
                "reason": f"添加指北针失败: {str(e)}"
            })

    # ── 非核心：添加图例 ──
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
            try:
                cim_leg = leg.getDefinition('V2')
                frame = cim_leg.frame
                if frame is not None:
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
        except Exception as e:
            element_warnings.append({
                "element": "图例",
                "reason": f"添加图例失败: {str(e)}"
            })

    # ── 非核心：添加比例尺 ──
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
        except Exception as e:
            element_warnings.append({
                "element": "比例尺",
                "reason": f"添加比例尺失败: {str(e)}"
            })

    # ── 核心任务：导出PNG ──
    try:
        layout.exportToPNG(output_path, resolution=300)
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": f"导出PNG失败: {str(e)}",
            "added_layers_count": len(added_layers)
        }, ensure_ascii=False))
        sys.exit(0)

    # ── 汇总所有警告 ──
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
    }))
'''
