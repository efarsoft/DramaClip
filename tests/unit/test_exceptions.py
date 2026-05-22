"""
单元测试 - 异常体系
测试 DramaClip 异常
"""

import pytest
from app.exceptions import (
    DramaClipError,
    UserError,
    SystemError,
    AIError,
    ErrorFactory,
    ErrorCode,
    ErrorHandler,
    ErrorDetail,
)


class TestDramaClipError:
    """DramaClipError 测试"""

    def test_user_error(self):
        """测试用户错误"""
        error = UserError(
            code=ErrorCode.VIDEO_NOT_FOUND,
            title="视频未找到",
            message="指定的视频文件不存在",
            suggestion="请检查文件路径",
        )

        assert isinstance(error, DramaClipError)
        assert isinstance(error, UserError)
        assert error.code == ErrorCode.VIDEO_NOT_FOUND

    def test_system_error(self):
        """测试系统错误"""
        error = SystemError(
            code=ErrorCode.FFMPEG_ERROR,
            title="FFmpeg 错误",
            message="FFmpeg 执行失败",
            suggestion="请安装 FFmpeg",
        )

        assert isinstance(error, SystemError)
        assert error.code == ErrorCode.FFMPEG_ERROR

    def test_ai_error(self):
        """测试 AI 错误"""
        error = AIError(
            code=ErrorCode.LLM_ERROR,
            title="LLM 服务错误",
            message="AI 服务调用失败",
            suggestion="请稍后重试",
        )

        assert isinstance(error, AIError)

    def test_to_dict(self):
        """测试转换为字典"""
        error = UserError(
            code=ErrorCode.STORAGE_ERROR,
            title="存储错误",
            message="磁盘空间不足",
            suggestion="请清理磁盘",
            context={"path": "/some/path"},
        )

        data = error.to_dict()

        assert data["code"] == ErrorCode.STORAGE_ERROR.value
        assert data["title"] == "存储错误"
        assert data["suggestion"] == "请清理磁盘"
        assert data["context"]["path"] == "/some/path"

    def test_str_representation(self):
        """测试字符串表示
        
        __str__ 格式为 [ErrorCode.VIDEO_NOT_FOUND] title: message，
        包含枚举名而非枚举值（E1001）。
        """
        error = UserError(
            code=ErrorCode.VIDEO_NOT_FOUND,
            title="视频未找到",
            message="视频文件不存在",
            suggestion="请检查路径",
        )

        s = str(error)

        # __str__ 输出：[ErrorCode.VIDEO_NOT_FOUND] 视频未找到: 视频文件不存在
        assert "VIDEO_NOT_FOUND" in s
        assert "视频未找到" in s
        assert "视频文件不存在" in s


class TestErrorFactory:
    """ErrorFactory 测试"""

    def test_video_not_found(self):
        """测试视频未找到异常"""
        error = ErrorFactory.video_not_found("/path/to/video.mp4")

        assert isinstance(error, UserError)
        assert error.code == ErrorCode.VIDEO_NOT_FOUND
        assert "/path/to/video.mp4" in error.message

    def test_invalid_format(self):
        """测试格式不支持异常"""
        error = ErrorFactory.invalid_format("/path/to/file.txt")

        assert isinstance(error, UserError)
        assert "txt" in error.message

    def test_ffmpeg_error(self):
        """测试 FFmpeg 执行错误"""
        error = ErrorFactory.ffmpeg_error(
            command="ffmpeg -i input.mp4 output.mp4",
            stderr="Unknown codec",
        )

        assert isinstance(error, SystemError)
        assert error.code == ErrorCode.FFMPEG_ERROR

    def test_llm_error(self):
        """测试 LLM 错误"""
        error = ErrorFactory.llm_error("openai", "API key invalid")

        assert isinstance(error, AIError)
        assert error.code == ErrorCode.LLM_ERROR

    def test_database_error(self):
        """测试数据库错误"""
        error = ErrorFactory.database_error("read", "connection failed")

        assert isinstance(error, SystemError)
        assert error.code == ErrorCode.DATABASE_ERROR


class TestErrorHandler:
    """ErrorHandler 测试"""

    def test_to_user_friendly(self):
        """测试转换为用户友好的错误信息"""
        error = UserError(
            code=ErrorCode.VIDEO_NOT_FOUND,
            title="视频未找到",
            message="视频不存在",
            suggestion="请检查路径",
        )

        result = ErrorHandler.to_user_friendly(error)

        assert isinstance(result, ErrorDetail)
        assert result.code == ErrorCode.VIDEO_NOT_FOUND
        assert result.title == "视频未找到"

    def test_to_user_friendly_generic_exception(self):
        """测试处理通用异常"""
        error = ValueError("Some unknown error")

        result = ErrorHandler.to_user_friendly(error)

        assert isinstance(result, ErrorDetail)
        assert "Some unknown error" in result.message

    def test_is_retryable(self):
        """测试是否可重试"""
        retryable_error = ErrorFactory.ai_api_unavailable("openai")
        not_retryable_error = ErrorFactory.video_not_found("/path")

        assert ErrorHandler.is_retryable(retryable_error) is True
        assert ErrorHandler.is_retryable(not_retryable_error) is False

    def test_log_error(self):
        """测试记录错误
        
        loguru 不兼容 pytest caplog，使用 mock 验证调用。
        """
        from unittest.mock import MagicMock
        error = ErrorFactory.video_not_found("/path/to/video.mp4")
        
        mock_logger = MagicMock()
        ErrorHandler.log_error(error, mock_logger)
        
        # 验证 logger.error 被调用
        mock_logger.error.assert_called_once()


class TestErrorCode:
    """ErrorCode 枚举测试"""

    def test_error_code_values(self):
        """测试错误码值"""
        assert ErrorCode.VIDEO_NOT_FOUND.value == "E1001"
        assert ErrorCode.FFMPEG_ERROR.value == "E2001"
        assert ErrorCode.LLM_ERROR.value == "E3001"

    def test_error_code_from_str(self):
        """测试从字符串创建错误码"""
        code = ErrorCode("E1001")
        assert code == ErrorCode.VIDEO_NOT_FOUND


class TestErrorDetail:
    """ErrorDetail 测试"""

    def test_error_detail_creation(self):
        """测试 ErrorDetail 创建"""
        detail = ErrorDetail(
            code=ErrorCode.VIDEO_NOT_FOUND,
            title="测试标题",
            message="测试消息",
            suggestion="测试建议",
            context={"key": "value"},
        )

        assert detail.code == ErrorCode.VIDEO_NOT_FOUND
        assert detail.title == "测试标题"
        assert detail.suggestion == "测试建议"
        assert detail.context == {"key": "value"}
