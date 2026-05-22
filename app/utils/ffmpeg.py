"""
FFmpeg 统一操作封装
目标：减少魔法字符串、支持快速路径、统一错误处理
"""

import subprocess
import uuid
import random
import re
import os
from pathlib import Path
from typing import List, Optional, Dict, Any
from loguru import logger

from app.utils.ffmpeg_utils import get_ffmpeg_path


class FFmpegError(Exception):
    """FFmpeg 执行异常"""
    pass


def run_ffmpeg(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    """统一执行 ffmpeg 命令"""
    try:
        result = subprocess.run(
            cmd,
            check=check,
            capture_output=True,
            text=True
        )
        return result
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg 执行失败: {e.stderr}")
        raise FFmpegError(f"FFmpeg failed: {e.stderr}") from e


def build_base_cmd(input_path: str, output_path: str) -> List[str]:
    """构建基础命令"""
    return [get_ffmpeg_path(), "-y", "-i", input_path, output_path]


def cut_segment(
    input_path: str,
    output_path: str,
    start_time: float,
    duration: float,
    use_copy: bool = True
) -> bool:
    """
    切割视频片段
    优先尝试 -c copy，失败则重编码
    """
    cmd_copy = [
        get_ffmpeg_path(), "-y",
        "-ss", str(start_time),
        "-i", input_path,
        "-t", str(duration),
        "-c", "copy",
        output_path
    ]

    if use_copy:
        try:
            run_ffmpeg(cmd_copy)
            return True
        except FFmpegError:
            logger.warning("快速复制失败，降级到重编码")

    # 降级重编码
    cmd_reencode = [
        get_ffmpeg_path(), "-y",
        "-ss", str(start_time),
        "-i", input_path,
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac",
        output_path
    ]
    run_ffmpeg(cmd_reencode)
    return False


def generate_dedup_params() -> Dict[str, Any]:
    """
    生成去重参数：微变速、微缩放、对比度与亮度微调
    """
    return {
        "speed_factor": round(random.uniform(0.996, 1.004), 4),
        "contrast": round(random.uniform(0.99, 1.01), 4),
        "brightness": round(random.uniform(-0.01, 0.01), 4),
        "scale_factor": round(random.uniform(0.982, 0.988), 4),
    }


def srt_time_to_seconds(srt_time_str: str) -> float:
    """
    将 SRT 时间字符串 (e.g. "00:01:23,456" 或 "00:01:23.456") 转换为秒数
    """
    time_str = srt_time_str.replace(",", ".")
    parts = time_str.split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    else:
        return float(parts[0])


def parse_srt(srt_path: str) -> List[tuple]:
    """
    解析 SRT 字幕文件，返回所有字幕时间区间：[(start_sec, end_sec), ...]
    """
    subtitles = []
    if not srt_path or not os.path.exists(srt_path):
        return subtitles
    try:
        with open(srt_path, "r", encoding="utf-8") as f:
            content = f.read()
        # 匹配字幕时间轴，如：00:01:23,456 --> 00:01:25,789
        pattern = r"(\d{1,2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,\.]\d{3})"
        matches = re.findall(pattern, content)
        for start_str, end_str in matches:
            sub_s = srt_time_to_seconds(start_str)
            sub_e = srt_time_to_seconds(end_str)
            if sub_s < sub_e:
                subtitles.append((sub_s, sub_e))
    except Exception as e:
        logger.warning(f"解析字幕文件失败 {srt_path}: {e}")
    
    subtitles.sort(key=lambda x: x[0])
    return subtitles


def get_safe_jittered_times(video_path: str, start: float, end: float) -> tuple:
    """
    基于静音区避让与台词防吞的智能首尾偏置 (智能 Jitter)
    """
    # 查找同名的 .srt 文件
    srt_path = video_path.rsplit(".", 1)[0] + ".srt"
    subtitles = parse_srt(srt_path)
    
    if not subtitles:
        logger.info(f"未找到对应字幕文件或字幕为空，跳过时间抖动: {srt_path}")
        return start, end

    # 台词保护缓冲区
    buffer_before = 0.2  # 说话前留白
    buffer_after = 0.15  # 说话后留白

    # 1. 调整 start 时间
    start_jitter = random.uniform(0.1, 0.3)
    if random.choice([True, False]):
        start_jitter = -start_jitter
    new_start = start + start_jitter

    prev_sub = None
    next_sub = None
    in_sub = None

    for sub in subtitles:
        sub_s, sub_e = sub
        forbidden_s = sub_s - buffer_before
        forbidden_e = sub_e + buffer_after
        if forbidden_s <= start <= forbidden_e:
            in_sub = sub
            break
        if sub_e + buffer_after <= start:
            prev_sub = sub
        if sub_s - buffer_before >= start and next_sub is None:
            next_sub = sub

    if in_sub:
        # 在说话区间内，强行向外（左）避让
        new_start = in_sub[0] - buffer_before
        logger.info(f"[Jitter] Start {start:.2f}s 冲突台词区间 [{in_sub[0]:.2f}s, {in_sub[1]:.2f}s]，避让 snap 至 {new_start:.2f}s")
    else:
        # 在静音区，限制抖动不要越界
        min_allowed = prev_sub[1] + buffer_after if prev_sub else 0.0
        max_allowed = next_sub[0] - buffer_before if next_sub else start + 2.0
        new_start = max(min_allowed, min(max_allowed, new_start))
        logger.info(f"[Jitter] Start {start:.2f}s 处于静音区，安全抖动至 {new_start:.2f}s (可用区间: [{min_allowed:.2f}s, {max_allowed:.2f}s])")

    # 2. 调整 end 时间
    end_jitter = random.uniform(0.1, 0.3)
    if random.choice([True, False]):
        end_jitter = -end_jitter
    new_end = end + end_jitter

    prev_sub = None
    next_sub = None
    in_sub = None

    for sub in subtitles:
        sub_s, sub_e = sub
        forbidden_s = sub_s - buffer_before
        forbidden_e = sub_e + buffer_after
        if forbidden_s <= end <= forbidden_e:
            in_sub = sub
            break
        if sub_e + buffer_after <= end:
            prev_sub = sub
        if sub_s - buffer_before >= end and next_sub is None:
            next_sub = sub

    if in_sub:
        # 在说话区间内，强行向外（右）避让
        new_end = in_sub[1] + buffer_after
        logger.info(f"[Jitter] End {end:.2f}s 冲突台词区间 [{in_sub[0]:.2f}s, {in_sub[1]:.2f}s]，避让 snap 至 {new_end:.2f}s")
    else:
        # 在静音区，限制抖动不要越界
        min_allowed = prev_sub[1] + buffer_after if prev_sub else end - 2.0
        max_allowed = next_sub[0] - buffer_before if next_sub else end + 2.0
        new_end = max(min_allowed, min(max_allowed, new_end))
        logger.info(f"[Jitter] End {end:.2f}s 处于静音区，安全抖动至 {new_end:.2f}s (可用区间: [{min_allowed:.2f}s, {max_allowed:.2f}s])")

    if new_start >= new_end or (new_end - new_start) < 0.5:
        logger.info(f"[Jitter] 抖动调整后时长过短或无效 ({new_end - new_start:.2f}s)，降级为原始时间: [{start:.2f}s, {end:.2f}s]")
        return start, end

    return round(new_start, 3), round(new_end, 3)


def to_portrait(input_path: str, output_path: str, dedup_params: Optional[Dict[str, Any]] = None) -> None:
    """横屏转竖屏（9:16），支持去重参数"""
    import cv2

    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        import shutil
        shutil.copy2(input_path, output_path)
        return

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    aspect = width / height if height > 0 else 1.0
    if dedup_params is None and abs(aspect - (9 / 16)) < 0.06:
        import shutil
        shutil.copy2(input_path, output_path)
        return

    target_w = (int(height * 9 / 16) // 2) * 2
    target_h = (height // 2) * 2

    # 默认居中裁剪
    vf_filters = [f"crop={target_w}:{target_h}:(in_w-{target_w})/2:0"]
    af_filters = []
    acodec = ["-c:a", "copy"]

    if dedup_params:
        # 1. 缩放抖动 (微缩放 1.2% - 1.8%)
        scale_f = dedup_params.get("scale_factor", 1.0)
        if scale_f != 1.0:
            cw = (int(target_w * scale_f) // 2) * 2
            ch = (int(target_h * scale_f) // 2) * 2
            cx = max(0, (width - cw) // 2)
            cy = max(0, (height - ch) // 2)
            vf_filters[0] = f"crop={cw}:{ch}:{cx}:{cy},scale={target_w}:{target_h}"

        # 2. 对彩对比度与亮度抖动
        c = dedup_params.get("contrast", 1.0)
        b = dedup_params.get("brightness", 0.0)
        vf_filters.append(f"eq=contrast={c}:brightness={b}")

        # 3. 变速抖动
        sf = dedup_params.get("speed_factor", 1.0)
        if sf != 1.0:
            vf_filters.append(f"setpts=PTS/{sf}")
            af_filters.append(f"atempo={sf}")
            acodec = ["-c:a", "aac", "-b:a", "128k"]

    vf_str = ",".join(vf_filters)
    cmd = [
        get_ffmpeg_path(), "-y",
        "-i", input_path,
        "-vf", vf_str,
    ]
    if af_filters:
        cmd.extend(["-af", ",".join(af_filters)])
    cmd.extend([
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
    ])
    cmd.extend(acodec)
    cmd.append(output_path)
    run_ffmpeg(cmd)


def smart_crop(
    input_path: str,
    output_path: str,
    target_ratio: str = "16:9",
    crop_position: str = "center",
    face_detect: bool = True,
    dedup_params: Optional[Dict[str, Any]] = None,
) -> None:
    """
    智能裁剪视频到目标比例，支持去重参数

    Args:
        input_path: 输入视频路径
        output_path: 输出视频路径
        target_ratio: 目标比例 "16:9" | "9:16" | "1:1"
        crop_position: 裁剪位置 "center" | "top" | "smart"
            - center: 中心裁剪
            - top: 顶部优先（保留人物头部）
            - smart: 智能选择（检测人脸/运动物体）
        face_detect: 是否启用人脸检测优化
        dedup_params: 去重参数字典

    Returns:
        None
    """
    import cv2
    import shutil

    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        shutil.copy2(input_path, output_path)
        return

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    current_ratio = width / height if height > 0 else 1.0

    target_w, target_h = _parse_ratio(target_ratio)
    target_ratio_value = target_w / target_h

    if dedup_params is None and abs(current_ratio - target_ratio_value) < 0.02:
        shutil.copy2(input_path, output_path)
        return

    crop_x, crop_y, crop_w, crop_h = _calculate_crop_params(
        width, height, target_ratio_value, crop_position, face_detect, input_path
    )

    # 确保 crop_w, crop_h 是偶数
    crop_w = (crop_w // 2) * 2
    crop_h = (crop_h // 2) * 2
    orig_w = crop_w
    orig_h = crop_h

    if dedup_params:
        scale_f = dedup_params.get("scale_factor", 1.0)
        if scale_f != 1.0:
            crop_w = (int(orig_w * scale_f) // 2) * 2
            crop_h = (int(orig_h * scale_f) // 2) * 2
            crop_x = max(0, int(crop_x + (orig_w - crop_w) // 2))
            crop_y = max(0, int(crop_y + (orig_h - crop_h) // 2))
            vf_filters = [f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale={orig_w}:{orig_h}"]
        else:
            vf_filters = [f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}"]
    else:
        vf_filters = [f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}"]

    af_filters = []
    acodec = ["-c:a", "copy"]

    if dedup_params:
        c = dedup_params.get("contrast", 1.0)
        b = dedup_params.get("brightness", 0.0)
        vf_filters.append(f"eq=contrast={c}:brightness={b}")

        sf = dedup_params.get("speed_factor", 1.0)
        if sf != 1.0:
            vf_filters.append(f"setpts=PTS/{sf}")
            af_filters.append(f"atempo={sf}")
            acodec = ["-c:a", "aac", "-b:a", "128k"]

    vf_str = ",".join(vf_filters)
    cmd = [
        get_ffmpeg_path(), "-y",
        "-i", input_path,
        "-vf", vf_str,
    ]
    if af_filters:
        cmd.extend(["-af", ",".join(af_filters)])
    cmd.extend([
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
    ])
    cmd.extend(acodec)
    cmd.append(output_path)
    run_ffmpeg(cmd)
    logger.info(f"[smart_crop] 裁剪 {width}x{height} -> {crop_w}x{crop_h}, 位置: ({crop_x}, {crop_y}), 去重启用: {dedup_params is not None}")


def _parse_ratio(ratio: str) -> tuple:
    """解析比例字符串"""
    if ratio == "16:9":
        return (16, 9)
    elif ratio == "9:16":
        return (9, 16)
    elif ratio == "1:1":
        return (1, 1)
    elif ratio == "4:3":
        return (4, 3)
    elif ratio == "21:9":
        return (21, 9)
    else:
        return (16, 9)


def _calculate_crop_params(
    width: int,
    height: int,
    target_ratio: float,
    crop_position: str,
    face_detect: bool,
    video_path: str,
) -> tuple:
    """
    计算裁剪参数

    Returns:
        (crop_x, crop_y, crop_w, crop_h)
    """
    if target_ratio > 1.0:
        crop_w = height * target_ratio
        crop_h = height
        if crop_w > width:
            crop_w = width
            crop_h = width / target_ratio

        crop_w = int(crop_w)
        crop_h = int(crop_h)

        if crop_position == "center":
            crop_x = (width - crop_w) // 2
            crop_y = 0
        elif crop_position == "top":
            crop_x = (width - crop_w) // 2
            crop_y = 0
        else:
            crop_x, crop_y = _smart_detect_crop_position(
                video_path, crop_w, crop_h, width, height
            )
    else:
        crop_h = width / target_ratio
        crop_w = width
        if crop_h > height:
            crop_h = height
            crop_w = height * target_ratio

        crop_w = int(crop_w)
        crop_h = int(crop_h)
        crop_x = 0
        crop_y = (height - crop_h) // 2

    return (crop_x, crop_y, crop_w, crop_h)


def _smart_detect_crop_position(
    video_path: str,
    crop_w: int,
    crop_h: int,
    video_w: int,
    video_h: int,
) -> tuple:
    """
    智能检测裁剪位置（基于画面内容分析）

    检测画面中心区域的内容密度，选择最佳裁剪位置
    """
    import cv2

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return ((video_w - crop_w) // 2, 0)

    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if frame_count > 60:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_count // 4)

    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        return ((video_w - crop_w) // 2, 0)

    height, cols = frame.shape[:2]

    if crop_w >= video_w:
        return (0, (video_h - crop_h) // 2)

    if crop_h >= video_h:
        return ((video_w - crop_w) // 2, 0)

    center_score = _calculate_center_interest_score(frame, crop_w, crop_h)
    top_score = _calculate_top_interest_score(frame, crop_w, crop_h)

    if center_score > top_score * 1.2:
        return ((video_w - crop_w) // 2, 0)
    else:
        return ((video_w - crop_w) // 2, max(0, (video_h - crop_h) // 4))


def _calculate_center_interest_score(frame, crop_w: int, crop_h: int) -> float:
    """计算中心区域的兴趣分数"""
    import cv2
    height, width = frame.shape[:2]
    center_x = width // 2
    center_y = height // 2

    h, w = frame.shape[:2]
    center_region = frame[
        max(0, center_y - crop_h // 2):min(h, center_y + crop_h // 2),
        max(0, center_x - crop_w // 2):min(w, center_x + crop_w // 2)
    ]

    gray = cv2.cvtColor(center_region, cv2.COLOR_BGR2GRAY)
    laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()

    return laplacian_var


def _calculate_top_interest_score(frame, crop_w: int, crop_h: int) -> float:
    """计算顶部区域的兴趣分数"""
    import cv2
    height, width = frame.shape[:2]
    top_region = frame[0:min(height // 2, crop_h), :]

    gray = cv2.cvtColor(top_region, cv2.COLOR_BGR2GRAY)
    laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()

    return laplacian_var * 1.3


def crop_to_square(input_path: str, output_path: str) -> None:
    """裁剪为正方形 1:1"""
    smart_crop(input_path, output_path, target_ratio="1:1", crop_position="center")


def convert_aspect_ratio(
    input_path: str,
    output_path: str,
    target_ratio: str = "16:9",
) -> None:
    """转换视频比例（添加黑边而非裁剪）"""
    import cv2

    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        import shutil
        shutil.copy2(input_path, output_path)
        return

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    target_w, target_h = _parse_ratio(target_ratio)
    target_ratio_value = target_w / target_h
    current_ratio = width / height if height > 0 else 1.0

    if abs(current_ratio - target_ratio_value) < 0.02:
        import shutil
        shutil.copy2(input_path, output_path)
        return

    if current_ratio > target_ratio_value:
        new_height = int(width / target_ratio_value)
        pad_top = (new_height - height) // 2
        pad_bottom = new_height - height - pad_top
        vf_filter = f"pad={width}:{new_height}:0:{pad_top}"
    else:
        new_width = int(height * target_ratio_value)
        pad_left = (new_width - width) // 2
        pad_right = new_width - width - pad_left
        vf_filter = f"pad={new_width}:{height}:{pad_left}:0"

    cmd = [
        get_ffmpeg_path(), "-y",
        "-i", input_path,
        "-vf", vf_filter,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "copy",
        output_path
    ]
    run_ffmpeg(cmd)


def concat_videos(video_paths: List[str], output_path: str) -> None:
    """拼接视频，并彻底抹除元数据"""
    if len(video_paths) == 0:
        raise ValueError("没有视频需要拼接")
    if len(video_paths) == 1:
        # 不使用 shutil.copy2，因为我们要彻底抹除原视频元数据！
        cmd = [
            get_ffmpeg_path(), "-y",
            "-i", video_paths[0],
            "-c", "copy",
            "-map_metadata", "-1",
            output_path
        ]
        try:
            run_ffmpeg(cmd)
        except Exception:
            import shutil
            shutil.copy2(video_paths[0], output_path)
        return

    import tempfile
    temp_dir = tempfile.gettempdir()
    list_file = Path(temp_dir) / f"concat_{uuid.uuid4().hex[:8]}.txt"

    with open(list_file, "w", encoding="utf-8") as f:
        for p in video_paths:
            escaped = str(p).replace("\\", "/").replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")

    cmd = [
        get_ffmpeg_path(), "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        "-map_metadata", "-1",
        output_path
    ]

    try:
        run_ffmpeg(cmd)
    except FFmpegError:
        # 降级重编码
        cmd2 = [
            get_ffmpeg_path(), "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(list_file),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac",
            "-map_metadata", "-1",
            output_path
        ]
        run_ffmpeg(cmd2)
    finally:
        if list_file.exists():
            list_file.unlink()
