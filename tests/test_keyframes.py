"""关键帧裁切动画的验收测试。

所有时间均为毫秒（ms），像素矩形比较容差 0.5 像素。
初始状态下这些测试应全部因 NotImplementedError 而失败。
"""

import pytest

from cropanim.keyframes import (
    CropError,
    clamp_rect,
    crop_batch,
    detect_jumps,
    ease,
    interp_rect,
    sample_at,
    to_pixels,
    validate,
)


def _rect(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


def _centered_frames(centers, dt_ms, y=0.4, w=0.2, h=0.2):
    """按中心点横坐标构造等间距关键帧。"""
    return [
        {"t": index * dt_ms, "rect": _rect(cx - w / 2, y, w, h)}
        for index, cx in enumerate(centers)
    ]


def _assert_rect(actual, expected, abs_tol=1e-9):
    assert set(actual) == {"x", "y", "w", "h"}
    for key in ("x", "y", "w", "h"):
        assert actual[key] == pytest.approx(expected[key], abs=abs_tol)


def _snapshot(clips):
    return [
        {
            "id": clip["id"],
            "duration": clip["duration"],
            "keyframes": [
                {"t": keyframe["t"], "rect": dict(keyframe["rect"])}
                for keyframe in clip["keyframes"]
            ],
        }
        for clip in clips
    ]


def test_ease_endpoints_are_zero_and_one():
    for name in ("linear", "in", "out", "inout"):
        assert ease(name, 0.0) == pytest.approx(0.0, abs=1e-9)
        assert ease(name, 1.0) == pytest.approx(1.0, abs=1e-9)
        assert ease(name, -0.5) == pytest.approx(0.0, abs=1e-9)
        assert ease(name, 1.5) == pytest.approx(1.0, abs=1e-9)


def test_ease_inout_is_smooth_not_linear():
    quarter = ease("inout", 0.25)
    assert quarter == pytest.approx(0.15625, abs=1e-9)
    assert abs(quarter - 0.25) > 1e-6
    assert ease("inout", 0.5) == pytest.approx(0.5, abs=1e-9)
    assert ease("inout", 0.75) == pytest.approx(0.84375, abs=1e-9)


def test_interp_rect_rejects_negative_dimensions():
    a = _rect(0.0, 0.0, 0.4, 0.4)
    b = _rect(0.2, 0.2, 0.2, 0.2)

    midpoint = interp_rect(a, b, 0.5)
    assert midpoint["w"] == pytest.approx(0.3, abs=1e-9)
    assert midpoint["h"] == pytest.approx(0.3, abs=1e-9)

    beyond = interp_rect(a, b, 2.0)
    assert beyond["w"] == pytest.approx(0.2, abs=1e-9)
    assert beyond["h"] == pytest.approx(0.2, abs=1e-9)

    with pytest.raises(CropError):
        interp_rect(a, _rect(0.2, 0.2, -0.1, 0.2), 0.5)
    with pytest.raises(CropError):
        interp_rect(a, _rect(0.2, 0.2, 0.2, -0.1), 0.5)


def test_sample_at_clamps_outside_endpoints():
    frames = [
        {"t": 100, "rect": _rect(0.1, 0.2, 0.3, 0.4)},
        {"t": 900, "rect": _rect(0.5, 0.1, 0.2, 0.2)},
    ]

    before = sample_at(frames, -1000)
    after = sample_at(frames, 5000)

    _assert_rect(before, frames[0]["rect"])
    _assert_rect(after, frames[-1]["rect"])


def test_to_pixels_uses_floor_not_round():
    pixels = to_pixels(_rect(0.1, 0.2, 0.5, 0.5), 101, 99)
    assert pixels == {"x": 10, "y": 19, "w": 50, "h": 49}


def test_clamp_rect_preserves_dimensions():
    left = clamp_rect(_rect(-40, -10, 100, 50), 640, 360)
    assert (left["x"], left["y"], left["w"], left["h"]) == (0, 0, 100, 50)

    right = clamp_rect(_rect(600, 340, 100, 50), 640, 360)
    assert (right["x"], right["y"], right["w"], right["h"]) == (540, 310, 100, 50)

    tiny = clamp_rect(_rect(10, 10, 0, 0), 640, 360)
    assert (tiny["x"], tiny["y"], tiny["w"], tiny["h"]) == (10, 10, 1, 1)


def test_detect_jumps_uses_relative_speed():
    fast = _centered_frames([0.12, 0.62, 0.12, 0.62, 0.12], dt_ms=250)
    slow = _centered_frames([0.2, 0.22, 0.24, 0.26, 0.28], dt_ms=1000)
    spike = _centered_frames([0.2, 0.22, 0.24, 0.44, 0.46], dt_ms=1000)

    assert detect_jumps(fast, 1.5) == []
    assert detect_jumps(slow, 1.5) == []
    assert detect_jumps(spike, 2.5) == [3]


def test_validate_reports_unordered_keyframes():
    frames = [
        {"t": 800, "rect": _rect(0.1, 0.1, 0.2, 0.2)},
        {"t": 200, "rect": _rect(0.2, 0.2, 0.2, 0.2)},
    ]

    issues = validate(frames, 1000)

    assert any(message.startswith("order:") for message in issues)
    assert not any(message.startswith("time:") for message in issues)


def test_crop_batch_isolates_clips():
    config = {"width": 640, "height": 360, "times": [0]}
    clips = [
        {
            "id": "left",
            "duration": 1000,
            "keyframes": [
                {"t": 0, "rect": _rect(0.0, 0.1, 0.2, 0.2)},
                {"t": 1000, "rect": _rect(0.2, 0.1, 0.2, 0.2)},
            ],
        },
        {
            "id": "right",
            "duration": 1000,
            "keyframes": [
                {"t": 0, "rect": _rect(0.6, 0.1, 0.2, 0.2)},
                {"t": 1000, "rect": _rect(0.8, 0.1, 0.2, 0.2)},
            ],
        },
    ]

    result = crop_batch(clips, config)
    assert list(result) == ["left", "right"]
    assert result["left"][0]["x"] == 0
    assert result["right"][0]["x"] == 384

    bad_clips = clips + [
        {
            "id": "bad",
            "duration": 1000,
            "keyframes": [{"t": 0, "rect": _rect(0.1, 0.1, -0.2, 0.2)}],
        }
    ]
    snapshot = _snapshot(bad_clips)
    with pytest.raises(CropError):
        crop_batch(bad_clips, config)
    assert bad_clips == snapshot


def test_validate_rejects_nonpositive_duration():
    frames = [{"t": 0, "rect": _rect(0.1, 0.1, 0.2, 0.2)}]

    assert validate(frames, 0) == ["duration: must be positive"]
    assert validate(frames, -100) == ["duration: must be positive"]


def test_sample_at_t_zero_returns_first_keyframe():
    first = _rect(0.1, 0.2, 0.3, 0.4)
    frames = [
        {"t": 0, "rect": first},
        {"t": 1000, "rect": _rect(0.6, 0.5, 0.2, 0.2)},
    ]

    got = sample_at(frames, 0)

    _assert_rect(got, first)
    assert got is not first


def test_sample_at_t_duration_returns_last_keyframe():
    last = _rect(0.6, 0.5, 0.2, 0.2)
    frames = [
        {"t": 0, "rect": _rect(0.1, 0.2, 0.3, 0.4)},
        {"t": 1000, "rect": last},
    ]

    got = sample_at(frames, 1000)

    _assert_rect(got, last)
    assert got is not last


def test_single_keyframe_is_constant_across_segment():
    only = _rect(0.25, 0.25, 0.5, 0.5)
    frames = [{"t": 500, "rect": only}]

    for t in (-1000, 500, 5000):
        _assert_rect(sample_at(frames, t), only)


def test_crop_batch_zero_duration_raises_crop_error():
    clips = [
        {
            "id": "zero",
            "duration": 0,
            "keyframes": [{"t": 0, "rect": _rect(0.1, 0.1, 0.2, 0.2)}],
        }
    ]
    config = {"width": 640, "height": 360, "times": [0]}

    with pytest.raises(CropError):
        crop_batch(clips, config)


def test_crop_batch_preserves_clip_order():
    clips = [
        {
            "id": "third",
            "duration": 1000,
            "keyframes": [
                {"t": 0, "rect": _rect(0.0, 0.1, 0.2, 0.2)},
                {"t": 1000, "rect": _rect(0.4, 0.1, 0.2, 0.2)},
            ],
        },
        {
            "id": "first",
            "duration": 1000,
            "keyframes": [
                {"t": 0, "rect": _rect(0.3, 0.1, 0.2, 0.2)},
                {"t": 1000, "rect": _rect(0.7, 0.1, 0.2, 0.2)},
            ],
        },
        {
            "id": "second",
            "duration": 1000,
            "keyframes": [
                {"t": 0, "rect": _rect(0.6, 0.1, 0.2, 0.2)},
                {"t": 1000, "rect": _rect(0.1, 0.1, 0.2, 0.2)},
            ],
        },
    ]

    result = crop_batch(clips, {"width": 640, "height": 360, "times": [0, 500]})

    assert list(result) == ["third", "first", "second"]
    assert all(len(rects) == 2 for rects in result.values())
    assert result["third"][0]["x"] == 0
    assert result["first"][0]["x"] == 192
    assert result["second"][0]["x"] == 384
