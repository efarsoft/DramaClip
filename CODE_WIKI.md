# DramaClip 项目代码文档

## 一、项目概述

DramaClip 是一款基于人工智能技术的短剧自动高光剪辑工具，能够智能分析视频内容、自动检测高光片段，并生成精彩的短视频作品。该项目采用 Electron 作为桌面应用框架，前端使用 React + TypeScript 构建用户界面，后端采用 Python 实现核心业务逻辑，通过 JSON-RPC 协议进行进程间通信。

项目的主要功能包括：多维度高光检测（音频爆点、台词情绪、画面特征、镜头节奏）、AI 驱动的视觉分析、语音识别与情绪分析、支持多种配音引擎的 AI 解说功能，以及智能剪辑流程（场景分割、高光筛选、片段拼接、字幕合成）。此外，项目还支持多集剧集的批量处理能力。

技术栈方面，前端采用 Electron 33.x 作为跨平台桌面框架，配合 React 19.x 构建 UI，使用 TypeScript 5.7 保证类型安全，通过 Vite 6.x 进行构建，Ant Design 5.x 提供组件库，Zustand 5.x 管理前端状态。后端则基于 Python 3.10+，使用 PyInstaller 打包为可执行文件，通过 JSON-RPC 2.0 协议实现进程间通信。AI/ML 能力方面集成了 OpenAI API 进行视觉分析，librosa 用于音频分析，OpenCV 和 PySceneDetect 处理视频和场景分割。

## 二、项目架构

### 2.1 整体架构设计

DramaClip 采用经典的主从架构设计，Electron 主进程负责管理应用生命周期、窗口创建和后端进程管理，渲染进程（React 应用）负责用户界面交互，Python 后端进程处理所有计算密集型任务。这种架构的优势在于将前端界面与核心算法解耦，前端专注于用户体验和交互，后端专注于高光检测、AI 分析和视频处理。

进程间通信采用 JSON-RPC 2.0 协议，通过标准输入输出流进行双向通信。主进程作为 JSON-RPC 客户端，向后端发送请求并接收响应；同时后端可以通过通知机制主动向主进程推送进度更新、日志和错误信息。这种设计既保证了通信的标准化，又实现了实时反馈能力。

项目根目录结构如下所示，核心代码分别位于 main/（Electron 主进程）、src/（React 前端）和 app/（Python 后端）三个主要目录中。

### 2.2 前端架构

前端部分采用 Electron 的主从进程模型，主进程（main/）负责系统级操作和后端管理，渲染进程（src/）负责用户界面。

主进程包含以下核心模块：app.ts 是应用入口点，负责创建窗口、初始化后端和注册 IPC 处理器；preload.ts 通过 contextBridge 在渲染进程和主进程之间建立安全的通信桥接，暴露精心设计的 API 接口；backend/ 目录包含 BackendLauncher（后端启动器）和 BackendManager（后端管理器），负责后端进程的生命周期管理，包括启动、监控、重启等；ipc/ 目录包含 bridge.ts（IPC 桥接器）和 channels.ts（通道常量定义），统一管理所有 IPC 通信；window/manager.ts 负责窗口的创建、销毁和状态管理。

渲染进程（src/）采用 React + TypeScript 构建，结构清晰分层：pages/ 目录包含 HomePage.tsx（首页）、WorkspacePage.tsx（工作区页面）、SettingsPage.tsx（设置页面），以及 workspace/ 子目录下的功能面板组件（AnalyzePanel、EditPanel、ExportPanel、ImportPanel、RecommendPanel）；components/ 目录包含可复用的 UI 组件，如布局组件（AppLayout、Sidebar、StatusBar）、通用组件（VideoPlayer）、图表组件（EmotionCurve）和项目组件（ProjectCard、ProjectList）；stores/ 目录使用 Zustand 管理状态，包括项目状态（projectStore）、任务队列状态（taskQueueStore）、UI 状态（uiStore）和导出状态（exportStore）；services/ipc.ts 是 IPC 客户端封装，提供与后端通信的便捷接口；types/ipc.ts 定义了 TypeScript 类型，确保前后端通信的类型安全。

### 2.3 后端架构

Python 后端采用分层架构设计，从上到下依次为 IPC 层、服务层和工具层。

