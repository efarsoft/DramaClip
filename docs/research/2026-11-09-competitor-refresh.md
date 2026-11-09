# 竞品工具增量调研（2026-11-09）

基线：`docs/research/2026-09-22-competitor-teardown.md`（六本地项目深读，借鉴点多数已落地）。
本篇只做**增量**：2026-09 之后的新版本/新能力 + 旧调研未覆盖的外部竞品（商业工具、短剧 CPS 专用工具）。
全程只读调研，未改任何代码、未执行 git 写操作。所有来源访问日期均为 **2026-11-09**。

证据分级：【一手】= 官方仓库源码/README/Release 原子订阅原始时间戳、官网、官方应用商店描述、法规原文；【二手】= 媒体/评测/社区文章；找不到一手来源的标「未核实」。
GitHub releases 页网页摘要年份不可靠，本篇版本日期一律以 `releases.atom` / `commits.atom` 的原始 UTC 时间戳核实。

---

## 1. 开源项目动态速览

| 项目 | 最新版本（atom 核实） | 2026-09 后增量判定 |
|---|---|---|
| NarratoAI (linyqh/NarratoAI) | v0.8.7，2026-07-17 | **无功能增量**。9 月后 commit 仅文档/赞助变更（2026-10-24 最新）。短剧解说/混剪早在 2024-12～2025-05 已有，旧调研已覆盖 |
| HotClip (xixihhhh/hotclip) | v0.33.0，2026-10-26 | **旧调研未覆盖的新对象**，9-10 月密集发布 v0.28→v0.33，本篇差距主要来源 |
| MoneyPrinterTurbo (harry0703) | v1.3.10，2026-11-07 | v1.3.7(09-13)→v1.3.10 四个版本增量，见 §1.2 |
| ShortGPT (RayVentura) | v0.3.0，2025-02-10 | **停滞**。最后 commit 2025-02-10（Gemini key 支持），无继任项目，不再跟踪 |
| VideoLingo (Huanshere) | v3.1.1，2026-09-27 | v3.1.0/3.1.1 双版本增量，见 §1.3 |
| FunClip (modelscope) | v2.2.1，2026-09-01 | v2.2.x 新增 MOSS 说话人感知切片（08-30/09-01，旧调研临界点）；9 月后 commit 仅文档/修复 |
| JJYB 智剪 (jianjieyiban) | v3.4.5，2026-11-07 | v3.4.0(10-18)→v3.4.5 密集工程修复 + 教程更新至 v3.4.0，见 §1.4 |

来源（一手）：各项目 `releases.atom` / `commits.atom`，如 https://github.com/linyqh/NarratoAI/commits/main.atom 、https://github.com/harry0703/MoneyPrinterTurbo/releases.atom 、https://github.com/RayVentura/ShortGPT/commits/stable.atom 等，访问 2026-11-09。

### 1.1 HotClip（新增重点对象）
【一手】README：https://github.com/xixihhhh/hotclip （raw: https://raw.githubusercontent.com/xixihhhh/hotclip/main/README.md），访问 2026-11-09。
定位：AGPL-3.0 本地 AI 直播切片/长视频切条工作台（Electron 系，Win/macOS/Linux），口号与 DramaClip 高度同源：「素材不出你的电脑」「AI 每一刀都有理由」「宁可不做不可做错」。虽主打直播切片而非短剧，但**发布侧与质量工程侧能力显著超出旧调研六项目**，是本篇差距清单主源。
9 月后版本要点（一手 release notes，https://github.com/xixihhhh/hotclip/releases ）：
- v0.28.0(09-05)：SRT/WebVTT 字幕导入、长稿跨句搜索、局部时间校准（试听/确认/撤销）、本地转写分段续跑、可选 Qwen3-ASR。
- v0.29.0(09-16)：台词+画面统一搜索、字词定位、上下文试听。
- v0.30.0(09-23)：「相近台词」模糊搜索（仅差一字，明确标近似命中）。
- v0.31.0(09-23)：逐句稿按说话人 S1/S2 筛选，搜索/选段同步收窄。
- v0.33.0(10-26)：时长档（新增 60-120s）与候选数量（1-12）常驻控件并透传 CLI/MCP/监听；品类自定义判据；重试保留任务设置快照。
README 常驻能力（发布日均已存在，具体落地版本未逐一核实）：九路证据链爆点检测、发布反馈台账+本地 A/B 实验中心、平台发布包、字幕安全区九平台遮罩、气口跳剪+剪口头禅、双档人声增强（DPDFNet2）、出片自我质检+自修复、高潮前置/爆点闪现、MCP Server/Headless CLI/Agent Skill、质量黄金集 eval、分发留证包、敏感词音频静音、AIGC 标注助手、clips.json 处理回执。

