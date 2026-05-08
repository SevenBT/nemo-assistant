# 边缘吸附宽度阈值功能

## 功能说明

边缘吸附功能现在支持基于窗口宽度的智能触发条件。只有当窗口宽度小于屏幕宽度的指定比例时，才会触发边缘吸附。

## 使用场景

- **便签模式**（窄窗口，< 40% 屏幕宽度）：允许边缘吸附
- **工作模式**（宽窗口，≥ 40% 屏幕宽度）：不触发边缘吸附
- **最大化模式**：自动不触发（因为宽度接近 100%）

## 配置方式

### 1. 通过设置界面

1. 打开「设置」对话框
2. 切换到「窗口」标签页
3. 找到「吸附宽度阈值」设置项
4. 调整数值（范围：0.2 - 0.8，即 20% - 80%）
5. 点击「确定」保存

### 2. 通过配置文件

编辑 `config/app_config.json`：

```json
{
  "window": {
    "edge_snap": true,
    "edge_snap_width_threshold": 0.4
  }
}
```

## 默认值

- 默认阈值：`0.4`（40% 屏幕宽度）
- 推荐范围：`0.2` - `0.8`（20% - 80%）

## 示例

假设屏幕宽度为 1920px，阈值为 0.4（40%）：

| 窗口宽度 | 宽度比例 | 是否触发吸附 |
|---------|---------|------------|
| 440px   | 0.23    | ✓ 是       |
| 600px   | 0.31    | ✓ 是       |
| 800px   | 0.42    | ✗ 否       |
| 1800px  | 0.94    | ✗ 否       |

## 技术实现

### 核心逻辑

```python
def _is_narrow_enough_to_snap(self) -> bool:
    threshold = self._window._config.edge_snap_width_threshold
    window_width = self._window.width()
    screen_width = self._window.screen().availableGeometry().width()
    width_ratio = window_width / screen_width
    return width_ratio < threshold
```

### 调用时机

在 `EdgeSnapManager.check_position()` 中，每次窗口移动时检查：

```python
def check_position(self):
    if not self._enabled or self._snapped or self._animating:
        return
    
    # 只有窗口足够窄时才触发边缘吸附
    if not self._is_narrow_enough_to_snap():
        return
    
    # ... 其余吸附逻辑
```

## 向后兼容

- 旧配置文件没有此字段时，自动使用默认值 0.4
- 不影响现有的边缘吸附开关（`edge_snap`）

## 测试

运行测试脚本验证功能：

```bash
python test_edge_snap_width.py
```

测试覆盖：
- ✓ 默认配置加载
- ✓ 配置更新和持久化
- ✓ 宽度比例计算逻辑
- ✓ 多种窗口宽度和阈值组合
