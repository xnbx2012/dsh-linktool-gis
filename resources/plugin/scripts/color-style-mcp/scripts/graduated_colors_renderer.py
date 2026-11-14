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
        "message": "分级符号系统地图创建成功"
    }))

except Exception as e:
    import traceback
    print(json.dumps({
        "success": False,
        "error": str(e),
        "traceback": traceback.format_exc()
    }))
