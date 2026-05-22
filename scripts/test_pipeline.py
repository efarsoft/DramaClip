"""
端到端语音/字幕处理流程联调脚本
测试: 音频提取 → ASR 语音识别 → 说话人分离 → 情绪分析 → 字幕输出
"""

import asyncio
import sys
import json
import subprocess
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.init import init_all

init_all()

from loguru import logger
from app.utils.ffmpeg_utils import get_ffmpeg_path
from app.services.analyze.asr_service import ASRService
from app.services.analyze.speaker_diarization_service import SpeakerDiarizationService
from app.services.analyze.emotion_service import EmotionService


# ─── 配置 ────────────────────────────────────────────────────────────────────

VIDEO_PATH = Path(__file__).resolve().parents[1] / "storage" / "test_video.mp4"
SPEECH_PATH = Path(__file__).resolve().parents[1] / "storage" / "test_speech.wav"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "storage" / "test_flow"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# config.toml 中配置的 model 是 large-v3，但我们本地只有 tiny
# 这里强制用 tiny 做联调（够快）
ASR_MODEL = "tiny"


# ─── Step 0: 检查文件 ─────────────────────────────────────────────────────────

def check_video():
    if not SPEECH_PATH.exists():
        print(f"❌ 语音文件不存在: {SPEECH_PATH}")
        sys.exit(1)
    size_kb = SPEECH_PATH.stat().st_size // 1024
    print(f"✅ 测试语音: {SPEECH_PATH.name} ({size_kb} KB)")


# ─── Step 1: 音频提取 ──────────────────────────────────────────────────────────

def extract_audio() -> Path:
    """将 test_speech.wav 转换为 16kHz mono WAV"""
    audio_path = OUTPUT_DIR / "audio.wav"
    print(f"\n{'='*60}")
    print("Step 1: 转换音频 (16kHz mono WAV)")
    print(f"{'='*60}")

    ffmpeg = get_ffmpeg_path()
    cmd = [
        ffmpeg,
        "-y", "-i", str(SPEECH_PATH),
        "-acodec", "pcm_s16le",
        "-ar", "16000", "-ac", "1",
        str(audio_path),
    ]
    t0 = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.time() - t0

    if result.returncode != 0:
        print(f"❌ FFmpeg 失败: {result.stderr[-200:]}")
        sys.exit(1)

    size_kb = audio_path.stat().st_size // 1024
    print(f"✅ 音频处理完成: {audio_path.name} ({size_kb} KB)  [{elapsed:.2f}s]")
    return audio_path


# ─── Step 2: ASR 语音识别 ──────────────────────────────────────────────────────

def run_asr(audio_path: Path):
    print(f"\n{'='*60}")
    print(f"Step 2: ASR 语音识别 (model={ASR_MODEL})")
    print(f"{'='*60}")

    service = ASRService()

    def progress(pct, msg):
        print(f"  [{pct:3d}%] {msg}")

    t0 = time.time()
    result = service.recognize(
        audio_path=str(audio_path),
        language="zh",
        model=ASR_MODEL,
        progress_callback=progress,
    )
    elapsed = time.time() - t0

    print(f"\n✅ ASR 完成: {len(result.segments)} 段, 语言={result.language}  [{elapsed:.2f}s]")
    print(f"\n--- 识别结果预览 ---")
    for i, seg in enumerate(result.segments[:8]):
        print(f"  [{seg.start:.1f}s - {seg.end:.1f}s] {seg.text}")
    if len(result.segments) > 8:
        print(f"  ... (共 {len(result.segments)} 段)")

    # 保存 ASR JSON
    asr_out = OUTPUT_DIR / "asr.json"
    asr_out.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"\n💾 ASR 结果已保存: {asr_out}")
    return result


# ─── Step 3: 说话人分离 ────────────────────────────────────────────────────────

def run_diarization(audio_path: Path):
    print(f"\n{'='*60}")
    print("Step 3: 说话人分离 (MFCC + 谱聚类)")
    print(f"{'='*60}")

    service = SpeakerDiarizationService(min_speakers=1, max_speakers=5)

    def progress(pct, msg):
        print(f"  [{pct:3d}%] {msg}")

    t0 = time.time()
    result = service.diarize(
        audio_path=str(audio_path),
        video_id="test_video",
        progress_callback=progress,
    )
    elapsed = time.time() - t0

    print(f"\n✅ 分离完成: {result.speaker_count} 个说话人, {len(result.segments)} 段  [{elapsed:.2f}s]")
    print(f"\n--- 说话人分布 ---")
    for sp in result.speakers:
        print(f"  {sp.speaker_id}: {sp.segment_count} 段, 时长={sp.total_duration:.1f}s, 音高={sp.avg_pitch:.0f}Hz")

    print(f"\n--- 时间线预览 (前 8 段) ---")
    for seg in result.segments[:8]:
        print(f"  [{seg.start:.1f}s - {seg.end:.1f}s] {seg.speaker_id} (置信度={seg.confidence:.2f})")

    # 保存
    diar_out = OUTPUT_DIR / "diarization.json"
    diar_out.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"\n💾 分离结果已保存: {diar_out}")
    return result


# ─── Step 4: 说话人整合到字幕 ─────────────────────────────────────────────────