IPC 层位于 app/ipc/ 目录，是后端与 Electron 主进程通信的入口。server.py 实现了 JSON-RPC 服务端，监听标准输入并将响应写入标准输出，支持请求处理、通知发送和错误响应；router.py 负责将 RPC 方法名路由到对应的处理函数，实现 namespace.method 的命名空间管理；protocol.py 定义了 JSON-RPC 2.0 协议的数据结构和序列化/反序列化逻辑；handlers.py 包含所有 RPC 方法的具体实现，是业务逻辑的调度中心。

服务层位于 app/services/ 目录，是项目的核心业务逻辑所在。根据功能可分为以下几个主要模块：

highlight/ 模块负责高光检测的核心算法，包括 scorer.py（打分器基类）、audio_scorer.py（音频爆点打分）、emotion_scorer.py（情绪打分）、visual_scorer.py（画面打分）、rhythm_scorer.py（节奏打分）、scene_detect.py（场景检测）、selector.py（高光选择器）和 sorter.py（片段排序器）。这个模块通过多维度分析计算每个视频片段的综合得分，然后智能筛选出最具价值的高光内容。

analyze/ 模块负责视频内容的智能分析，包含 manager.py（分析管理器）、asr_service.py（语音识别服务）和 emotion_service.py（情绪分析服务）。分析流程会调用这些服务提取视频的音频转文字、情绪变化曲线等信息，为高光检测提供数据支撑。

llm/ 模块封装了大语言模型调用能力，包含 base.py（基类）、manager.py（管理器）、unified_service.py（统一服务）、openai_compatible_provider.py（OpenAI 兼容提供商）等。这个模块提供了统一的 LLM 调用接口，支持多种后端（OpenAI、Claude 等），并内置了配置验证和错误处理机制。

narration/ 模块负责 AI 解说生成，包含 pipeline.py（解说生成流水线）。该模块可以生成解说文案并通过 TTS 引擎合成语音，支持保留原声叠加解说或完全替换原声两种模式。

project/ 模块管理项目数据持久化，包含 manager.py（管理器）、database.py（数据库操作）、manager_sqlite.py（SQLite 实现）和 manager_json.py（JSON 实现）。支持项目的创建、打开、删除和视频导入等功能。

direct_cut/ 模块实现直接剪辑功能，包含 pipeline.py（剪辑流水线）。该模块将场景检测、高光打分、高光选择、片段排序和视频拼接等步骤串联成完整流程。

prompts/ 模块管理提示词模板，包含 registry.py（模板注册表）、manager.py（管理器）和各类型的提示词文件（documentary/、short_drama_editing/、short_drama_narration/）。提示词模板使用 Jinja2 语法，支持动态参数替换。

配置层位于 app/config/ 目录，config.py 是配置加载入口，支持 TOML 格式的配置文件；defaults.py 定义了默认配置值和配置合并逻辑；其他配置文件分别管理音频（audio_config.py）、FFmpeg（ffmpeg_config.py）和重试策略（retry_config.py）。

工具层位于 app/utils/ 目录，提供了各种辅助功能：ffmpeg_utils.py 封装 FFmpeg 命令调用；video_utils.py 和 video_processor.py 处理视频相关操作；srt_utils.py 管理字幕文件；gemini_analyzer.py 和 qwenvl_analyzer.py 提供视觉分析能力；utils.py 包含通用工具函数。

## 三、关键模块详解

### 3.1 进程间通信机制

JSON-RPC 服务端是后端的核心入口，在 backend_main.py 中初始化并启动。服务端通过标准输入监听来自主进程的请求，每收到一个请求便解析、执行并返回响应。服务端还支持主动发送通知，用于向主进程推送进度更新和日志信息。

IpcServer 类的核心方法包括：handle() 方法处理单个 JSON-RPC 请求，首先解析请求数据，然后通过 Router 解析方法名找到对应的处理函数，执行处理函数并捕获异常，最后返回成功或错误响应；send_notification() 方法用于发送通知到标准输出；send_progress() 方法封装进度更新通知，包含任务ID、进度百分比、消息和详情等字段。

Router 类负责方法路由，它维护一个从方法名到处理函数的映射表。create_router() 函数在初始化时注册所有 RPC 方法，这些方法分布在不同的命名空间中：project 命名空间处理项目管理（list、create、open、delete、importVideos 等）；analyze 命名空间处理分析任务（start、getStatus、cancel）；clip 命名空间处理剪辑操作（recommend、execute、getProgress、preview、stop）；export 命名空间处理导出操作（start、getProgress）；settings 命名空间处理设置读写；system 命名空间提供系统级功能（getVersion、getFFmpegInfo、ping、shutdown）；model 命名空间管理 AI 模型（list、download、cancel、delete、status）。

