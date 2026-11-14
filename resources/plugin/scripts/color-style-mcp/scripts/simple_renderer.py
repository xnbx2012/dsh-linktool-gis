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
        aprx = arcpy.mp.ArcGISProject("C:/Users/HP/Documents/ArcGIS/Projects/MyProject1/MyProject1.aprx")
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
            # 页面尺寸映射（A4横版，单位：英寸）
            page_sizes = {
                "A4": (11.69, 8.27),
                "A3": (16.54, 11.69),
                "Letter": (11, 8.5),
            }

            # 获取页面尺寸
            page_size = style.get("layout", {}).get("page_size", "A4")
            width, height = page_sizes.get(page_size, (11.69, 8.27))

            # 创建布局
            layout = aprx.createLayout(width, height, "INCH")

            # 添加地图框 (使用5个点创建闭合矩形)
            mf = layout.createMapFrame(
                arcpy.Polygon(arcpy.Array([
                    arcpy.Point(0.5, 0.5),
                    arcpy.Point(10, 0.5),
                    arcpy.Point(10, 7.5),
                    arcpy.Point(0.5, 7.5),
                    arcpy.Point(0.5, 0.5)
                ])),
                map_obj,
                "地图框"
            )

            # 设置地图范围以适应所有数据
            mf.camera.setExtent(mf.getLayerExtent(layer))

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
