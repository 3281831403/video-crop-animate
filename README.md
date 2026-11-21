# video-crop-animate

## 题面

给短视频加关键帧裁切后，镜头一顿一顿、还偶尔翻转：缓动端点不回 0/1，跳变；inout 用线性，观感生硬；插值允许负宽高，画面翻转；端点外外推，走出画面；归一化转像素用四舍五入，尺寸差 1；钳制改变宽高，比例失真；突变检测用固定阈值，快慢镜头都误报；乱序关键帧不报错，插值反向；批量共用关键帧，片之间串；duration<=0 不校验，除零。cropanim/keyframes.py 是核心，tests/test_keyframes.py 15个红。要修的是：让缓动端点严格回到 0/1，inout 使用平滑曲线，插值宽高始终非负，端点外夹取首末帧，像素转换向下取整，钳制时保持宽高，按片段内相对速度检测突变，校验乱序与越界时间，批量按片隔离关键帧，duration<=0 抛 CropError。

## 字段表

| 字段 | 取值 |
| --- | --- |
| 所属领域 | 游戏、图形与多媒体 |
| 子方向 | 音视频处理 |
| 任务类型 | Bugfix |
| 语言/框架 | Python 3, pytest |
| 环境可复现等级 | 无外部依赖 |

## 运行

```powershell
cd D:\gsb-20261119\video-crop-animate
python -m pytest tests -q
```

初始仓库应恰好输出 `15 failed`，并且没有 collection error、import error 或 syntax error。修正 `cropanim/keyframes.py` 后测试应全部通过。

## 约束

- `tests/test_keyframes.py` 不可修改，测试就是验收契约。
- 只使用 Python 标准库（`math`、`bisect`）与 `pytest`，离线运行，不使用随机数。
- 只实现 `cropanim/keyframes.py` 中的 8 个桩函数。