### 1.2 MoneyPrinterTurbo v1.3.7→v1.3.10
【一手】release notes：https://github.com/harry0703/MoneyPrinterTurbo/releases ，访问 2026-11-09。
定位仍是「文案→库存/AI 素材→成片」的通用短视频生成器，**不是短剧源片剪辑**，与 DramaClip 主链路距离远；可借的增量：
- v1.3.7(09-13)：**逐字字幕 + 弹跳弹簧动画**（显示模式与动画独立控制）；Azure/Edge TTS **原生停顿标签 `[pause: 2s]`** 保持旁白与字幕对齐；Kokoro/VoxCPM TTS；BGM 预设浏览器内试听。
- v1.3.8(10-03)：**VoxCPM 参考音频克隆 + delivery conditioning（继承参考音频的节奏/情绪）**，本地 Whisper 重转写参考文本；素材下载/切片/渲染全程连续进度上报；BT.709 色彩矩阵统一；可选**本地视频项目 CLI：修订追踪 + 变更对比 + 未变渲染产物复用**。
- v1.3.9(10-21)：官方 `mpt` pip 包（`mpt webui` / `mpt cli`）；可选本地 SDXL 图像服务（空闲 GPU 卸载）；诊断日志分级 + API 请求脱敏追踪。
- v1.3.10(11-07)：Codex/ChatGPT OAuth 订阅接入；长任务阶段化反馈、刷新不丢任务、防重复提交；阿拉伯文 subtitle shaping（撞多语锁，不追）。
- 另有 Upload-Post 自动发布集成（v1.3.6 起）：第三方云发布聚合，观察项（见 G14 注）。

### 1.3 VideoLingo v3.1.0 / v3.1.1（均 2026-09-27）
【一手】release notes：https://github.com/Huanshere/VideoLingo/releases ，访问 2026-11-09。
主赛道是翻译（撞 DramaClip 多语锁），但三项增量与锁无关：
- **Qwen3-ASR 成为默认本地 ASR + Qwen3-ForcedAligner 词级对齐**（1.7B 默认/0.6B 轻量）；WhisperX 不再自动安装。
- **本地 HTTP API 取代 Excel 批处理**（`uv run start.py --api`），脚本/Agent 与网页同管线。
- v3.1.1：Fish Audio 官方克隆（15-30s 源视频直接克隆、不落账号音色）；**配音失败可见可恢复**——重试后仍失败即停、语速封顶、塞不下的行落 `output/log/dub_truncated.json` 清单（与旧调研 A1「人工清单出口」哲学收敛，DramaClip 已落地同类机制）。
- v3.0.4(09-15)：ASR 转写按源文件内容+识别设置缓存复用（`.cache/asr`），成功段在后续失败中幸存——与 DramaClip 内容寻址缓存同构。

### 1.4 JJYB 智剪 v3.4.0→v3.4.5
【一手】release notes：https://github.com/jianjieyiban/JJYB_AI_VideoAutoCut/releases ；使用教程（适用 v3.4.0+，更新 2026-10-18）：https://github.com/jianjieyiban/JJYB_AI_VideoAutoCut/blob/videoautocut/docs/使用教程.md ，访问 2026-11-09。
增量以**工程修复与质量纪律收敛**为主，新功能少：
- v3.4.1(10-31)：字幕时间戳重映射（片段重拼后跟随新时间轴）；Edge TTS 真实词边界、不伪造逐字时间；必需配音/字幕失败即停；新增 pytest 套件。
- v3.4.3(11-06)：快切合并重构为「逐段归一化 + concat 流复制」，失败回退 filter_complex，错误透传 ffmpeg 原因。
- v3.4.4(11-07)：修复 BGM `-shortest` 把 180s 成片截成 0.16s——四层防护（stream_loop 循环填充/选曲排除<15s 音效/配乐后时长兜底校验/concat 时长校验回退）。**与 DramaClip「曲库自动铺底」直接相关的反面教材+防护清单**。
- v3.4.5(11-07)：快切按累计时间边界分配帧数防逐段取整累积漂移；中间片段 MOV/PCM、最终只编码一次 AAC；**素材不足明确拒绝，不再静默缩短目标**（v3.4.2 曾「按可用时长 95% 出片」，被推翻）；真实 FFmpeg 120 段回归、0.35s 容差不放宽。
- 判定：JJYB 正在向 DramaClip 的「诚实失败/真机回归」哲学收敛，**无新的上位能力**；其 BGM 截断四层防护值得对照自查（DramaClip 已有响度/时长审计，需确认曲库铺底无 `-shortest` 类截断路径）。
- 注意：JJYB 许可证为**仅个人学习、禁止商用**（release notes 原文），借鉴机制不抄代码。

