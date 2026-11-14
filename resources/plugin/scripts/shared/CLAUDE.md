# CLAUDE.md — shared

共享工具模块。提供 ArcPy 解释器定位和脚本执行功能，供所有需要 ArcPy 的 Hook 共用。

---

## 模块

### find_arcpy.py

```python
from shared.find_arcpy import find_py_interpreter, run_arcpy_script
```

#### `find_py_interpreter() -> str | None`

定位 ArcGIS Pro Python 解释器路径。查找顺序：
1. 环境变量 `ARCGIS_PRO_PATH`
2. 默认安装路径（C:/D:/E: 盘 Program Files）
3. 用户 AppData 安装路径
4. 开始菜单快捷方式解析
5. Windows 注册表

#### `run_arcpy_script(script_code, input_data=None, timeout=120) -> dict`

通过 ArcGIS Pro Python 解释器执行 ArcPy 脚本。

**参数**：
- `script_code`：Python 脚本代码字符串
- `input_data`：可选的输入数据（通过 stdin 传递为 JSON）
- `timeout`：超时秒数（默认 120）

**返回**：
```python
{"success": bool, "result": Any, "error": str | None}
```

## 引用方式

在 Hook 脚本中添加：
```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
from find_arcpy import find_py_interpreter, run_arcpy_script
```

## 来源

从 `arcgis-mcp-server/main.py` 提取的公共逻辑，避免在多个 Hook 中重复。