handlers.py 中的处理函数是业务逻辑的核心入口。以 analyze_start() 为例，该函数接收项目ID和要分析的剧集ID列表，首先通过 ProjectManager 获取项目的视频列表，然后为每个视频创建分析任务，最后将任务提交到线程池异步执行。分析任务在后台线程中运行，通过 progress_callback 将进度信息发送给 IPC 服务器，最终到达渲染进程更新界面。

### 3.2 高光检测系统

高光检测是 DramaClip 的核心技术能力，采用多维度打分机制综合评估每个视频片段的价值。

打分器基类定义了统一的打分接口，每个具体的打分器需要实现 _score_single() 方法，返回 0 到 1 之间的分数。AudioScorer 使用 librosa 库分析音频特征，包括梅尔频谱、响度和频谱质心等指标，检测音频爆点和高潮部分。EmotionScorer 分析台词的情绪倾向，通过 LLM 理解对白的情感色彩，给出情绪高涨程度的评分。VisualScorer 分析画面特征，包括场景复杂度、运动强度和画面质量等因素。RhythmScorer 评估镜头节奏的紧凑程度，通过分析镜头时长分布和切换频率来判断节奏感。

HighlightSegment 是高光片段的核心数据结构，包含以下字段：video_path 表示源视频路径；start_time 和 end_time 表示片段时间范围；score 表示综合得分；audio_score、emotion_score、visual_score、rhythm_score 分别表示各维度得分；subtitle_text 可选地包含字幕文本；reason 表示入选理由；segment_id 是前端传递的片段标识。HighlightSegment 提供了 duration 属性计算片段时长，以及 to_dict() 方法转换为可序列化格式。

HighlightSelector 负责从所有候选片段中筛选最终的高光内容。其选择策略包括：过滤时长不足的片段（默认最小 2 秒）；按综合得分排序并选取 Top N%（默认 30%）；按集数分组并平衡每集的片段数量（默认每集最多 5 个）；智能截断以满足目标总时长；为每个入选片段生成入选理由。

### 3.3 剪辑流水线

DirectCutPipeline 实现了原片直剪的完整流程，包含以下步骤：首先通过场景检测将视频分割为多个场景；然后对每个场景进行多维度打分；接着根据目标时长筛选高光片段；之后对片段进行智能排序（可按时间顺序或打乱重组）；最后使用 FFmpeg 将选定的片段拼接为完整视频。

NarrationPipeline 实现了 AI 解说功能，支持两种混音模式：overlay 模式保留原声并叠加解说音频；replace 模式完全替换原声为解说音频。流水线的步骤包括：解析剧情并提取关键信息；生成解说文案（调用 LLM）；使用 TTS 引擎合成解说音频；剪辑原片素材；将解说音频与原片音画合成。

clip_recommend() 函数根据项目视频数量智能推荐剪辑方案。对于多集视频，推荐「一键三连」模式同时生成原片直剪、混合解说和全解说三种版本；对于单集视频，推荐原片直剪或全解说模式。这种智能推荐简化了用户的决策过程。

### 3.4 前端状态管理

Zustand 是 React 应用的状态管理方案，相比 Redux 更轻量且使用更简便。项目定义了多个 Store 来管理不同领域的状态。

ProjectStore 管理项目相关状态，包括当前打开的项目、项目列表、视频列表等。状态更新通过暴露的方法进行，如 createProject()、openProject()、deleteProject()、importVideos() 等。这种集中管理的方式确保了状态变更的可追踪性和可预测性。

TaskQueueStore 管理异步任务的状态，包括分析任务、剪辑任务和导出任务。每个任务记录其 ID、状态（pending、running、completed、failed）、进度百分比和可选的结果数据。Store 提供了查询任务状态和取消任务的方法。

UIStore 管理界面相关状态，如当前选中的面板、侧边栏折叠状态、模态框开关等。这些状态变化频繁但不需要持久化，适合放在前端状态中管理。

ExportStore 管理导出配置和导出任务状态，包括输出格式、分辨率、帧率、码率等参数。

## 四、依赖关系

### 4.1 前端依赖