### 1.5 FunClip v2.2.x（增量在旧调研临界点，补记）
【一手】release notes：https://github.com/modelscope/FunClip/releases ，访问 2026-11-09。
- v2.2.0(08-30)/v2.2.1(09-01)：可选 `--model moss` 接 OpenMOSS **MOSS-Transcribe-Diarize**（本地/远程 vLLM 服务）：单模型长音频 ASR + 匿名说话人标签 + 段级时间戳，无需外挂 VAD/说话人模型；支持说话人 SRT 与按说话人切片；末段截断显式失败不静默丢。
- **官方明确边界：MOSS 只给同一录音内匿名标签（spkS01…），不做已知人物身份识别、无声纹验证**；时间戳段级，精确任意文本切片仍靠 Paraformer。
- 对 DramaClip：CAM++ + 角色真名已是上位替代（见 §5），MOSS 仅作为「单模型免分离栈」的备选路线记录，不追。

---

## 2. 商业/半商业工具（只记与短剧推广成片自动化相关项）

| 工具 | 状态与相关能力 | 证据 |
|---|---|---|
| 剪映专业版 | 官网明示：**智能解说粗剪**（智能生成解说词并粗剪）、**智能剪口播**（AI 识别无效词、对着文本剪）、一站式 AI 成片、文本朗读、数字人、人声分离、响度统一、AI 音效 | 【一手】https://www.jianying.com/ ，访问 2026-11-09。操作细节（素材右键→智能解说粗剪）见【二手】https://zhuanlan.zhihu.com/p/1984204810292053952 （2025-12-16） |
| 度加（百度） | 已从「度加剪辑」转型**度加AI 创作 Agent**：对话式创作、热点推荐、**定时托管**、团队管理、数据中心；Web 端功能：AI 成片（文案→视频）、AI 剧本（分集分镜）、动漫视频、**高光剪辑**（长视频自动识别精彩片段）、数字人、**声音克隆（10 秒音频）** | 【一手】https://aigc.baidu.com/welcome （正文可抓取）；官方 App Store 描述 https://apps.apple.com/cn/app/id1552875358 （4.41.0，10-23 更名强化 Agent）；https://ducut.baidu.com/ 为 JS 壳无正文。访问 2026-11-09 |
| 腾讯智影 | **已退场**：2025-04 公告 6-30 起暂停服务、删除用户数据；官网 zenvideo.qq.com 今实测无法建立连接（SSL EOF） | 公告内容【二手】https://finance.sina.com.cn/roll/2025-04-26/doc-ineupaav8472953.shtml 、https://news.qq.com/rain/a/20250905A06W5T00 ；官网不可达为本次实测。访问 2026-11-09 |
| 一帧秒创 | 图文转视频、AI 帮写、数字人播报/直播/定制、PPT 转视频 | **未核实**：官网 aigc.yizhentv.com / www.yizhentv.com 本次均无法访问（后者证书异常）。功能描述仅【二手】https://top.aibase.com/tool/yizhenmiaochuang 、https://nav.newrank.cn/site/379 。与短剧源片剪辑相关性低 |
| 快影（快手） | **AI 文案成片**（App Store 官方描述主打，含 DeepSeek R1 免费用）、智能配音、语音加字幕、画质增强/一键修复/智能插帧、创作中心（看数据找灵感） | 【一手】官方站 https://h5.kwaiying.com/officialWebsite （正文可抓取）；官方 App Store 描述 https://apps.apple.com/cn/app/id1195860596 。访问 2026-11-09 |
| 必剪（B站） | **花生AI**（输入文案/口播匹配素材成片）、批量粗剪、游戏高光识别、文本朗读、语音转字幕、一键发布 B 站；必剪Studio：数字分身+音色定制 | 【一手】官方 App Store 描述 https://apps.apple.com/cn/app/id1299589486 ；官网 https://bcut.bilibili.cn/ 为 JS 壳，「花生AI」文案取自其搜索引擎收录的官方页摘要；必剪Studio https://member.bilibili.com/york/bilibili-studio/ 。访问 2026-11-09 |

