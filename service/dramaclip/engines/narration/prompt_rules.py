# 规则原文注册表：同 key 长短版合并保留最长（超集）——短版引用运行时拿长版，语义同源
RULE_TEXTS: dict[str, str] = {
    'no_same_ending_adjacent': '相邻段禁止同款收尾',
    'adjacent_episode_jump': '换集优先取相邻集，大跨度跳集只许跳往确有关键爆点的集，且前集段尾必须把跨集因果说破，禁止无因果跳切；',
    'hook_concrete_contrast': 'hook 必须含一个具体反差事实（身份/生死/数字），禁「他竟然…」式空泛悬念；',
    'question_ending_cap': '全稿以问号收尾的段至多两个，相邻段禁止同款收尾；',
    'core_motif_cap': '核心意象（数字+物件，如两千斤玄铁锅）全稿至多完整点名两次，再提只讲它带来的新后果。',
    'body_sensation_sparse': '每三到四段落一个人物的体感或心理瞬间（「脸上发烫」「攥紧了指节」式——用身体写内心，禁直呼「愤怒/悲伤」这类情绪名词）',
    'json_only': '只输出 JSON，不要多余文字。',
    'every_segment_episode': '每个片段都必须带 episode，一个都不能漏；',
    'time_within_transcript': 'start/end 取自转写台词的时间区间，不得超过该集上界；',
    'timeline_sorted_no_overlap': '同集内按时间递增且互不重叠；',
    'no_spoiler_climax': '禁剧透最大反转、禁空喊关注/点赞/收藏/二维码；',
    'cta_three_part': 'cta 必须是三段式转化引导（悬念半句+「点击左下角」+「免费/立即观看全集」，可带剧名）',
    'speaker_tag_realname': '台词前的[角色X]是声纹聚类标签，同一标签即同一个人：写文案时换成你从称呼与剧情推断出的真名，推断不出再保留原标签；',
    'metanarrative': '禁元叙述（零容忍）：解说员在讲故事不在讲文件——「第X集」「画面里」「镜头」「素材」这类字眼一个不许有，观众不该意识到这是被剪出来的视频。',
    'numerals_cn': '数字一律写中文（两千斤/八年/四十七块）：「2,000斤」是报表写法，配音念出来全毁。',
    'person_consistent': '人称二选一并全篇统一，禁止中途切换。',
    'no_fabrication': '所有情节、细节、台词必须来自给定转写，禁止编造转写外的事件或设定；',
    'anchor_from_transcript': '真实锚点（年份/金额/物件/称呼）只能原样摘自转写，转写里没有就少写，禁止为凑数发明',
    'characters_recognizable': '每个出场的人都要让观众认得出来（身份或关系随出场带一句）；同一人物全稿只用一个写法',
    'lines_cover_all_slots': 'lines 必须覆盖全部槽位 id；',
    'slot_contract': '文案必须完成该槽位的「要做的事」，不得答非所问；',
}


def assemble(template: str) -> str:
    """{key} 占位 → 规则原文。不用 str.format：提示词含字面花括号。"""
    for key, text in RULE_TEXTS.items():
        template = template.replace("{" + key + "}", text)
    return template
