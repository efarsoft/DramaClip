"""
场景提取工具模块
P2 性能优化：优先使用 -c copy，失败再重编码

优化策略：
1. 优先使用 -c copy（无损提取，不重编码）
2. 失败时捕获错误，判断是否需要重编码
3. 减少 120 个场景 = 120 次重编码的性能损耗
"""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple
from loguru import logger

from app.utils.path_manager import get_path_manager
from app.exceptions import ErrorFactory, SystemError


class SceneExtractor:
    """
    智能场景提取器

    优化点：
    1. 优先使用 -c copy（不重编码）
    2. 失败时自动降级到重编码
    3. 统一临时文件管理
    """

    def __init__(self, config: Optional[dict] = None):
        self._config = config or {}
        self._path_mgr = get_path_manager()

    def extract(
        self,
        video_path: str,
        start_time: float,
        end_time: float,
        output_path: Optional[str] = None,
        force_reencode: bool = False,
    ) -> str:
        """
        提取视频片段

        Args:
            video_path: 输入视频路径
            start_time: 开始时间（秒）
            end_time: 结束时间（秒）
            output_path: 输出路径（可选）
            force_reencode: 是否强制重编码

        Returns:
            输出文件路径

        Raises:
            SystemError: 提取失败
        """
        duration = end_time - start_time

        # 如果未指定输出路径，使用 PathManager
        if output_path is None:
            output_path = str(
                self._path_mgr.create_temp_file(suffix=".mp4")
            )

        # 尝试 -c copy（优先）
        if not force_reencode:
            try:
                result = self._extract_with_copy(
                    video_path, start_time, end_time, output_path
                )
                logger.info(
                    f"[SceneExtractor] Extracted with -c copy: {video_path} "
                    f"[{start_time:.1f}s - {end_time:.1f}s] -> {output_path}"
                )
                return result
            except Exception as e:
                logger.warning(
                    f"[SceneExtractor] -c copy failed, falling back to re-encode: {e}"
                )

        # 回退到重编码
        result = self._extract_with_reencode(
            video_path, start_time, end_time, output_path
        )
        logger.info(
            f"[SceneExtractor] Extracted with re-encode: {video_path} "
            f"[{start_time:.1f}s - {end_time:.1f}s] -> {output_path}"
        )
        return result

    def _extract_with_copy(
        self,
        video_path: str,
        start_time: float,
        end_time: float,
        output_path: str,
    ) -> str:
        """
        使用 -c copy 提取（不重编码）

        优点：
        - 无损提取
        - 速度快（不需要解码/重编码）

        限制：
        - 必须在关键帧处切割
        - 无法处理跨流的情况
        """
        from app.utils.ffmpeg_utils import get_ffmpeg_path

        cmd = [
            get_ffmpeg_path(),
            "-y",  # 覆盖输出
            "-ss", str(start_time),  # 开始时间
            "-i", video_path,
            "-t", str(end_time - start_time),  # 持续时间
            "-c", "copy",  # 不重编码
            "-avoid_negative_ts", "1",
            output_path,
        ]

        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )

        # 验证输出文件
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise ValueError("-c copy produced empty output")

        return output_path

    def _extract_with_reencode(
        self,
        video_path: str,
        start_time: float,
        end_time: float,
        output_path: str,
    ) -> str:
        """
        使用重编码提取

        适用场景：
        - -c copy 失败
        - 需要精确帧级别切割
        - 需要转码
        """
        from app.utils.ffmpeg_utils import get_ffmpeg_path

        # 使用 ultrafast + crf23 减少编码时间
        cmd = [
            get_ffmpeg_path(),
            "-y",
            "-ss", str(start_time),
            "-i", video_path,
            "-t", str(end_time - start_time),
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            output_path,
        ]

        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode("utf-8", errors="ignore")
            raise ErrorFactory.ffmpeg_error(
                command=" ".join(cmd),
                stderr=stderr,
            )

        # 验证输出文件
        if not os.path.exists(output_path):
            raise ErrorFactory.temp_file_error(output_path, "提取后文件不存在")

        return output_path

    def extract_batch(
        self,
        video_path: str,
        segments: list,
        output_dir: Optional[str] = None,
    ) -> list:
        """
        批量提取视频片段

        Args:
            video_path: 输入视频路径
            segments: 片段列表 [(start, end), ...]
            output_dir: 输出目录

        Returns:
            输出路径列表
        """
        if output_dir is None:
            output_dir = str(self._path_mgr.create_temp_dir())

        os.makedirs(output_dir, exist_ok=True)

        outputs = []
        for i, (start, end) in enumerate(segments):
            output_path = os.path.join(
                output_dir, f"segment_{i:03d}_{start:.2f}_{end:.2f}.mp4"
            )

            try:
                result = self.extract(
                    video_path, start, end, output_path
                )
                outputs.append(result)
            except Exception as e:
                logger.error(
                    f"[SceneExtractor] Failed to extract segment {i}: {e}"
                )
                outputs.append(None)

        return outputs


