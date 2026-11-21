"""关键帧裁切动画的核心契约。

坐标与单位：
- 归一化矩形为 ``{"x": float, "y": float, "w": float, "h": float}``；
  x/y 是左上角，w/h 是宽高，均相对整帧尺寸。w/h 不得为负。
- 像素矩形为 ``{"x": int, "y": int, "w": int, "h": int}``，单位为像素；
  是否越界由 clamp_rect 处理。
- 所有时间字段 ``t`` 与参数 ``duration`` 的单位均为毫秒（ms）。
- 关键帧统一写成 ``{"t": int, "rect": 归一化矩形}``。
- 支持的缓动名固定为 ``"linear"``、``"in"``、``"out"``、``"inout"``。
- 比较容差：归一化数值 1e-9；像素坐标 0.5 像素。

本模块只使用 Python 标准库；初始状态下 8 个公开函数都是待修复的桩。
"""

import bisect
import math


class CropError(Exception):
    """裁切参数、关键帧或批量任务非法时抛出的异常。"""


def _median(values):
    """中位数（标准库未给 statistics 授权时的本地实现）。"""
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


_EASINGS = ("linear", "in", "out", "inout")


def ease(name, t):
    """返回缓动曲线在归一化时间 ``t`` 处的进度。

    支持的缓动名（固定四种）：
      - "linear": t
      - "in": t*t
      - "out": 1 - (1-t)**2
      - "inout": t*t*(3 - 2*t)，即 smoothstep，不是线性

    参数:
        name: 缓动名，必须是上述四种之一；未知名称抛 ValueError。
        t: 归一化时间。先夹到 [0, 1]；端点严格为 0.0 与 1.0。

    返回:
        [0.0, 1.0] 内的 float。t <= 0 返回 0.0，t >= 1 返回 1.0，
        四种曲线都不得在端点跳变。归一化数值比较容差 1e-9。
    """
    if name not in _EASINGS:
        raise ValueError("unknown easing: %r" % (name,))
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    if name == "linear":
        return float(t)
    if name == "in":
        return float(t * t)
    if name == "out":
        return float(1.0 - (1.0 - t) ** 2)
    # inout: smoothstep，端点严格落在 0/1 且一阶导数连续
    return float(t * t * (3.0 - 2.0 * t))


def _check_dimensions(rect):
    """归一化/像素矩形的宽高为负即非法，抛 CropError。"""
    if rect["w"] < 0 or rect["h"] < 0:
        raise CropError("rect width/height must be non-negative")


def interp_rect(a, b, t, easing="linear"):
    """在两个归一化矩形之间做缓动插值。

    先把 t 夹到 [0, 1]，再调用 ``ease(easing, t)`` 得到进度，逐字段
    线性插值到一个新字典，不修改 a/b。t=0 返回 a 的副本，t=1 返回
    b 的副本。返回的 w/h 始终大于等于 0；参数里的 w/h 为负则抛
    CropError，以免负宽高造成画面翻转。

    参数:
        a, b: 归一化矩形，w/h 必须非负。
        t: 归一化进度，可以越界，内部夹取。
        easing: "linear"/"in"/"out"/"inout" 之一，默认 "linear"。

    返回:
        新的归一化矩形 {"x","y","w","h"}，数值为 float。归一化值
        比较容差 1e-9；换算到像素时按 0.5 像素容差断言。
    """
    _check_dimensions(a)
    _check_dimensions(b)
    if t <= 0.0:
        return {key: float(a[key]) for key in ("x", "y", "w", "h")}
    if t >= 1.0:
        return {key: float(b[key]) for key in ("x", "y", "w", "h")}
    p = ease(easing, t)
    return {
        key: float(a[key] + (b[key] - a[key]) * p)
        for key in ("x", "y", "w", "h")
    }


def _validate_structure(keyframes):
    """sample_at / detect_jumps 共用的结构校验。"""
    if not keyframes:
        raise CropError("keyframes must not be empty")
    previous_t = None
    for frame in keyframes:
        rect = frame["rect"]
        _check_dimensions(rect)
        current_t = frame["t"]
        if previous_t is not None and current_t <= previous_t:
            raise CropError("keyframes must be strictly increasing in t")
        previous_t = current_t


