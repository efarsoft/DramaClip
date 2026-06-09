"""
成片级解说文案打磨提示词
用于 NarrationPipeline 在初稿生成后，进行全局优化：
- 提升叙事连贯性与故事感
- 优化情绪节奏与起伏
- 去除油腻、套路化、AI味语言
- 确保解说与画面/原声的自然配合
"""

from ..base import ParameterizedPrompt, PromptMetadata, ModelType, OutputFormat


class NarrationRefinementPrompt(ParameterizedPrompt):
    """成片级解说文案打磨提示词"""

    def __init__(self):
        metadata = PromptMetadata(
            name="narration_refinement",
            category="short_drama_narration",
            version="v2.0",
            description="对已生成的短剧高光解说初稿进行成片级打磨，提升故事性、情绪节奏和语言自然度",
            model_type=ModelType.TEXT,
            output_format=OutputFormat.JSON,
            tags=["短剧", "解说打磨", "成片优化", "去油腻", "情绪节奏"],
            parameters=["drama_name", "plot_synopsis", "mix_mode", "original_segments", "initial_script"]
        )
        super().__init__(metadata, required_parameters=["drama_name", "plot_synopsis", "original_segments", "initial_script"])

        self._system_prompt = (
            "你是一位顶级的短剧解说后期总监，擅长把AI初稿打磨成自然、专业、有感染力的成片文案。"
            "你的输出必须严格是合法的 JSON，不要任何多余文字。"
        )

    def get_template(self) -> str:
        return """你现在拿到了一份短剧高光混剪的**初稿解说脚本**，需要进行**成片级打磨**。

【剧名】
${drama_name}

【全剧剧情梗概】
${plot_synopsis}

【混音模式】
${mix_mode}

【原始高光片段信息】
${original_segments}

【当前初稿解说脚本】
${initial_script}

【打磨核心任务】
请对整份脚本进行全局优化，输出**打磨后的完整 JSON**（结构必须和输入一致，只修改 narration 字段，必要时可微调 OST）：

1. **故事连贯性**：确保解说整体像一个完整的小故事，有清晰的起承转合和逻辑推进。避免碎片化、重复、跳跃。解说内容必须与【全剧剧情梗概】一致，不要编造不存在的情节。
2. **情绪节奏**：优化情绪起伏曲线。高潮要更燃，过渡要自然，避免情绪平铺或突兀。
3. **语言自然度**：彻底去除油腻、套路、AI味表达（例如"震惊！""太燃了！""接下来会发生什么？"等低质金句）。使用更高级、克制、有画面感的语言。
4. **UP主风格强化**：
   - 像朋友在跟你八卦，而不是念新闻稿
   - 多用悬念钩子（"你敢信？""注意看！""谁能想到？"）
   - 多用反差、反转、吐槽制造戏剧效果
   - ❌ 避免："总裁招聘启动""豪车遭遇碰瓷"（新闻播报风）
   - ✅ 推荐："注意看！这姐们居然被碰瓷了，对方还狮子大开口"（有态度、有情绪）
5. **与画面/原声配合**：解说要真正服务于画面情绪和节奏。需要保留原声的段落要自然；需要解说的段落要精准补位。
6. **整体精炼**：根据每段时长调整解说长度（约5字/秒），但让整部成片听起来更专业、更有质感。

【输出要求】
- 必须返回**完整合法的 JSON**，结构与输入的 "items" 数组完全一致。
- 只修改 `narration` 字段，必要时可微调 `OST`。
- 不要添加任何解释、注释或 Markdown。
- 直接输出纯 JSON。

请开始专业打磨。
"""
