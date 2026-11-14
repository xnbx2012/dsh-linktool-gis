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
        aprx = arcpy.mp.ArcGISProject("DEFAULT")
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

        # 页面尺寸映射（单位：英寸）
        page_sizes = {
            "A4": {"portrait": (8.27, 11.69), "landscape": (11.69, 8.27)},
            "A3": {"portrait": (11.69, 16.54), "landscape": (16.54, 11.69)},
            "Letter": {"portrait": (8.5, 11), "landscape": (11, 8.5)},
            "Legal": {"portrait": (8.5, 14), "landscape": (14, 8.5)},
        }

        # 获取页面尺寸
        if page_size in page_sizes:
            width, height = page_sizes[page_size][orientation]
        else:
            # 默认A4横版
            width, height = 11.69, 8.27

        # 创建布局
        layout = aprx.createLayout(width, height, "INCH")

        # 添加地图框
        page_width = layout.pageWidth
        page_height = layout.pageHeight

        # 创建地图框（居中）
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

        # 添加标题
        if title:
            try:
                title_text = layout.createTextElement(
                    arcpy.Point(page_width / 2, page_height - 1),
                    title,
                    "标题",
                    "SimSun",  # 宋体
                    24
                )
                title_text.textSymbol.fontSize = 24
                title_text.textSymbol.fontName = "SimSun"
                # 居中对齐
                title_text.anchor = "middle"
                title_text.elementPositionX = page_width / 2
            except Exception:
                pass

        # 添加地图元素
        map_elements = style.get("map_elements", {})

        # 添加指北针
        try:
            north_arrow = map_elements.get("north_arrow", {})
            if north_arrow.get("enabled", True):
                position = north_arrow.get("position", "top_right")

                if position == "top_left":
                    na_x = 1
                    na_y = page_height - 2
                else:  # top_right
                    na_x = page_width - 2
                    na_y = page_height - 2

                # 创建指北针
                na = layout.createMapSurroundElement(
                    arcpy.Point(na_x, na_y),
                    "North Arrow",
                    mf,
                    "指北针"
                )
                na.elementWidth = 1
                na.elementHeight = 1
        except Exception:
            pass

        # 添加图例
        try:
            legend = map_elements.get("legend", {})
            if legend.get("enabled", True):
                position = legend.get("position", "bottom_left")
                legend_title = legend.get("title", "图  例")

                if position == "bottom_left":
                    leg_x = 0.5
                    leg_y = 0.5
                else:  # bottom_right
                    leg_x = page_width - 4
                    leg_y = 0.5

                # 创建图例
                leg = layout.createMapSurroundElement(
                    arcpy.Point(leg_x, leg_y),
                    "Legend",
                    mf,
                    "图例"
                )
                leg.elementWidth = 3
                leg.elementHeight = 3
                leg.title = legend_title
                leg.titleFontName = "SimSun"
                leg.titleFontSize = 14
        except Exception:
            pass

        # 添加比例尺
        try:
            scale_bar = map_elements.get("scale_bar", {})
            if scale_bar.get("enabled", True):
                sb_x = page_width / 2 - 2.5
                sb_y = 0.5

                # 创建比例尺
                sb = layout.createMapSurroundElement(
                    arcpy.Point(sb_x, sb_y),
                    "Scale Bar",
                    mf,
                    "比例尺"
                )
                sb.elementWidth = 5
                sb.elementHeight = 0.5
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