判定：商业工具中**唯一与 DramaClip 核心链路正面重叠的是剪映「智能解说粗剪」**（单素材→解说词+粗剪），但其无跨集编排、无卖点互异多方案、无复述质检重写循环、无角色原声克隆（见 §5 对照）。度加/快影/必剪的「文案成片」是库存素材匹配路线，与短剧源片推广不同赛道；度加「高光剪辑」与 DramaClip 冲突峰选段同构但云端。「定时托管/创作 Agent/数据中心」是商业侧共同趋势，对应差距 G1/G8。

---

## 3. 短剧 CPS/分销专用新兴工具（2025-2026）

| 工具 | 能力（官方描述原文要点） | 证据 |
|---|---|---|
| 推剧助手-AI短剧解说智能体 | 上传素材一键生成解说/配音/字幕、内置爆款风格、三步操作；订阅制（月 78 元档）；Android 版官方描述另有「一键去重、视频去字幕、视频提取文案」工具箱 | 【一手】https://apps.apple.com/us/app/id6786110530 （1.1.1，9-22 更新）；【一手】应用宝官方页 https://sj.qq.com/appdetail/com.startupcloud.filmhelper 。访问 2026-11-09 |
| 剧说-AI短剧解说智能体 | 一键生成解说、内置爆款风格、极简操作；月卡+积分制 | 【一手】https://apps.apple.com/cn/app/id6760341675 。访问 2026-11-09 |
| 剧小通 | 现名「剧小通-AI剪辑短剧影视二创解说」：短剧数据分析（热门趋势/潜力爆款）+ **短剧挂载变现** + 智能剪辑，一站式短剧变现服务 | 【一手】https://apps.apple.com/cn/app/id6740080788 （描述从页面内嵌 JSON 提取）。访问 2026-11-09 |
| 智剪-视频一键去重 等 | 去重/抗比对卖点工具 | 仅商店 listings 线索；**撞锁不追**，不展开 |
| 剪映草稿 Agent 生态 | jianying-editor-skill（MIT，UI 自动化读写剪映，文案→配音→字幕→音乐→导出全流程）；jianying-headless（2026-09-15 出现，剪映专业版 macOS 无界面自动化，JSON 剪辑计划→原生草稿→本机引擎导出）；pyJianYingDraft（草稿生成库） | 【一手】https://github.com/isYangs/jianying-editor-skill 、https://github.com/GdLinkLock/jianying-headless （标注 Private source preview，源码完整性未核实）、https://github.com/GuanYixuan/pyJianYingDraft ；热度背景【二手】https://zhuanlan.zhihu.com/p/2085294953937246000 。访问 2026-11-09。**草稿路线整体撞锁**，但其「Agent 一句话驱动剪辑」的产品形态是趋势信号（对应 G8） |
| 红果/抖音解说漫剧新政周边 | 解说漫剧类型系数提升、60 分钟 AI 剧保底，催生「解说剧一键成片」生产工具（如巨日禄AI） | 【二手】https://www.pingwest.com/a/317444 （2026-09-15）、https://www.csdn.net/article/2026-08-02/163399833 。属**制作端**（AI生成漫剧）非推广剪辑端，与 DramaClip 相邻不重叠，仅记市场信号。未核实一手 |

判定：CPS 专用工具（推剧助手/剧说/剧小通）验证了「短剧推广一键解说」是真实付费赛道，但其能力描述停留在「模板风格+一键生成」，**无一家公开宣称跨集编排、卖点互异、质检重写、角色原声克隆、本地不出机**——DramaClip 的质量纵深仍是差异化。它们的独有价值在**业务侧**：挂载变现通道、选剧数据、去重（撞锁）。

---

## 4. 差距清单（核心产出：竞品有而 DramaClip 没有）

成本口径：小 ≈ <1 周；中 ≈ 1-3 周；大 ≈ >1 月。已对照现码核实「DramaClip 没有」的项：G1-G5、G7-G12（grep 无安全区/跳剪/发布包/A-B 实现；发布回流仅手录三项）。

### G1. 发布反馈对账 + 本地 A/B 实验中心（HotClip）
- **是什么**：每条成片登记稳定内容 ID 与发布状态，一键生成待回填 CSV；导入播放/互动后按 ID 或唯一标题**保守对账**（未匹配/歧义行明确列出）；一片多版自动按原候选/导出批次/平台建对照组，只比较同平台、72h 内发布、每版 ≥500 播放且数据齐全的版本，输出「等待/证据不足/差异不明显/方向性领先」四态，不作单变量因果承诺；表现规律回流下一轮选段。
- **证据**：【一手】HotClip README「发布合规」节，https://github.com/xixihhhh/hotclip ，访问 2026-11-09。
- **现状**：DramaClip 有手录回流（平台/播放量/完播率必填，`desktop/src/features/works/WorksDetailPage.tsx` W8），但无内容 ID 对账、无多版对照组、无样本门槛判定、无规律回流选段。
- **价值**：DramaClip 每模式 K 条卖点互异方案天然就是 A/B 实验组——这是「自进化原料」从录入升级为**统计闭环**的最短路径，直接服务首要质量线。
- **成本**：中（内容 ID 贯穿导出报告+回流表、对账逻辑、四态判定；四态读数哲学现成）。