def sample_at(keyframes, t):
    """按毫秒时间从关键帧序列采样归一化矩形。

    keyframes 必须非空并按 "t"（ms）严格递增，每项形如
    ``{"t": 100, "rect": {"x": ..., "y": ..., "w": ..., "h": ...}}``。
    - t 小于首帧时间：返回首帧 rect 的副本；
    - t 大于末帧时间：返回末帧 rect 的副本；
    - t 恰等于某帧：返回该帧 rect 的副本；
    - 两帧之间：用 linear 缓动按时间比例插值。

    端点外不得外推，结果不得越过首帧或末帧的矩形。空序列、乱序或
    重复时间、负宽高均抛 CropError；不修改输入。

    时间单位 ms；归一化值比较容差 1e-9，像素域比较容差 0.5 像素。
    """
    _validate_structure(keyframes)
    times = [frame["t"] for frame in keyframes]
    if t <= times[0]:
        # 端点外夹取首帧，不外推
        return {key: float(keyframes[0]["rect"][key])
                for key in ("x", "y", "w", "h")}
    if t >= times[-1]:
        # 端点外夹取末帧，不外推
        return {key: float(keyframes[-1]["rect"][key])
                for key in ("x", "y", "w", "h")}
    index = bisect.bisect_right(times, t)
    left = keyframes[index - 1]
    right = keyframes[index]
    span = right["t"] - left["t"]
    fraction = (t - left["t"]) / span if span > 0 else 0.0
    return interp_rect(left["rect"], right["rect"], fraction, easing="linear")


def to_pixels(norm_rect, w, h):
    """把归一化矩形转换为 w×h 像素帧上的整数矩形。

    逐字段向下取整（math.floor），禁止使用四舍五入：
      x = floor(norm_x * w)
      y = floor(norm_y * h)
      width = floor(norm_w * w)
      height = floor(norm_h * h)

    这样连续相邻矩形不会因为各自 round 而多出或少掉 1 像素。取整
    误差严格小于 1 像素；像素坐标比较容差 0.5 像素。宽高取整后可能
    为 0，由 clamp_rect 负责补到最小 1×1。

    参数:
        norm_rect: 归一化矩形，w/h 必须非负。
        w, h: 输出帧宽高，必须为正整数。

    异常:
        参数非法抛 CropError。返回 int 字典，不修改输入。
    """
    _check_dimensions(norm_rect)
    if not isinstance(w, int) or not isinstance(h, int) or w <= 0 or h <= 0:
        raise CropError("frame width/height must be positive integers")
    return {
        "x": math.floor(norm_rect["x"] * w),
        "y": math.floor(norm_rect["y"] * h),
        "w": math.floor(norm_rect["w"] * w),
        "h": math.floor(norm_rect["h"] * h),
    }


def clamp_rect(rect, w, h):
    """把像素矩形钳制到 w×h 帧内，并尽量保持请求的宽高。

    只移动左上角，不缩放宽高：
      - 目标宽高分别为 max(1, floor(rect["w"])) 与
        max(1, floor(rect["h"]))，保证最小 1×1；
      - 若目标宽高大于帧宽高，无法在不缩放的情况下放入，抛 CropError；
      - x 夹到 [0, w - 目标宽]，y 夹到 [0, h - 目标高]；宽高保持不变，
        以免裁切比例失真。

    输入宽高为负抛 CropError。返回 int 像素矩形；不修改输入。
    像素坐标比较容差 0.5 像素。
    """
    _check_dimensions(rect)
    if not isinstance(w, int) or not isinstance(h, int) or w <= 0 or h <= 0:
        raise CropError("frame width/height must be positive integers")
    target_w = max(1, math.floor(rect["w"]))
    target_h = max(1, math.floor(rect["h"]))
    if target_w > w or target_h > h:
        raise CropError("rect is larger than the frame")
    x = min(max(rect["x"], 0), w - target_w)
    y = min(max(rect["y"], 0), h - target_h)
    return {
        "x": int(x),
        "y": int(y),
        "w": int(target_w),
        "h": int(target_h),
    }


def detect_jumps(keyframes, max_speed):
    """检测关键帧序列中的速度突变，返回后一关键帧的下标列表。

    keyframes 与 sample_at 相同（非空、t 毫秒、严格递增，rect 归一化）。
    对每段 i=1..n-1 计算中心点位移速度：
        center = (rect.x + rect.w/2, rect.y + rect.h/2)
        speed_i = hypot(dx, dy) / ((t_i - t_{i-1}) / 1000.0)
    单位是“归一化单位/秒”。以全片所有段速度的中位数作为本片基准，
    当 speed_i > max_speed * median 时把 i 判为突变；max_speed 是相对
    倍数，不是固定绝对阈值，因此快镜头与慢镜头都不会被整体误报。
    中位速度 <= 0，或关键帧少于 3 个时，返回 []。

    异常:
        max_speed <= 0、时间非递增、负宽高抛 CropError。

    返回升序 list[int]；速度比较相对容差 1e-9，像素域容差 0.5 像素。
    """
    if max_speed <= 0:
        raise CropError("max_speed must be positive")
    _validate_structure(keyframes)
    if len(keyframes) < 3:
        return []
    speeds = []
    for i in range(1, len(keyframes)):
        previous = keyframes[i - 1]["rect"]
        current = keyframes[i]["rect"]
        center_prev = (previous["x"] + previous["w"] / 2.0,
                       previous["y"] + previous["h"] / 2.0)
        center_cur = (current["x"] + current["w"] / 2.0,
                      current["y"] + current["h"] / 2.0)
        dx = center_cur[0] - center_prev[0]
        dy = center_cur[1] - center_prev[1]
        dt_seconds = (keyframes[i]["t"] - keyframes[i - 1]["t"]) / 1000.0
        speeds.append(math.hypot(dx, dy) / dt_seconds)
    base = _median(speeds)
    if base <= 0:
        return []
    threshold = max_speed * base
    return [i for i, speed in enumerate(speeds, start=1) if speed > threshold]