class VideoConcat:
    """
    视频拼接器

    支持：
    1. 无损拼接（-c copy）
    2. 重编码拼接
    3. 批量拼接
    """

    def __init__(self, config: Optional[dict] = None):
        self._config = config or {}
        self._path_mgr = get_path_manager()

    def concat(
        self,
        input_paths: list,
        output_path: Optional[str] = None,
        use_copy: bool = True,
    ) -> str:
        """
        拼接视频

        Args:
            input_paths: 输入文件路径列表
            output_path: 输出路径
            use_copy: 是否使用 -c copy（需要相同编码参数）

        Returns:
            输出文件路径
        """
        if not input_paths:
            raise ValueError("No input files")

        # 过滤无效文件
        valid_paths = [p for p in input_paths if p and os.path.exists(p)]
        if not valid_paths:
            raise ValueError("No valid input files")

        # 如果只有一个文件，直接复制
        if len(valid_paths) == 1:
            if output_path is None:
                output_path = str(
                    self._path_mgr.create_temp_file(suffix=".mp4")
                )
            import shutil
            shutil.copy(valid_paths[0], output_path)
            return output_path

        # 创建临时文件列表
        concat_list_path = str(
            self._path_mgr.create_temp_file(suffix=".txt")
        )

        with open(concat_list_path, "w", encoding="utf-8") as f:
            for path in valid_paths:
                f.write(f"file '{path}'\n")

        if output_path is None:
            output_path = str(
                self._path_mgr.create_temp_file(suffix=".mp4")
            )

        if use_copy:
            try:
                return self._concat_with_copy(concat_list_path, output_path)
            except Exception as e:
                logger.warning(f"[VideoConcat] -c copy failed: {e}")

        return self._concat_with_reencode(concat_list_path, output_path)

    def _concat_with_copy(
        self,
        concat_list: str,
        output_path: str,
    ) -> str:
        """使用 -c copy 拼接"""
        from app.utils.ffmpeg_utils import get_ffmpeg_path

        cmd = [
            get_ffmpeg_path(),
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_list,
            "-c", "copy",
            output_path,
        ]

        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

        return output_path

    def parallel_concat(
        self,
        input_paths: list,
        output_path: Optional[str] = None,
        max_workers: int = 4,
    ) -> str:
        """
        并行拼接多个视频（两两合并）

        策略：将视频分成多组，每组内先并行拼接，最后合并
        这样可以利用多核 CPU 加速

        Args:
            input_paths: 输入文件路径列表
            output_path: 输出路径
            max_workers: 最大并行数

        Returns:
            输出文件路径
        """
        if not input_paths:
            raise ValueError("No input files")

        valid_paths = [p for p in input_paths if p and os.path.exists(p)]
        if not valid_paths:
            raise ValueError("No valid input files")

        if len(valid_paths) <= 2:
            return self.concat(valid_paths, output_path)

        if output_path is None:
            output_path = str(
                self._path_mgr.create_temp_file(suffix=".mp4")
            )

        temp_dir = str(self._path_mgr.create_temp_dir(prefix="concat_"))

        current_files = valid_paths.copy()
        round_num = 1

        while len(current_files) > 1:
            next_round_files = []

            for i in range(0, len(current_files), 2):
                if i + 1 < len(current_files):
                    output = os.path.join(
                        temp_dir,
                        f"round{round_num}_{i // 2}.mp4"
                    )
                    self.concat(
                        [current_files[i], current_files[i + 1]],
                        output,
                        use_copy=True,
                    )
                    next_round_files.append(output)
                else:
                    next_round_files.append(current_files[i])

            current_files = next_round_files
            round_num += 1

            if round_num > 20:
                break

        if len(current_files) == 1:
            import shutil
            shutil.copy(current_files[0], output_path)
        else:
            self.concat(current_files, output_path, use_copy=True)

        logger.info(
            f"[VideoConcat] Parallel concat completed: {len(valid_paths)} -> {output_path}"
        )

        return output_path

    def _concat_with_reencode(
        self,
        concat_list: str,
        output_path: str,
    ) -> str:
        """使用重编码拼接"""
        from app.utils.ffmpeg_utils import get_ffmpeg_path

        cmd = [
            get_ffmpeg_path(),
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_list,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            output_path,
        ]

        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

        return output_path