### G2. 逐平台发布包（HotClip）
- **是什么**：导出后按平台整理齐套物料到「发布包/」：每平台一个文件夹，视频硬链接不占双份磁盘、**按平台画幅重裁封面**（小红书 3:4、B站 16:10、视频号 6:7）、**按平台上限适配文案**（如小红书标题硬截 20 字、话题数按平台建议），manifest 记录适配了什么。
- **证据**：【一手】HotClip README「审阅与工作流」节，同上 URL，访问 2026-11-09。
- **现状**：DramaClip 发布物料是通用一套（8 候选标题+文案+标签+钩子帧封面，`engines/narration/titles.py`），无平台差异化适配。
- **价值**：短剧推广是多平台分发业务；标题超限/封面画幅不符是真实的发布摩擦与点击率损失。
- **成本**：小-中（平台规则表 + 封面重裁 + 文案截断/标签数适配 + manifest；规则表需持续维护）。

### G3. AIGC 隐式标识（文件元数据）+ 逐平台标注指引
- **是什么**：《人工智能生成合成内容标识办法》（2025-09-01 施行）第 4 条要求视频起始画面等位置显式标识、**导出文件须含显式标识**；第 5 条要求**文件元数据中添加隐式标识**（生成合成属性、服务提供者名称/编码、内容编号）；第 6 条要求传播平台核验元数据。HotClip 提供「AIGC 标注助手」：按平台给标注文案与操作入口指引、一键复制。
- **证据**：【一手】法规原文 https://www.cac.gov.cn/2025-03/14/c_1743654684782215.htm ，访问 2026-11-09；【一手】HotClip README「发布合规」节。
- **现状**：DramaClip **已有显式标注**（`engines/exporter/ai_label.py`，右上角烧「AI 生成」，用户开关默认关——业主 2026-10-15 裁决，本篇不重议该裁决）；但 Phase B 做**元数据擦除**（`encoder.py`），无隐式标识写入，也无逐平台发布声明指引。
- **价值**：TTS 配音+字幕烧录成片属生成合成内容；平台核验元数据趋势下，隐式标识是合规硬需求；擦除元数据与写入 AIGC 属性可并存（擦源留标）。
- **成本**：小（ffmpeg `-metadata` 写入属性/编码/内容编号 + 发布物料附平台声明指引文案）。注意：是否默认开启建议同显式标注走业主裁决。

### G4. 字幕安全区预览（HotClip / NarratoAI）
- **是什么**：预览时一键叠加平台 UI 遮挡遮罩（抖音/快手/B站竖屏/视频号/小红书/TikTok/Reels/Shorts+通用并集九档，按实测数据绘制），确保烧录字幕不被平台互动区/通栏吃掉。
- **证据**：【一手】HotClip README「审阅与工作流」节，访问 2026-11-09；【一手】NarratoAI v0.8.2/0.8.3 release notes（字幕安全区+预览，2026-06）https://github.com/linyqh/NarratoAI/releases 。
- **现状**：DramaClip ASS 烧录无安全区预览/校验（现码 grep 无实现；ai_label 仅自身避开顶部/底部 3%）。
- **价值**：字幕被平台 UI 遮挡=完播率直接损失；短剧推广全竖屏信息流，命中首要质量线。
- **成本**：小（遮罩 PNG/SVG 叠层预览 + ASS MarginV 约束校验；遮罩数据需实测维护）。

