"""
短剧高光片段解说脚本生成提示词
专为 NarrationPipeline 中的高光混剪解说生成优化
"""

from ..base import ParameterizedPrompt, PromptMetadata, ModelType, OutputFormat


class HighlightNarrationPrompt(ParameterizedPrompt):
    """高光片段解说脚本生成提示词（NarrationPipeline 专用）"""

    def __init__(self):
        metadata = PromptMetadata(
            name="highlight_narration",
            category="short_drama_narration",
            version="v1.0",
            description="为短剧高光片段合集生成精简、生动、连贯的AI解说脚本，支持原声保留控制",
            model_type=ModelType.TEXT,
            output_format=OutputFormat.JSON,
            tags=["短剧", "高光混剪", "解说脚本", "OST控制", "精简文案"],
            parameters=["drama_name", "mix_mode_description", "segments"]
        )
        super().__init__(metadata, required_parameters=["drama_name", "segments"])

        self._system_prompt = (
            "你是一名精通短剧解说与文案配音的资深自媒体人。"
            "你的输出必须是裸 JSON 字符串，绝对不要包含任何代码块符号或Markdown标记。"
        )

    def get_template(self) -> str:
        return """你是一名顶级的短剧解说UP主，擅长为高光剪辑合集撰写极具戏剧冲突、幽默犀利的解说词。
现在需要为短剧《${drama_name}》的高光片段合集撰写AI解说脚本。

【输入高光片段列表】
${segments}

【混音模式】
${mix_mode_description}

【严格要求】
1. 必须针对输入的每一个高光片段（按顺序）撰写一小段解说词或指定播放原声：
   - 若该片段拥有非常精彩的原声音效或大怒大喜台词，且混音模式为混合解说，可设置 OST=1 (播放原声)，此时 narration 固定写 "播放原片"。
   - 否则，设置 OST=2 (解说并降低背景原声音量，若原声无声音可作为纯解说)，在 narration 中写具体的 AI 解说词。
2. 每一个片段的解说词（narration）必须极其精简！因为高光片段往往只有 3 至 8 秒：
   - 绝对不能写太长的句子！每个片段的解说词控制在 10 到 18 个汉字之间（5秒画面只能念约15个汉字），确保说话语速正常，能在对应时长内念完，绝对不要超长！
3. 解说词风格要生动高燃，具有极强的连贯叙事性，让片段与片段之间的解说词能自然衔接成一个小故事。
4. **必须严格输出合法 JSON**，不要包含任何 markdown 代码块、解释文字或额外内容。
   - 优先使用 response_format=json 模式直接返回结构化对象。
   - 如果模型不支持，直接输出干净的 JSON 对象即可。

输出格式必须严格如下：
{
  "items": [
    {
      "_id": 0,
      "OST": 2,
      "narration": "解说词写在这里"
    },
    ...
  ]
}
"""
