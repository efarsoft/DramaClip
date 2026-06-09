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
            version="v2.0",
            description="为短剧高光片段合集生成精简、生动、连贯的AI解说脚本，支持原声保留控制",
            model_type=ModelType.TEXT,
            output_format=OutputFormat.JSON,
            tags=["短剧", "高光混剪", "解说脚本", "OST控制", "精简文案"],
            parameters=["drama_name", "plot_synopsis", "mix_mode_description", "segments"]
        )
        super().__init__(metadata, required_parameters=["drama_name", "plot_synopsis", "segments"])

        self._system_prompt = (
            "你是一名精通短剧解说与文案配音的资深自媒体人。"
            "你的输出必须是裸 JSON 字符串，绝对不要包含任何代码块符号或Markdown标记。"
        )

    def get_template(self) -> str:
        return """你是一名在抖音/B站拥有百万粉丝的短剧解说UP主，你的解说风格是：
- 开头必带悬念钩子（"你敢信？""谁能想到？""注意看！"）
- 擅长用反差、反转、吐槽制造戏剧效果
- 说话有情绪、有态度，像朋友在跟你八卦，而不是念新闻稿
- 每条解说虽然短，但要像"追剧预告"一样让人想继续听下去

现在需要为短剧《${drama_name}》的高光片段合集撰写解说脚本。

【全剧剧情梗概】
${plot_synopsis}

【输入高光片段列表】
${segments}

【混音模式】
${mix_mode_description}

【严格要求】
1. 必须针对输入的每一个高光片段（按顺序）撰写解说词或指定播放原声：
   - 若该片段拥有非常精彩的原声音效或大怒大喜台词（如争吵、告白、反转），且混音模式为混合解说，可设置 OST=1 (播放原声)，narration 固定写 "播放原片"。
   - 否则，设置 OST=2 (解说并降低背景原声音量)，在 narration 中写具体的解说词。

2. 解说词长度必须匹配片段时长（每段时长见 duration 字段）：
   - 3-5秒片段：15-25个汉字
   - 6-10秒片段：25-45个汉字
   - 10秒以上片段：45-65个汉字
   - 确保语速自然（约5字/秒），能在对应时长内念完

3. 解说风格示范（请模仿这种风格，而不是像新闻播报）：
   - ❌ 差的写法："女司机倒车撞车，责任明确"（像新闻标题，无聊）
   - ❌ 差的写法："面试通知来了"（太平淡）
   - ✅ 好的写法："注意看！这姐们倒车把人撞了，居然还倒打一耙要赔偿"（有态度、有情绪）
   - ✅ 好的写法："电话一响，命运直接翻盘——总裁要亲自面试她"（有悬念钩子）
   - ✅ 好的写法："监控一放，全场傻眼，撞人的竟然是她自己"（反转感强）
   - ✅ 好的写法："四百万的豪车没牌照？碰瓷哥这下慌了"（有反差、有看点）

4. 整体叙事要有"追剧感"：
   - 开头片段要有钩子，抓住观众
   - 中间片段要有起承转合，不能平铺直叙
   - 结尾片段要有悬念或情绪高潮，让人意犹未尽

5. **必须严格输出合法 JSON**，不要包含任何 markdown 代码块、解释文字或额外内容。
   - 优先使用 response_format=json 模式直接返回结构化对象。
   - 如果模型不支持，直接输出干净的 JSON 对象即可。

6. 解说词必须基于【全剧剧情梗概】来撰写，确保叙事逻辑与剧情一致，不要凭空编造不存在的情节。

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