前端项目的依赖在 package.json 中定义。核心依赖包括：react 和 react-dom（React 框架）；react-router-dom（路由管理）；antd 和 @ant-design/icons（Ant Design 组件库）；zustand（状态管理）；recharts（图表可视化）；dayjs（日期处理）；uuid（唯一ID生成）。开发依赖包括：typescript（类型系统）；vite 及其插件（构建工具）；electron 和 electron-builder（桌面应用框架和打包工具）；eslint 和 prettier（代码检查和格式化）；vitest（单元测试）；@testing-library/react（React 组件测试）。

### 4.2 后端依赖

后端项目的依赖在 requirements.txt 中定义。主要依赖包括：loguru（日志记录）；toml（配置文件解析）；librosa（音频分析）；opencv-python（图像处理）；numpy（数值计算）；pydantic（数据验证）；jieba（中文分词）；httpx（HTTP 客户端）；Pillow（图像处理）。

开发依赖在 requirements-dev.txt 中定义，包括：pytest（单元测试）；black（代码格式化）；isort（导入排序）；mypy（类型检查）。

### 4.3 进程间数据流

前端与后端之间的通信遵循标准的三层结构。首先，渲染进程通过 electronAPI（由 preload.ts 暴露）发起调用，例如 electronAPI.backend.call('project.list')；其次，主进程的 IPC 处理器接收调用，通过 Node.js 的子进程管理向后端进程发送 JSON-RPC 请求；最后，后端处理请求并将结果通过 JSON-RPC 响应返回，主进程再将结果转发给渲染进程。

进度更新的数据流向则相反：后端在处理过程中调用 _server.send_progress() 发送通知，通知通过 stdout 发送到主进程，主进程通过 IPC 通道转发给渲染进程，渲染进程监听 BACKEND_PROGRESS 通道并更新 UI。

## 五、项目运行方式

### 5.1 开发环境准备

运行 DramaClip 项目需要准备以下环境：Node.js 18 或更高版本；Python 3.10 或更高版本；FFmpeg 可执行文件（用于视频处理）。

首先克隆项目仓库到本地，然后依次安装前端和后端依赖。前端使用 npm install 安装 Node.js 依赖，后端使用 pip install -r requirements.txt 安装 Python 依赖。复制配置文件模板 config.example.toml 为 config.toml，并根据需要修改配置（主要是 LLM API 密钥）。

### 5.2 开发模式运行

开发模式下，前后端代码修改后可以热重载。运行 npm run dev 启动开发服务器，Vite 开发服务器运行在 localhost:5173，Electron 应用会自动打开并加载页面。后端代码在 app/ 目录中，修改后端代码后需要重启后端进程才能生效。

### 5.3 生产构建

生产构建分为三个步骤。首先构建前端，运行 npm run build:vite 生成 dist/ 目录中的前端资源。然后打包 Python 后端，运行 python scripts/build-backend.py，将 app/ 目录打包为 dist/backend/ 中的可执行文件。最后打包 Electron 应用，运行 npm run build，生成 Windows 安装包。

### 5.4 配置文件说明

config.toml 是项目的主要配置文件，包含多个配置段。[app] 段配置 LLM 相关参数，如 vision_openai_api_key、vision_openai_base_url、vision_openai_model_name 等。[highlight] 段配置高光检测权重，包括 audio_weight、emotion_weight、visual_weight 和 rhythm_weight。[scene_detect] 段配置场景检测参数。[output] 段配置输出相关参数。配置值可以通过前端设置页面修改，也可以直接编辑配置文件。

settings.json 存储用户界面相关的设置，位于用户主目录的 .dramaclip/ 文件夹下。其结构与 config.toml 类似但更面向用户，包括 openai_protocol、anthropic_protocol、tts、asr、vit、output 和 hardware 等配置段。

## 六、关键类与函数参考

### 6.1 后端核心类

IpcServer 类位于 app/ipc/server.py，是 JSON-RPC 服务端的实现。构造函数接收一个 Router 实例。register_handler() 方法用于注册命名空间和方法到路由。handle() 方法处理单个 JSON-RPC 请求并返回响应。send_notification() 和 send_progress() 方法用于向主进程发送通知。run() 方法启动服务主循环，监听 stdin 并处理请求。

Router 类位于 app/ipc/router.py，负责 RPC 方法的路由分发。register() 方法注册处理函数到指定的命名空间和方法。resolve() 方法根据完整方法名查找处理函数。list_methods() 方法返回所有已注册的方法列表。

