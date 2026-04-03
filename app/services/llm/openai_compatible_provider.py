"""
OpenAI 兼容提供商实现

使用 OpenAI 官方 SDK 调用 OpenAI 兼容接口，支持文本和视觉模型。
"""

import io
import base64
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import PIL.Image
from loguru import logger
from openai import (
    APIError as OpenAIAPIError,
    AsyncOpenAI,
    AuthenticationError as OpenAIAuthError,
    BadRequestError as OpenAIBadRequestError,
    RateLimitError as OpenAIRateLimitError,
)

from app.config import config
from app.config.defaults import normalize_openai_compatible_model_name
from .base import TextModelProvider, VisionModelProvider
from .exceptions import APICallError, AuthenticationError, ContentFilterError, RateLimitError


def _normalize_model_name(model_name: str) -> str:
    """仅剥离误保存的 openai/ 前缀，保留完整模型名称。"""
    return normalize_openai_compatible_model_name(model_name)


def _is_response_format_error(message: str) -> bool:
    return "response_format" in (message or "").lower()


def _is_content_filter_error(message: str) -> bool:
    lowered = (message or "").lower()
    return "content_filter" in lowered or "safety" in lowered


def _clean_json_output(output: str) -> str:
    """清理 JSON 输出中的 markdown 包裹。"""
    output = re.sub(r"^```json\s*", "", output, flags=re.MULTILINE)
    output = re.sub(r"^```\s*$", "", output, flags=re.MULTILINE)
    output = re.sub(r"^```.*$", "", output, flags=re.MULTILINE)
    return output.strip()


class _OpenAICompatibleBase:
    """OpenAI 兼容 provider 共享逻辑。"""

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def supported_models(self) -> List[str]:
        # 兼容网关模型数量很多，运行时校验由远端完成。
        return []

    def _validate_model_support(self):
        logger.debug(f"OpenAI 兼容模型已配置: {self.model_name}")

    def _initialize(self):
        # SDK client 按请求参数动态构建，这里无需初始化全局状态。
        pass

    def _build_client(
        self,
        api_key_override: Optional[str] = None,
        base_url_override: Optional[str] = None,
        timeout_override: Optional[float] = None,
    ) -> AsyncOpenAI:
        """按请求构建 AsyncOpenAI 客户端，支持动态覆盖 api_key / base_url。"""
        api_key = api_key_override or self.api_key
        base_url = base_url_override or self.base_url or None

        timeout_seconds: float = timeout_override or config.app.get("llm_text_timeout", 180)
        max_retries: int = config.app.get("llm_max_retries", 3)

        return AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )


class OpenAICompatibleVisionProvider(_OpenAICompatibleBase, VisionModelProvider):
    """OpenAI 兼容视觉模型提供商。"""

    async def analyze_images(
        self,
        images: List[Union[str, Path, PIL.Image.Image]],
        prompt: str,
        batch_size: int = 10,
        **kwargs,
    ) -> List[str]:
        logger.info(f"开始使用 OpenAI 兼容接口 ({self.model_name}) 分析 {len(images)} 张图片")

        processed_images = self._prepare_images(images)
        results: List[str] = []

        for i in range(0, len(processed_images), batch_size):
            batch = processed_images[i : i + batch_size]
            logger.info(f"处理第 {i // batch_size + 1} 批，共 {len(batch)} 张图片")
            try:
                result = await self._analyze_batch(batch, prompt, **kwargs)
                results.append(result)
            except Exception as exc:
                logger.error(f"批次 {i // batch_size + 1} 处理失败: {exc}")
                results.append(f"批次处理失败: {exc}")

        return results

    async def _analyze_batch(self, batch: List[PIL.Image.Image], prompt: str, **kwargs) -> str:
        content = [{"type": "text", "text": prompt}]
        for img in batch:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{self._image_to_base64(img)}"},
                }
            )

        messages = [{"role": "user", "content": content}]
        model_name = _normalize_model_name(self.model_name)

        client = self._build_client(
            api_key_override=kwargs.get("api_key"),
            base_url_override=kwargs.get("api_base"),
            timeout_override=config.app.get("llm_vision_timeout", 120),
        )

        try:
            response = await client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=kwargs.get("temperature", 1.0),
                max_tokens=kwargs.get("max_tokens", 4000),
            )
            if response.choices and response.choices[0].message and response.choices[0].message.content:
                return response.choices[0].message.content
            raise APICallError("OpenAI 兼容接口返回空响应")
        except OpenAIAuthError as exc:
            logger.error(f"OpenAI 兼容接口认证失败: {exc}")
            raise AuthenticationError(str(exc))
        except OpenAIRateLimitError as exc:
            logger.error(f"OpenAI 兼容接口速率限制: {exc}")
            raise RateLimitError(str(exc))
        except OpenAIBadRequestError as exc:
            error_msg = str(exc)
            if _is_content_filter_error(error_msg):
                raise ContentFilterError(f"内容被安全过滤器阻止: {error_msg}")
            raise APICallError(f"请求错误: {error_msg}")
        except OpenAIAPIError as exc:
            logger.error(f"OpenAI 兼容接口 API 错误: {exc}")
            raise APICallError(f"API 错误: {exc}")
        except Exception as exc:
            logger.error(f"OpenAI 兼容接口调用失败: {exc}")
            raise APICallError(f"调用失败: {exc}")

    def _image_to_base64(self, img: PIL.Image.Image) -> str:
        img_buffer = io.BytesIO()
        img.save(img_buffer, format="JPEG", quality=85)
        return base64.b64encode(img_buffer.getvalue()).decode("utf-8")

    async def _make_api_call(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return payload


class OpenAICompatibleTextProvider(_OpenAICompatibleBase, TextModelProvider):
    """OpenAI 兼容文本模型提供商。"""

    async def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 1.0,
        max_tokens: Optional[int] = None,
        response_format: Optional[str] = None,
        **kwargs,
    ) -> str:
        messages = self._build_messages(prompt, system_prompt)
        model_name = _normalize_model_name(self.model_name)

        client = self._build_client(
            api_key_override=kwargs.get("api_key"),
            base_url_override=kwargs.get("api_base"),
            timeout_override=config.app.get("llm_text_timeout", 180),
        )

        completion_kwargs: Dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            completion_kwargs["max_tokens"] = max_tokens
        if response_format == "json":
            completion_kwargs["response_format"] = {"type": "json_object"}

        try:
            response = await client.chat.completions.create(**completion_kwargs)
            if response.choices and response.choices[0].message and response.choices[0].message.content:
                return response.choices[0].message.content
            raise APICallError("OpenAI 兼容接口返回空响应")

        except OpenAIBadRequestError as exc:
            error_msg = str(exc)
            # 某些网关不支持 response_format，回退到提示词约束模式
            if response_format == "json" and _is_response_format_error(error_msg):
                logger.warning("目标网关不支持 response_format，回退为提示词约束 JSON 输出")
                completion_kwargs.pop("response_format", None)
                messages[-1]["content"] += "\n\n请确保输出严格的JSON格式，不要包含任何其他文字或标记。"

                retry_response = await client.chat.completions.create(**completion_kwargs)
                if retry_response.choices and retry_response.choices[0].message and retry_response.choices[0].message.content:
                    return _clean_json_output(retry_response.choices[0].message.content)
                raise APICallError("OpenAI 兼容接口返回空响应")

            if _is_content_filter_error(error_msg):
                raise ContentFilterError(f"内容被安全过滤器阻止: {error_msg}")
            raise APICallError(f"请求错误: {error_msg}")

        except OpenAIAuthError as exc:
            logger.error(f"OpenAI 兼容接口认证失败: {exc}")
            raise AuthenticationError(str(exc))
        except OpenAIRateLimitError as exc:
            logger.error(f"OpenAI 兼容接口速率限制: {exc}")
            raise RateLimitError(str(exc))
        except OpenAIAPIError as exc:
            logger.error(f"OpenAI 兼容接口 API 错误: {exc}")
            raise APICallError(f"API 错误: {exc}")
        except Exception as exc:
            logger.error(f"OpenAI 兼容接口调用失败: {exc}")
            raise APICallError(f"调用失败: {exc}")

    async def _make_api_call(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return payload
