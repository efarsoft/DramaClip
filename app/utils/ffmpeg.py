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

from app.utils.ffmpeg_utils import (
    get_ffmpeg_path,
    get_ffprobe_path,
    get_null_input,
    check_ffmpeg_installation,
    detect_hardware_acceleration,
    extract_audio,
)

# Re-export 使此文件成为 ffmpeg 操作的统一入口
# 新代码应统一从 app.utils.ffmpeg 导入


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


def _extract_audio_snippet(video_path: str, start_sec: float, duration_sec: float, output_wav: str) -> bool:
    """使用 ffmpeg 提取视频中短音频片段（16kHz 单声道 PCM），供能量分析使用。"""
    cmd = [
        get_ffmpeg_path(), "-y",
        "-i", video_path,
        "-ss", f"{max(0.0, start_sec):.3f}",
        "-t", f"{max(0.5, duration_sec):.3f}",
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        output_wav
    ]
    try:
        run_ffmpeg(cmd, check=True)
        return True
    except Exception as e:
        logger.debug(f"音频片段提取失败: {e}")
        return False


def _detect_speech_zones_energy(video_path: str, center_start: float, center_end: float, window_sec: float = 7.0) -> List[tuple]:
    """
    能量-based 语音区检测（无字幕时的降级方案）。
    仅分析目标切点周围小窗口，避免加载整段长视频音频。
    返回相对于视频时间轴的 [(speech_start, speech_end), ...]
    """
    import tempfile
    import os

    try:
        from pydub import AudioSegment
        from pydub.utils import make_chunks
    except ImportError:
        logger.warning("pydub 未安装，无法启用无字幕语音区检测降级")
        return []

    search_start = max(0.0, center_start - window_sec)
    search_duration = (center_end - center_start) + 2 * window_sec

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp_path = tmp.name
    tmp.close()

    zones: List[tuple] = []
    try:
        if not _extract_audio_snippet(video_path, search_start, search_duration, tmp_path):
            return zones

        if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) < 1024:
            return zones

        audio = AudioSegment.from_file(tmp_path)
        if len(audio) < 150:
            return zones

        # 每 80ms 一个 chunk 计算 RMS（对人声较敏感）
        chunk_ms = 80
        chunks = make_chunks(audio, chunk_ms)
        energies = []
        for i, chunk in enumerate(chunks):
            rms = float(chunk.rms or 1)
            t = search_start + (i * chunk_ms / 1000.0)
            energies.append((t, rms))

        if len(energies) < 3:
            return zones

        rms_vals = [e[1] for e in energies]
        mean_rms = sum(rms_vals) / len(rms_vals)
        # 自适应阈值：均值之上一定倍数（对短剧对白有效）
        threshold = max(mean_rms * 1.65, 120)  # 避免极静音视频误判

        in_speech = False
        speech_start_t = 0.0
        min_speech_dur = 0.28  # 忽略极短爆音

        for t, rms in energies:
            if rms > threshold and not in_speech:
                in_speech = True
                speech_start_t = t
            elif rms < threshold * 0.65 and in_speech:
                in_speech = False
                dur = t - speech_start_t
                if dur >= min_speech_dur:
                    zones.append((speech_start_t, t))

        if in_speech:
            dur = energies[-1][0] - speech_start_t
            if dur >= min_speech_dur:
                zones.append((speech_start_t, energies[-1][0] + 0.1))

        if zones:
            logger.info(f"[Jitter-Fallback] 能量检测到 {len(zones)} 个语音区（窗口 {search_start:.1f}s ~ {search_start+search_duration:.1f}s）")
    except Exception as e:
        logger.warning(f"语音区能量检测失败: {e}")
    finally:
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except Exception:
            pass

    return zones