HighlightSegment 类位于 app/services/highlight/selector.py，是高光片段的数据容器。作为 dataclass 实现，包含视频路径、时间范围、多维度得分等字段。duration 属性计算片段时长。to_dict() 方法转换为字典格式便于序列化。

HighlightSelector 类位于 app/services/highlight/selector.py，实现高光片段的智能筛选。构造函数接收筛选参数（top_ratio、min_segment_duration 等）。select() 方法执行完整的筛选流程。_truncate_to_duration() 方法实现智能截断逻辑。

DirectCutPipeline 类位于 app/services/direct_cut/pipeline.py，实现原片直剪的完整流水线。_detect_scenes() 方法检测视频场景。_score_scenes() 方法对场景打分。_select_highlights() 方法选择高光片段。_sort_segments() 方法对片段排序。_cut_and_concat() 方法执行视频剪辑和拼接。

NarrationPipeline 类位于 app/services/narration/pipeline.py，实现 AI 解说生成流水线。run() 方法接收视频路径列表、输出路径、目标时长和混音模式参数，执行完整的解说生成流程。

### 6.2 前端核心组件

electronAPI 对象由 preload.ts 暴露，是前端访问后端功能的唯一接口。dialog 对象提供文件对话框功能（openFile、openFolder、saveFile）。backend 对象提供后端调用功能（call）和事件监听（onProgress、onLog、onReady、onError）。window 对象提供窗口控制功能（minimize、maximize、close）。system 对象提供系统信息（getVersion、getFFmpegInfo、openPath）。fs 对象提供文件系统操作（scanDirectory）。

IPC_CHANNELS 常量定义在 preload.ts 中，列出了所有 IPC 通道名称，包括对话框通道（dialog:*）、后端调用通道（backend:*）、窗口控制通道（window:*）、系统通道（system:*）和文件系统通道（fs:*）。

ProjectStore（位于 src/stores/projectStore.ts）使用 Zustand 管理项目状态。状态包括 projects（项目列表）、currentProject（当前项目）、videos（视频列表）、loading（加载状态）和 error（错误信息）。暴露的方法包括 loadProjects()、createProject()、openProject()、deleteProject()、importVideos() 等。

## 七、扩展与定制

### 7.1 添加新的 RPC 方法

要添加新的 RPC 方法，需要在 handlers.py 中定义处理函数，然后在 router.py 的 create_router() 函数中注册该方法。处理函数的命名空间和方法名共同构成 RPC 方法名，例如命名空间为 "custom"、方法名为 "process" 则 RPC 方法为 "custom.process"。

处理函数应遵循标准签名，接受命名参数并返回可序列化的结果。函数内部可以调用服务层的方法完成业务逻辑，并通过异常处理返回适当的错误信息。建议使用 RPCError 类封装业务错误，其构造函数接收错误码和消息。

### 7.2 添加新的打分器

高光检测系统支持扩展新的打分维度。要添加新的打分器，可以创建继承自 Scorer 基类的新类，实现 _score_single() 方法。新打分器的分数将与其他维度的分数加权合并，形成片段的综合得分。

权重配置位于 config.toml 的 [highlight] 段，通过调整各维度的权重可以改变高光片段的评选标准。

### 7.3 集成新的 TTS 引擎

AI 解说功能支持集成不同的 TTS 引擎。要集成新的 TTS 引擎，需要在 narration/ 或独立的 TTS 模块中实现调用接口，然后在 NarrationPipeline 中添加对新引擎的支持。TTS 引擎通常需要支持文本输入和音频输出，以及语速、音调等参数调节。

## 八、测试策略

项目使用 Vitest 作为前端测试框架，测试文件位于 src/stores/__tests__/ 目录下。运行测试使用 npm test 命令，观察模式使用 npm run test:watch 命令。

后端使用 pytest 作为测试框架，测试文件通常位于 tests/ 目录或各模块的 test_*.py 文件中。测试可以通过 pytest 命令直接运行，并支持标记（markers）来区分慢速测试和集成测试。

代码格式化方面，Python 代码使用 Black（行长度 100）和 isort 进行格式化，TypeScript 代码使用 ESLint 和 Prettier 进行检查和格式化。运行格式化命令分别为 black app/、isort app/ 和 npm run format。