def validate(keyframes, duration):
    """校验关键帧序列，返回人类可读的问题字符串列表。

    duration 为片段总时长（毫秒）。按以下顺序检查并追加消息：
      1. duration <= 0：立即返回 ["duration: must be positive"]，
         后续不再做范围比较，避免除零；
      2. keyframes 为空：["keyframes: empty"]；
      3. t 不在 [0, duration]：消息以 "time:" 开头；
      4. t 不大于前一帧的 t（乱序或重复）：消息以 "order:" 开头；
      5. rect w < 0：消息以 "width:" 开头；rect h < 0：以 "height:" 开头。

    每条问题一个字符串，按关键帧下标顺序追加；合法序列返回 []。
    本函数只返回问题，不抛 CropError；调用方（如 crop_batch）负责抛出。
    时间单位 ms；数值比较容差 1e-9。
    """
    if duration <= 0:
        return ["duration: must be positive"]
    if not keyframes:
        return ["keyframes: empty"]
    issues = []
    previous_t = None
    for index, frame in enumerate(keyframes):
        current_t = frame["t"]
        if current_t < 0 or current_t > duration:
            issues.append("time: frame %d t=%s outside [0, %s]"
                          % (index, current_t, duration))
        if previous_t is not None and current_t <= previous_t:
            issues.append("order: frame %d t=%s not greater than previous %s"
                          % (index, current_t, previous_t))
        previous_t = current_t
        rect = frame["rect"]
        if rect["w"] < 0:
            issues.append("width: frame %d has negative w=%s"
                          % (index, rect["w"]))
        if rect["h"] < 0:
            issues.append("height: frame %d has negative h=%s"
                          % (index, rect["h"]))
    return issues


def crop_batch(clips, config):
    """把多片关键帧批量采样成像素裁切矩形。

    参数:
        clips: 片列表，每项为 ``{"id": str, "duration": int,
               "keyframes": [{"t": int, "rect": 归一化矩形}, ...]}``。
               id 必须唯一；duration/keyframes 必须通过 validate。
        config: ``{"width": int, "height": int, "times": [int, ...]}``。
               width/height 是输出像素帧尺寸（>0），times 是毫秒采样
               时间，其顺序就是返回列表的顺序。

    处理:
        每个 clip 只能使用自己的 keyframes，分别对 times 中每个 t 调用
        sample_at、to_pixels、clamp_rect，返回
        ``{clip_id: [像素矩形, ...]}``，字典顺序与 clips 一致。

    原子性:
        先校验 config 和全部 clips，全部合法后才生成结果；任何一片非法
        （包括 duration<=0、乱序、越界、负宽高、重复 id）都抛 CropError，
        不返回部分结果，也不修改任何输入。

    像素坐标比较容差 0.5 像素；时间单位 ms。
    """
    width = config["width"]
    height = config["height"]
    times = config["times"]
    if (not isinstance(width, int) or not isinstance(height, int)
            or width <= 0 or height <= 0):
        raise CropError("config width/height must be positive integers")

    seen_ids = set()
    for clip in clips:
        if clip["id"] in seen_ids:
            raise CropError("duplicate clip id: %r" % (clip["id"],))
        seen_ids.add(clip["id"])
        # 原子性：先校验全部片，任一非法即整体失败
        if validate(clip["keyframes"], clip["duration"]):
            raise CropError("invalid clip: %r" % (clip["id"],))

    result = {}
    for clip in clips:
        # 每片只用自己的 keyframes，片之间互不串用
        frames = clip["keyframes"]
        rects = []
        for t in times:
            norm = sample_at(frames, t)
            pixels = to_pixels(norm, width, height)
            rects.append(clamp_rect(pixels, width, height))
        result[clip["id"]] = rects
    return result
