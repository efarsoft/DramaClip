"""OpenAI 兼容 provider 的最小回归测试。"""

import unittest
from typing import Optional, Dict, Any
from copy import deepcopy

from app.config.unified_config import get_config, UnifiedConfig
from app.services.llm.base import TextModelProvider
from app.services.llm.manager import LLMServiceManager
from app.services.llm.providers import register_all_providers

# 获取统一配置实例
_config = get_config()


class DummyOpenAITextProvider(TextModelProvider):
    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def supported_models(self) -> list[str]:
        return []

    async def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 1.0,
        max_tokens: Optional[int] = None,
        response_format: Optional[str] = None,
        **kwargs
    ) -> str:
        return prompt

    async def _make_api_call(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return payload


def _reset_manager_state():
    LLMServiceManager._vision_providers.clear()
    LLMServiceManager._text_providers.clear()
    LLMServiceManager._vision_instance_cache.clear()
    LLMServiceManager._text_instance_cache.clear()


class OpenAICompatManagerTests(unittest.TestCase):
    def setUp(self):
        _reset_manager_state()
        # 保存原始配置
        self._original_settings = deepcopy(_config._settings)
        # 保存原始临时覆盖状态
        self._original_overrides = {}

    def tearDown(self):
        _reset_manager_state()
        # 恢复原始配置
        _config._settings = self._original_settings
        # 恢复临时覆盖状态
        if hasattr(self, '_original_overrides'):
            pass  # 不需要恢复，因为我们直接修改了_settings

    def test_register_all_providers_only_registers_openai_provider(self):
        register_all_providers()

        self.assertEqual({"openai"}, set(LLMServiceManager.list_text_providers()))
        self.assertEqual({"openai"}, set(LLMServiceManager.list_vision_providers()))

    def test_get_text_provider_uses_openai_keys(self):
        LLMServiceManager.register_text_provider("openai", DummyOpenAITextProvider)

        # 直接修改UnifiedConfig的内部状态
        _config._settings["openai_protocol"] = {
            "api_key": "new-key",
            "model": "new-model",
            "base_url": "https://new.example/v1",
            "max_tokens": 4096,
            "temperature": 0.7,
            "enabled": True,
        }

        provider = LLMServiceManager.get_text_provider()

        self.assertIsInstance(provider, DummyOpenAITextProvider)
        self.assertEqual("new-key", provider.api_key)
        self.assertEqual("new-model", provider.model_name)
        self.assertEqual("https://new.example/v1", provider.base_url)


if __name__ == "__main__":
    unittest.main()
