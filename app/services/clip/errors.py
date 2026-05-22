"""
剪辑流水线统一错误定义
"""

class PipelineError(Exception):
    """流水线执行错误"""
    pass


class StageError(Exception):
    """阶段执行错误"""
    def __init__(self, stage_name: str, message: str, original_error: Exception = None):
        self.stage_name = stage_name
        self.message = message
        self.original_error = original_error
        super().__init__(f"[{stage_name}] {message}")


class FFmpegError(Exception):
    """FFmpeg 执行错误"""
    pass


class ResourceError(Exception):
    """资源管理错误（临时文件等）"""
    pass