def merge_speaker(asr_result, diarization_result):
    print(f"\n{'='*60}")
    print("Step 4: 说话人标签整合到字幕")
    print(f"{'='*60}")

    speaker_segments = diarization_result.segments
    assigned = 0

    for seg in asr_result.segments:
        # 1. 优先策略：计算 ASR 段与所有说话人段的重叠时长
        overlap_durations = {}
        for sp_seg in speaker_segments:
            overlap_start = max(seg.start, sp_seg.start)
            overlap_end = min(seg.end, sp_seg.end)
            if overlap_start < overlap_end:
                overlap_len = overlap_end - overlap_start
                sp_id = sp_seg.speaker_id
                overlap_durations[sp_id] = overlap_durations.get(sp_id, 0.0) + overlap_len
        
        if overlap_durations:
            best_speaker = max(overlap_durations, key=overlap_durations.get)
            seg.speaker = best_speaker
            assigned += 1
        else:
            # 2. 兜底策略：选择中心点距离最近的说话人段
            seg_midpoint = (seg.start + seg.end) / 2.0
            min_dist = float('inf')
            best_speaker = None
            
            for sp_seg in speaker_segments:
                sp_midpoint = (sp_seg.start + sp_seg.end) / 2.0
                dist = abs(seg_midpoint - sp_midpoint)
                if dist < min_dist:
                    min_dist = dist
                    best_speaker = sp_seg.speaker_id
            
            if best_speaker:
                seg.speaker = best_speaker
                assigned += 1

    total = len(asr_result.segments)
    print(f"✅ 已分配说话人: {assigned}/{total} 段")

    print(f"\n--- 带说话人标签的字幕预览 (前 8 段) ---")
    for seg in asr_result.segments[:8]:
        speaker = seg.speaker or "unknown"
        print(f"  [{seg.start:.1f}s-{seg.end:.1f}s] [{speaker}] {seg.text}")

    # 保存合并后的字幕
    subtitle_lines = []
    for i, seg in enumerate(asr_result.segments, 1):
        speaker = seg.speaker or "unknown"
        start = _format_srt_time(seg.start)
        end = _format_srt_time(seg.end)
        subtitle_lines.append(f"{i}")
        subtitle_lines.append(f"{start} --> {end}")
        subtitle_lines.append(f"[{speaker}] {seg.text}")
        subtitle_lines.append("")

    srt_out = OUTPUT_DIR / "subtitles.srt"
    srt_out.write_text("\n".join(subtitle_lines), encoding="utf-8")
    print(f"\n💾 字幕文件已保存: {srt_out}")

    return asr_result


# ─── Step 5: 情绪分析 ──────────────────────────────────────────────────────────

def run_emotion(asr_result):
    print(f"\n{'='*60}")
    print("Step 5: 情绪分析 (关键词/LLM)")
    print(f"{'='*60}")

    service = EmotionService(use_llm=True, fallback_to_keyword=True)

    text_segs = [
        {"text": seg.text, "start": seg.start, "end": seg.end}
        for seg in asr_result.segments
    ]

    def progress(pct, msg):
        if pct % 20 == 0:
            print(f"  [{pct:3d}%] {msg}")

    t0 = time.time()
    result = service.analyze(text_segs, video_id="test_video", progress_callback=progress)
    elapsed = time.time() - t0

    print(f"\n✅ 情绪分析完成  [{elapsed:.2f}s]")
    print(f"   整体情绪: {result.overall_emotion} (强度={result.overall_intensity:.2f})")
    print(f"   总结: {result.sentiment_summary}")
    print(f"\n--- 情绪分布 ---")
    for emotion, pct in sorted(result.emotion_distribution.items(), key=lambda x: x[1], reverse=True):
        bar = "█" * int(pct / 5)
        print(f"  {emotion:12s} {bar} {pct:.1f}%")

    if result.peak_moments:
        print(f"\n--- 情绪高峰 (前 3 个) ---")
        for peak in result.peak_moments[:3]:
            print(f"  [{peak['timestamp']:.1f}s] {peak['emotion']}({peak.get('sub_emotion','')}) 强度={peak['intensity']:.2f}")

    # 保存
    emotion_out = OUTPUT_DIR / "emotion.json"
    emotion_out.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"\n💾 情绪结果已保存: {emotion_out}")
    return result


# ─── 工具函数 ──────────────────────────────────────────────────────────────────

def _format_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ─── 主流程 ───────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("DramaClip 语音/字幕处理流程 端到端联调")
    print("=" * 60)

    total_start = time.time()

    check_video()
    audio_path = extract_audio()
    asr_result = run_asr(audio_path)
    diar_result = run_diarization(audio_path)
    merged_result = merge_speaker(asr_result, diar_result)

    if merged_result.segments:
        run_emotion(merged_result)
    else:
        print("\n⚠️  ASR 无识别结果，跳过情绪分析")

    total_elapsed = time.time() - total_start
    print(f"\n{'='*60}")
    print(f"✅ 全流程联调完成！总耗时: {total_elapsed:.2f}s")
    print(f"📁 输出目录: {OUTPUT_DIR}")
    print(f"   - audio.wav        原始音频")
    print(f"   - asr.json         语音识别结果")
    print(f"   - diarization.json 说话人分离结果")
    print(f"   - subtitles.srt    带说话人标签的字幕")
    print(f"   - emotion.json     情绪分析结果")
    print("=" * 60)


if __name__ == "__main__":
    main()