### G5. 语音感知气口跳剪 + 剪口头禅（HotClip / 剪映）
- **是什么**：剪掉停顿静音与嗯/呃/结巴重复并拼接，字幕时间轴同步重映射；HotClip 用「无词 + 声学静默 + 本地 VAD 无人声」**三重门**防误删（ASR 漏词/轻声尾音/笑声掌声不删），可选留 0.25s 呼吸口，词表刻意保守，剪了什么逐条写回执；剪映「智能剪口播」同思路（AI 识别无效词、对着文本剪）。
- **证据**：【一手】HotClip README「成片质量」节 + v0.26.0 release notes（629KB sherpa-onnx VAD 模型、0.6s 尾音保护硬上限），访问 2026-11-09；【一手】https://www.jianying.com/ （智能剪口播）。
- **现状**：DramaClip 有台词保护区+两级吸附，但无去气口/口头禅跳剪。
- **价值**：解说/对谈/口播类模式的节奏紧凑度直接影响完播率；「宁可不做不可做错」的三重门与 DramaClip 质量哲学同构。
- **成本**：中（VAD 证据通道 + 跳剪后字幕/混音时间轴重映射；sherpa-onnx 属轻依赖，不撞 torch 锁）。⚠️ 只作用于旁白/原声停顿，不得侵入台词保护区。

### G6. 双档人声增强（HotClip，观察项）
- **是什么**：基础档双高通+温和谱减；智能档按需下载 ~10MB SHA-256 校验的 DPDFNet2 本地 48kHz 模型，在剪辑组装后、音效/BGM 混入前只处理讲话原声，异常自动回退基础档并在回执区分「生效/回退/未应用」。
- **证据**：【一手】HotClip v0.27.0 release notes（2026-08-31）+ README，访问 2026-11-09。
- **价值**：短剧源音质量参差时提升听感；处理顺序（先增强后包装再响度）值得直接采纳。
- **成本**：中。优先级低于 G5；DramaClip 现有混音链若已够用可缓行。