def _apply_protection_jitter(
    cut_time: float,
    is_start: bool,
    protection_zones: List[tuple],
    buffer_before: float = 0.2,
    buffer_after: float = 0.15,
    jitter_range: float = 0.3
) -> float:
    """对单个切点应用保护区避让 + 安全抖动（同时适用于字幕和能量区）。"""
    if not protection_zones:
        # 无保护区时仍给一个很小的随机抖动（保持去重效果）
        j = random.uniform(0.03, 0.12)
        if random.random() < 0.5:
            j = -j
        return round(cut_time + j, 3)

    jitter = random.uniform(0.08, jitter_range)
    if random.random() < 0.5:
        jitter = -jitter
    new_t = cut_time + jitter

    prev_zone = None
    next_zone = None
    in_zone = None

    for z_s, z_e in protection_zones:
        forbidden_s = z_s - buffer_before
        forbidden_e = z_e + buffer_after
        if forbidden_s <= cut_time <= forbidden_e:
            in_zone = (z_s, z_e)
            break
        if z_e + buffer_after <= cut_time:
            prev_zone = (z_s, z_e)
        if z_s - buffer_before >= cut_time and next_zone is None:
            next_zone = (z_s, z_e)

    if in_zone:
        z_s, z_e = in_zone
        if is_start:
            new_t = z_s - buffer_before
        else:
            new_t = z_e + buffer_after
        logger.info(f"[Jitter] {'Start' if is_start else 'End'} {cut_time:.2f}s 命中保护区 [{z_s:.2f},{z_e:.2f}]，snap 至 {new_t:.2f}s")
    else:
        min_allowed = (prev_zone[1] + buffer_after) if prev_zone else (cut_time - 3.0)
        max_allowed = (next_zone[0] - buffer_before) if next_zone else (cut_time + 3.0)
        new_t = max(min_allowed, min(max_allowed, new_t))
        logger.debug(f"[Jitter] {'Start' if is_start else 'End'} {cut_time:.2f}s 安全抖动至 {new_t:.2f}s")

    return round(new_t, 3)


def get_safe_jittered_times(video_path: str, start: float, end: float) -> tuple:
    """
    基于静音区避让与台词/语音防吞的智能首尾偏置 (智能 Jitter)。
    优先使用同名字幕 (.srt)，无字幕时自动降级为基于音频能量的语音区检测。
    """
    # 1. 尝试字幕
    srt_path = video_path.rsplit(".", 1)[0] + ".srt"
    protection_zones = parse_srt(srt_path)
    source = "srt"

    if not protection_zones:
        # 2. 无字幕降级：音频能量语音区检测
        protection_zones = _detect_speech_zones_energy(video_path, start, end)
        source = "energy" if protection_zones else "none"

    if not protection_zones:
        logger.info(f"[Jitter] 未找到字幕且能量检测无语音区，使用极小抖动: {os.path.basename(video_path)}")
        # 极保守的小抖动（仍提供基础去重）
        j1 = random.uniform(0.02, 0.08)
        j2 = random.uniform(0.02, 0.08)
        if random.random() < 0.5:
            j1 = -j1
        if random.random() < 0.5:
            j2 = -j2
        new_s = round(max(0.0, start + j1), 3)
        new_e = round(end + j2, 3)
        return (new_s, new_e) if (new_e - new_s) > 0.4 else (start, end)

    buffer_before = 0.2
    buffer_after = 0.15

    new_start = _apply_protection_jitter(start, True, protection_zones, buffer_before, buffer_after)
    new_end = _apply_protection_jitter(end, False, protection_zones, buffer_before, buffer_after)

    if new_start >= new_end or (new_end - new_start) < 0.45:
        logger.warning(f"[Jitter] 调整后时长过短 ({new_end - new_start:.2f}s)，回退原始: [{start:.2f}, {end:.2f}]")
        return start, end

    if source == "energy":
        logger.info(f"[Jitter-Energy] {start:.2f}s~{end:.2f}s -> {new_start:.2f}s~{new_end:.2f}s (无字幕降级)")

    return new_start, new_end


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
