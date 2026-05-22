"""
模型管理器测试

测试模型下载、检测、删除功能
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.services.model_manager import (
    WHISPER_MODELS,
    STYLETTS2_MODEL,
    PYANNOTE_MODELS,
    check_whisper_model,
    check_styletts2_model,
    check_pyannote_model,
    get_whisper_model_size_on_disk,
    get_styletts2_model_size_on_disk,
    get_pyannote_model_size_on_disk,
    list_models,
)


class TestModelRegistry:
    """测试模型注册表"""
    
    def test_whisper_models_defined(self):
        """测试 Whisper 模型定义"""
        assert "tiny" in WHISPER_MODELS
        assert "base" in WHISPER_MODELS
        assert "small" in WHISPER_MODELS
        assert "medium" in WHISPER_MODELS
        assert "large-v3" in WHISPER_MODELS
        
        # 检查模型属性
        for name, model in WHISPER_MODELS.items():
            assert "id" in model
            assert "name" in model
            assert model["category"] == "asr"
            assert model["type"] == "whisper"
            assert "size_mb" in model
            assert "hf_repo" in model
    
    def test_styletts2_model_defined(self):
        """测试 StyleTTS2 模型定义"""
        assert STYLETTS2_MODEL["id"] == "styletts2"
        assert STYLETTS2_MODEL["category"] == "tts"
        assert STYLETTS2_MODEL["type"] == "styletts2"
        assert "hf_repo" in STYLETTS2_MODEL
    
    def test_pyannote_models_defined(self):
        """测试 Pyannote 模型定义"""
        assert "diarization-3.1" in PYANNOTE_MODELS
        assert "segmentation-3.0" in PYANNOTE_MODELS
        
        # 检查模型属性
        for name, model in PYANNOTE_MODELS.items():
            assert "id" in model
            assert "name" in model
            assert model["category"] == "diarization"
            assert model["type"] == "pyannote"
            assert "size_mb" in model
            assert "hf_repo" in model


class TestModelDetection:
    """测试模型检测功能"""
    
    @patch("app.services.model_manager._get_hf_model_dir")
    def test_check_whisper_model_not_found(self, mock_get_dir, temp_dir: Path):
        """测试检测不存在的 Whisper 模型"""
        mock_get_dir.return_value = temp_dir / "nonexistent"
        result = check_whisper_model("tiny")
        assert result is False
    
    @patch("app.services.model_manager._get_styletts2_cache_dir")
    def test_check_styletts2_model_not_found(self, mock_get_dir, temp_dir: Path):
        """测试检测不存在的 StyleTTS2 模型"""
        mock_get_dir.return_value = temp_dir / "nonexistent"
        result = check_styletts2_model()
        assert result is False
    
    @patch("app.services.model_manager._get_hf_model_dir")
    def test_check_pyannote_model_not_found(self, mock_get_dir, temp_dir: Path):
        """测试检测不存在的 Pyannote 模型"""
        mock_get_dir.return_value = temp_dir / "nonexistent"
        result = check_pyannote_model("diarization-3.1")
        assert result is False


class TestModelSize:
    """测试模型大小计算"""
    
    @patch("app.services.model_manager._get_hf_model_dir")
    def test_get_whisper_model_size_empty(self, mock_get_dir, temp_dir: Path):
        """测试获取不存在模型的大小"""
        mock_get_dir.return_value = temp_dir / "nonexistent"
        result = get_whisper_model_size_on_disk("tiny")
        assert result == 0
    
    @patch("app.services.model_manager._get_styletts2_cache_dir")
    def test_get_styletts2_model_size_empty(self, mock_get_dir, temp_dir: Path):
        """测试获取不存在 StyleTTS2 模型的大小"""
        mock_get_dir.return_value = temp_dir / "nonexistent"
        result = get_styletts2_model_size_on_disk()
        assert result == 0
    
    @patch("app.services.model_manager._get_hf_model_dir")
    def test_get_pyannote_model_size_empty(self, mock_get_dir, temp_dir: Path):
        """测试获取不存在 Pyannote 模型的大小"""
        mock_get_dir.return_value = temp_dir / "nonexistent"
        result = get_pyannote_model_size_on_disk("diarization-3.1")
        assert result == 0


class TestListModel:
    """测试模型列表功能"""
    
    def test_list_models_returns_all(self):
        """测试列出所有模型"""
        models = list_models()
        
        # 应该包含所有 Whisper 模型
        whisper_models = [m for m in models if m["category"] == "asr"]
        assert len(whisper_models) == len(WHISPER_MODELS)
        
        # 应该包含 TTS 模型（至少包含 styletts2，可能还有其他 TTS 模型）
        tts_models = [m for m in models if m["category"] == "tts"]
        assert len(tts_models) >= 1
        tts_ids = [m["id"] for m in tts_models]
        assert "styletts2" in tts_ids
        
        # 应该包含 Pyannote 模型
        diarization_models = [m for m in models if m["category"] == "diarization"]
        assert len(diarization_models) == len(PYANNOTE_MODELS)
    
    def test_list_models_has_required_fields(self):
        """测试模型列表包含必要字段"""
        models = list_models()
        
        for model in models:
            assert "id" in model
            assert "name" in model
            assert "category" in model
            assert "type" in model
            assert "size_mb" in model
            assert "downloaded" in model
            assert "disk_size_bytes" in model


class TestPyannoteIntegration:
    """测试 Pyannote 模型集成"""
    
    def test_pyannote_diarization_model_config(self):
        """测试 Pyannote 说话人分离模型配置"""
        model = PYANNOTE_MODELS["diarization-3.1"]
        
        assert model["id"] == "pyannote-diarization-3.1"
        assert model["name"] == "Pyannote Diarization 3.1"
        assert model["category"] == "diarization"
        assert model["type"] == "pyannote"
        assert model["size_mb"] == 1500  # 约 1.5GB
        assert model["hf_repo"] == "pyannote/speaker-diarization-3.1"
        assert "config.yaml" in model["required_files"]
    
    def test_pyannote_segmentation_model_config(self):
        """测试 Pyannote 分割模型配置"""
        model = PYANNOTE_MODELS["segmentation-3.0"]
        
        assert model["id"] == "pyannote-segmentation-3.0"
        assert model["name"] == "Pyannote Segmentation 3.0"
        assert model["category"] == "diarization"
        assert model["type"] == "pyannote"
        assert model["size_mb"] == 100  # 约 100MB
        assert model["hf_repo"] == "pyannote/segmentation-3.0"
        assert "pytorch_model.bin" in model["required_files"]
        assert "config.yaml" in model["required_files"]