### G7. 出片后视频级自我质检 + 安全自修复（HotClip）
- **是什么**：成片后检测黑屏/长静音/冻结帧/主体出框/响度/时长/**切点半词**，写入回执；冻结与构图问题只提醒人工回放，可安全自愈的告警当场修复、**修完重检变好才采纳**。
- **证据**：【一手】HotClip README「成片质量」节，访问 2026-11-09。
- **现状**：DramaClip 有渲染后时长审计与 conversion gate，但无视频级黑屏/冻结/半词切点复检。
- **价值**：把「质量优先宁可失败」从规划期延伸到成片期；半词切点复核与两级吸附互补。
- **成本**：中（ffprobe/抽帧检测器 + 三态回执；自修复谨慎，先做只读检测）。

### G8. Headless CLI / MCP Server / Agent Skill / 目录监听无人值守（HotClip；VideoLingo HTTP API；剪映 skill 生态）
- **是什么**：HotClip 提供与桌面产物一致的 CLI（transcribe/highlights/clip/feedback/doctor）、本地 MCP 三工具、官方 Agent Skill、录播目录 7×24 监听+webhook、持久任务队列（重启标「已中断」不偷偷续跑）；VideoLingo 本地 HTTP API 让脚本/Agent 走同一管线；剪映生态出现 editor-skill/headless 等 Agent 驱动剪辑项目（草稿路线撞锁，但产品形态是信号）。
- **证据**：【一手】HotClip README「批量与生态」节；https://github.com/Huanshere/VideoLingo/releases v3.1.0；https://github.com/isYangs/jianying-editor-skill 。访问 2026-11-09。
- **现状**（parent 现码复核修正）：DramaClip **已有对外 HTTP 网关**（`api/agent_gateway.py`，回环+令牌鉴权，v0.2.2 落地），但只暴露文本能力四件套（文案审查/复述质检/草拟标题）；**整片生产链（分析→编排→出片）无对外自动化接口**——无 CLI/MCP/目录监听。差距在「生产链无人值守」，不在「有无网关」。
- **价值**：80 集×九模式×K 方案的矩阵产能天然适合批处理/Agent 编排；「素材不出本机」的本地 MCP 与锁完全兼容。
- **成本**：中（复用现有 JSON-RPC 服务层包一层 CLI/MCP；监听可后置）。

### G9. 质量黄金集量化回归（HotClip）
- **是什么**：`quality:eval` 固定样本集本地输出 CER/WER、词边界中位/P95 误差、爆点 recall@3/@5；换模型/调阈值先跑同一套样本，质量变化有数可查；另有本地 VLM 对比命令（同批样本比较多模型成功率/耗时）。
- **证据**：【一手】HotClip README「批量与生态」节，访问 2026-11-09。
- **现状**：DramaClip 有真机回归门禁，但缺**量化黄金集指标**（门禁多为通过/失败，非分数漂移）。
- **价值**：CAM++/paraformer/Qwen3-VL 任何换型都有客观依据；与「三态读数」互补。
- **成本**：小-中（标注固定样本 + 指标脚本，进 CI 门禁）。

### G10. 分发留证包（HotClip）——⚠️ 撞既有裁决，不推荐立项
- **是什么**：每条切片对应源片区间落 CSV 台账，可选保存前后 3 分钟源片切段——授权切片被质疑搬运时证据链拿得出手。
- **证据**：【一手】HotClip README「发布合规」节，访问 2026-11-09。
- **裁决冲突（parent 复核）**：业主 2026-09-10 已否决「授权存证」方向（现实中不存在授权书/有效期物件，上游只给片单；工具侧不替用户证明授权）。留证包本质是同一方向的变体，**按既定裁决不追**；如业主未来重议授权链路再启。

### G11. 敏感词音频静音（HotClip，观察项）
- **是什么**：按逐字稿时间把自定义词表对应音频精确静音，跳剪/拼接后仍精确映射；字幕与逐字稿保留原文便于追溯。
- **证据**：【一手】HotClip README「发布合规」节，访问 2026-11-09。
- **价值**：平台违禁词导致的限流/下架是推广实际风险；DramaClip 质检重写管文案侧，音频侧静音是兜底。
- **成本**：小-中。⚠️ 与「复述质检+重写」优先级重叠，先评估重写是否已覆盖。

### G12. 逐字字幕动画 + 原生停顿标签（MoneyPrinterTurbo）
- **是什么**：逐字显示字幕 + 弹跳弹簧动画（模式/动画独立控制）；TTS 脚本原生 `[pause: 2s]` 停顿标签保持旁白与字幕对齐。
- **证据**：【一手】https://github.com/harry0703/MoneyPrinterTurbo/releases v1.3.7（2026-09-13），访问 2026-11-09。
- **价值**：字幕金句流/超短钩子模式的节奏表现力；停顿标签给解说文案显式节奏控制（比 atempo 更自然）。
- **成本**：小-中（ASS 逐字 override 现成可做；停顿标签需 TTS 引擎支持或分段合成拼接，与现有长文本切分兼容）。

### G13. 新引擎选项（观察项，不急于移植）
- Qwen3-ASR + Qwen3-ForcedAligner 词级对齐（VideoLingo v3.1.0 默认；HotClip 可选）：paraformer 的潜在替代/补强，重依赖走独立运行环境可兼容锁，**仅当词级精度成实测瓶颈再评估**。【一手】https://github.com/Huanshere/VideoLingo/releases 。
- VoxCPM 克隆 + delivery conditioning（MPT v1.3.8；NarratoAI v0.8.7 亦接 VoxCPM）：「继承参考音频节奏/情绪」是 IndexTTS-2.5 之外的新能力维度，同上重依赖纪律。【一手】https://github.com/harry0703/MoneyPrinterTurbo/releases 。
- 访问 2026-11-09。

### G14. CPS 业务侧集成：挂载变现 / 选剧数据（剧小通、推剧助手）
- **是什么**：剧小通把「数据分析选剧 + 智能剪辑 + 挂载变现」做成一站式；推剧助手面向推广者收订阅费。
- **证据**：【一手】https://apps.apple.com/cn/app/id6740080788 、https://sj.qq.com/appdetail/com.startupcloud.filmhelper ，访问 2026-11-09。
- **价值**：验证付费需求；挂载通道是变现最后一公里。
- **成本**：大（外部平台商务/API 对接，非纯工程）。**观察项**：DramaClip 当前定位是出片工具，业务集成属产品决策而移植成本估计；选剧数据需外部数据源，与「素材不出本机」不冲突但引入新外部依赖，需纪律评审。

---

## 5. 竞品做了、但 DramaClip 明确更强（防盲目跟进）

| 能力 | 竞品形态（证据） | DramaClip  stronger 在哪 |
|---|---|---|
| 说话人→角色 | FunClip MOSS 仅匿名 spkS01 标签，官方明示不做身份识别/声纹（v2.2.1 release notes，一手） | CAM++ 分离 + **角色真名**绑定，解说文案可直接称名 |
| 解说编排 | 剪映智能解说粗剪=单素材生成解说词+粗剪（jianying.com，一手）；推剧助手/剧说=内置爆款风格模板一键生成（App Store，一手） | **跨集**编排、每模式 K 条卖点互异、十二叙事母题卡、复述质检+重写循环——叙事纵深无对手 |
| 声音克隆 | 度加 10s 云端克隆（aigc.baidu.com，一手）；VideoLingo Fish Audio 云 API（release notes，一手） | IndexTTS-2.5/CosyVoice **本地角色原声克隆** + 引擎能力声明/显式引擎不回退，素材不出本机 |
| BGM | HotClip AI 配乐走云（Atlas，~按张/首计费）；NarratoAI Sonilo 云配乐/音效（README/release，一手） | **ACE-Step 本地生成** + 曲库自动铺底，零云成本零素材外传 |
| 源硬字幕处理 | NarratoAI 字幕遮罩/moviepy 路线（旧调研已证伪其速度）；推剧助手「视频去字幕」为云工具箱（应用宝，一手） | ffmpeg **delogo 本地擦除** + 台词保护区两级吸附 |
| 诚实失败工程 | JJYB v3.4.2 曾「素材不足按 95% 出片」，v3.4.5 才改明确拒绝（release notes，一手）；HotClip「宁可不做不可做错」同哲学 | DramaClip 三态读数/宁可失败不出次品/真机门禁**先行且成体系**；竞品正在收敛过来 |
| 响度/混音 | HotClip EBU R128 -14LUFS + BGM 闪避（README，一手） | 同形（sidechain+limiter+-14LUFS），**行业共识非差距**，数值不必动 |
| 硬编回退 | HotClip NVENC/QSV/VT 探测+透明回退 x264；JJYB 真机 FFmpeg 回归（一手） | 与 DramaClip 三厂商真试编+运行时回退同构，已落地，无需跟进 |

---

## 6. 撞锁不追（明确记录，防止后续误立项）

| 竞品能力 | 来源 | 撞哪条锁 |
|---|---|---|
| 剪映草稿导出 | HotClip/NarratoAI/JJYB/jianying-editor-skill/jianying-headless/pyJianYingDraft（一手见 §1/§3） | 「永不导出草稿，只交成品」 |
| EDL/时间线工程交接（DaVinci/PR 重链精修） | HotClip README（一手） | 同上精神：只交成品 |
| 去重/抗比对：变形度评分、多版反指纹、一键去重 | HotClip README；推剧助手应用宝描述；智剪 App（一手/线索） | 「不做消重/抗比对卖点」 |
| 关键帧对齐流复制切片提速 | HotClip README（一手） | 切点精度质量锁（旧调研 C 档已拒 `-c copy` 切片；DramaClip 重编码两阶段勿倒退） |
| 多语翻译/阿拉伯文 shaping/印尼语等 | VideoLingo、MPT v1.3.10（一手） | 「不做多语翻译」 |
| yt-dlp 下载/代理 | VideoLingo v3.0.4（一手） | 「不做视频下载器」 |
| 弹幕文件进爆点证据 | HotClip README（一手） | 非锁但素材不适用：短剧源片无弹幕，不追 |
| 云 AI 封面/云配乐 | HotClip Atlas 双档（一手） | 素材不出本机 + 成本；本地封面叠字/ACE-Step 已是上位替代 |
| HDR→SDR/智能画面校正/去录屏UI | HotClip README（一手） | 非锁但低价值：短剧源为专业制作 SDR 竖屏，无录屏 UI；不追 |

---

## 7. 优先级建议（收益/成本 × 质量线）

1. **批次一（小成本、合规与发布摩擦）**：G3 隐式标识+平台指引（走业主裁决）、G4 字幕安全区、G2 平台发布包。~~G10 分发留证~~（撞 2026-09-10 授权存证否决裁决，已剔出）。
2. **批次二（自进化闭环）**：G1 反馈对账+A/B 实验中心——DramaClip 的 K 方案互异结构是全行业最适合做本地 A/B 的，HotClip 已验证形态。
3. **批次三（听感与产能）**：G5 气口跳剪（三重门）、G12 停顿标签/逐字字幕、G8 CLI/MCP、G9 黄金集。
4. **观察项**：G6/G7/G11/G13/G14，按实测瓶颈与产品决策再启。
5. 对照自查（零立项）：DramaClip 曲库铺底链路确认无 `-shortest` 类截断路径（JJYB v3.4.4 反面教材）。

## 8. 市场信号（一句话级）
- 腾讯智影退场（2025-06 停服删数据）：云剪辑一站式路线收缩【二手，见 §2】。
- 度加转型创作 Agent（对话式+定时托管+数据中心）、剪映出现第三方 Agent skill 生态、HotClip 本地 MCP/Agent Skill、VideoLingo 本地 HTTP API：**「Agent 驱动剪辑」是 2026-09 后跨阵营共同趋势**，DramaClip 的 G8 不是锦上添花而是赛道门票。
- 红果/抖音解说漫剧新政带火「解说剧一键成片」**制作端**工具（巨日禄等，二手未核实），与推广端相邻；CPS 专用 App（推剧助手/剧说/剧小通）已验证订阅付费，但质量纵深浅——DramaClip 的窗口仍在。