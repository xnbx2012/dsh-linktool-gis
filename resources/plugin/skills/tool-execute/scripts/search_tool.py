#coding=utf-8

import json
import os
import sys

def search_arcgis_tools(query, json_file='arcgis_tool_info.json'):
    """
    在 JSON 文件中搜索包含关键词的工具。
    搜索字段：arcpy函数名、中文工具名、中文简介
    返回所有包含关键词的结果。
    """
    # 1. 检查文件是否存在
    if not os.path.exists(json_file):
        print(f"错误：找不到文件 '{json_file}'")
        print("请确保该文件与脚本在同一目录下。")
        return []

    # 2. 加载 JSON 数据
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError:
        print("错误：JSON 文件格式无效。")
        print("请确保文件内容是一个列表，例如：[{...}, {...}]")
        return []
    except Exception as e:
        print(f"读取文件时发生错误：{e}")
        return []

    # 确保数据是列表
    if not isinstance(data, list):
        print("错误：JSON 文件根节点必须是一个列表 [...]")
        return []

    # 3. 关键词搜索
    query = query.strip()

    if not query:
        return []

    # 为了忽略大小写影响（针对英文函数名），将查询词转为小写
    query_lower = query.lower()

    # 收集匹配的结果
    matched_results = []

    for item in data:
        # 获取目标字段
        func_name = item.get('arcpy 函数名', '')
        cn_tool_name = item.get('中文工具名', '')
        description = item.get('中文简介', '')

        # 检查关键词是否出现在任一字段中（不区分大小写）
        match_found = False

        if query_lower in func_name.lower():
            match_found = True
        elif query_lower in cn_tool_name.lower():
            match_found = True
        elif query_lower in description.lower():
            match_found = True

        if match_found:
            matched_results.append(item)

    # 4. 打印结果
    print(f"--- 搜索关键词：'{query}' ---")
    print(f"找到 {len(matched_results)} 条匹配结果\n")

    if not matched_results:
        print("未找到相关结果。")
    else:
        for i, item in enumerate(matched_results, 1):
            print(f"\n[结果 {i}]")
            print(f"  序号        : {item.get('序号', 'N/A')}")
            print(f"  工具名      : {item.get('工具名', 'N/A')}")
            print(f"  调用名      : {item.get('调用名', 'N/A')}")
            print(f"  arcpy 函数名 : {item.get('arcpy 函数名', 'N/A')}")
            print(f"  中文工具名  : {item.get('中文工具名', 'N/A')}")
            print(f"  中文简介    : {item.get('中文简介', 'N/A')}")
            print("-" * 40)

    # 5. 返回纯数据列表
    return matched_results

if __name__ == "__main__":
    # 检查命令行参数
    if len(sys.argv) < 2:
        print("用法：python search_tools.py <搜索关键词>")
        print("示例：python search_tools.py Clip")
        print("示例：python search_tools.py 表面信息")
        sys.exit(1)

    # 获取第一个参数作为搜索词
    search_query = sys.argv[1]
    
    # 执行搜索
    search_arcgis_tools(search_query)