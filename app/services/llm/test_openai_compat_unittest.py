"""OpenAI 兼容 provider 的最小回归测试。"""

import unittest

from app.config import config
from app.services.llm.base import TextModelProvider
from app.services.llm.manager import LLMServiceManager
from app.services.llm.providers import register_all_providers


class DummyOpenAITextProvider(TextModelProvider):
    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def supported_models(self) -> list[str]:
        return []

    async def generate_text(self, prompt: str, **kwargs) -> str:
        return prompt

    async def _make_api_call(self, payload: dict) -> dict:
        return payload


def _reset_manager_state():
    LLMServiceManager._vision_providers.clear()
    LLMServiceManager._text_providers.clear()
    LLMServiceManager._vision_instance_cache.clear()
    LLMServiceManager._text_instance_cache.clear()


class OpenAICompatManagerTests(unittest.TestCase):
    def setUp(self):
        _reset_manager_state()
        self._original_app = dict(config.app)

    def tearDown(self):
        _reset_manager_state()
        config.app.clear()
        config.app.update(self._original_app)

    def test_register_all_providers_only_registers_openai_provider(self):
        register_all_providers()

        self.assertEqual({"openai"}, set(LLMServiceManager.list_text_providers()))
        self.assertEqual({"openai"}, set(LLMServiceManager.list_vision_providers()))

    def test_get_text_provider_uses_openai_keys(self):
        LLMServiceManager.register_text_provider("openai", DummyOpenAITextProvider)

        config.app["text_llm_provider"] = "openai"
        config.app["text_openai_api_key"] = "new-key"
        config.app["text_openai_model_name"] = "new-model"
        config.app["text_openai_base_url"] = "https://new.example/v1"

        provider = LLMServiceManager.get_text_provider()

        self.assertIsInstance(provider, DummyOpenAITextProvider)
        self.assertEqual("new-key", provider.api_key)
        self.assertEqual("new-model", provider.model_name)
        self.assertEqual("https://new.example/v1", provider.base_url)


if __name__ == "__main__":
    unittest.main()
