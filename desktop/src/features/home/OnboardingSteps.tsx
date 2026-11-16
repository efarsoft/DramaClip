/** 首启三步（规格 §4.2 剧库空态）：装 ASR 模型 → 配文案 LLM → 新增项目。
 *
 * 每步带完成状态与直达入口——就绪判定与右栏「环境就绪度」同一数据源（models.list
 * 的 ASR 档 + llmBaseUrl），两边不各算一份。第三步在空态里恒为当前步：
 * 建了剧整块引导就让位给工作台，不存在「三步全勾还停在空态」的形态。
 *
 * ASR 步双入口（业主拍板 2026-11-16 推荐档=Paraformer-large）：
 *   推荐档一键串装（运行环境 + Paraformer-large/fsmn-vad/campplus-sv 三包），
 *   快速档 Whisper Small 单包免环境——两个都是真一键，取舍亮给用户不代选。
 * 清单缺席时回退「去下载」跳转。
 */
import { CheckCircleFilled, DownloadOutlined } from '@ant-design/icons';
import { App as AntdApp, Button, Progress } from 'antd';
import { useEffect, useState, type ReactElement } from 'react';
import { useNavigate } from 'react-router-dom';
import type { ModelInfo } from '@dramaclip/protocol';
import { localRuntimeApi } from '../../services/client';
import { layout, tokens } from '../../styles/theme';
import { useUiStore } from '../../stores/ui';
import { downloadingLabel } from '../engines/downloadLabel';
import { errorText } from '../engines/errorText';
import { nextChainCandidate, pickQuickModel } from './onboardingModel';
import { useOnboardingChain, type ChainPhase } from './useOnboardingChain';

type StepAction =
  | { readonly kind: 'navigate'; readonly label: string; readonly path: string }
  | { readonly kind: 'asr-actions' };

interface Step {
  readonly done: boolean;
  readonly label: string;
  readonly hint: string;
  readonly action: StepAction | null;
}

export function OnboardingSteps({
  models,
  llmBaseUrl,
  onModelsChanged,
}: {
  models: ModelInfo[] | null;
  llmBaseUrl: string;
  /** 一键装齐完成（或取消销账）后重拉 models.list——步骤勾选与环境就绪度同步翻转。 */
  onModelsChanged: () => void;
}): ReactElement {
  const navigate = useNavigate();
  // 判据=任一 ASR 模型已装：装了推荐档或快速档任一都算这步完成。
  const asrInstalled = (models ?? []).some((m) => m.kind === 'asr' && m.status === 'installed');
  const llmReady = llmBaseUrl !== '';
  const chainCandidate = asrInstalled ? null : nextChainCandidate(models);
  const quickCandidate = asrInstalled ? null : pickQuickModel(models);
  // E-2：本地识别跑在 tts-venv 的 worker 里——模型之前先有环境（funasr 组）；
  // 探测未归零（null）时不进步骤表，避免闪一步假答案。Whisper 用户可跳过（免装）。
  const [runtimeReady, setRuntimeReady] = useState<boolean | null>(null);
  useEffect(() => {
    // 测试态 bridge 未装配时 rpc 是同步抛错——effect 里必须连同步异常一起兜
    try {
      localRuntimeApi
        .status()
        .then((s) => {
          setRuntimeReady(Boolean(s.groups.funasr));
        })
        .catch(() => {
          setRuntimeReady(false);
        });
    } catch {
      setRuntimeReady(false);
    }
  }, []);
  const steps: readonly Step[] = [
    // 只在未就绪时出现：这一步的存在意义就是催安装，装完留着只是噪音。
    // 推荐档链会顺手把环境装上——这步对选推荐档的用户自然消失，不再各走各的。
    ...(runtimeReady === false
      ? [
          {
            done: false,
            label: '安装本地运行环境',
            hint: '本地识别/配音共用的 torch 运行时（约 2~6GB 按需下载）；推荐档一键装齐会自动带上',
            action: { kind: 'navigate', label: '去安装', path: '/engines/asr' } satisfies StepAction,
          },
        ]
      : []),
    {
      done: asrInstalled,
      label: '装一个 ASR 模型',
      hint: '推荐 Paraformer-large：中文最准、热词直灌、带说话人分离；赶时间选快速档（免装运行环境）',
      action: asrInstalled
        ? null
        : chainCandidate !== null || quickCandidate !== null
          ? { kind: 'asr-actions' }
          : { kind: 'navigate', label: '去下载', path: '/engines/asr' },
    },
    {
      done: llmReady,
      label: '配文案 LLM',
      hint: '任意 OpenAI 兼容端点；跳过也能先用纯原片剪辑',
      action: llmReady ? null : { kind: 'navigate', label: '去配置', path: '/engines/llm' },
    },
    {
      done: false,
      label: '新增项目',
      hint: '选素材所在文件夹即可，文件夹名就是剧名——下方按钮就是这一步',
      action: null,
    },
  ];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceXs, width: '100%', maxWidth: 440 }}>
      {steps.map((step, index) => (
        <StepRow
          key={step.label}
          step={step}
          index={index + 1}
          current={index === steps.length - 1}
          onGo={(path) => void navigate(path)}
          chainCandidate={step.action?.kind === 'asr-actions' ? chainCandidate : null}
          quickCandidate={step.action?.kind === 'asr-actions' ? quickCandidate : null}
          onModelsChanged={onModelsChanged}
        />
      ))}
    </div>
  );
}

function StepRow({
  step,
  index,
  current,
  onGo,
  chainCandidate,
  quickCandidate,
  onModelsChanged,
}: {
  step: Step;
  index: number;
  current: boolean;
  onGo: (path: string) => void;
  chainCandidate: ModelInfo | null;
  quickCandidate: ModelInfo | null;
  onModelsChanged: () => void;
}): ReactElement {
  // 跳转按钮先算好再进 JSX：闭包里窄化会丢，解构出 path 后回调直接用它
  const action = step.action;
  const navigateButton =
    action?.kind === 'navigate' ? (
      <Button
        size="small"
        style={{ flexShrink: 0, marginTop: layout.iconNudge }}
        onClick={() => {
          const { path } = action;
          onGo(path);
        }}
      >
        {action.label}
      </Button>
    ) : null;
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: tokens.spaceSm,
        padding: `${tokens.spaceXs} ${tokens.spaceSm}`,
        borderRadius: tokens.radiusControl,
        background: current && !step.done ? tokens.accentSoft : undefined,
      }}
    >
      {step.done ? (
        <CheckCircleFilled style={{ color: tokens.colorSuccess, fontSize: tokens.glyph.icon, marginTop: layout.iconNudge }} />
      ) : (
        <StepDot index={index} current={current} />
      )}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize: tokens.text.body.size,
            lineHeight: tokens.text.body.leading,
            fontWeight: 600,
            color: step.done ? tokens.textTertiary : tokens.textPrimary,
            textDecoration: step.done ? 'line-through' : undefined,
          }}
        >
          {step.label}
        </div>
        <div style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textTertiary }}>
          {step.hint}
        </div>
        {action?.kind === 'asr-actions' && (
          <AsrStepActions chainCandidate={chainCandidate} quickCandidate={quickCandidate} onChanged={onModelsChanged} />
        )}
      </div>
      {navigateButton}
    </div>
  );
}

/** ASR 步双入口：推荐档串装（环境+三包）/ 快速档单包，共用一条链状态机——
 *  任一进行中两入口同时锁（服务端环境 job 与下载串行闸都不允许并行）。 */
function AsrStepActions({
  chainCandidate,
  quickCandidate,
  onChanged,
}: {
  chainCandidate: ModelInfo | null;
  quickCandidate: ModelInfo | null;
  onChanged: () => void;
}): ReactElement | null {
  const { message } = AntdApp.useApp();
  const { phase, startRecommended, startQuick, cancel } = useOnboardingChain(onChanged);
  const running = phase.kind === 'runtime' || phase.kind === 'download';

  const launch = (run: () => void): void => {
    try {
      run();
    } catch (error: unknown) {
      // 串行闸等拒绝原话上屏（服务端_job 层还有终态账，这里只是发起面）
      message.error(errorText(error, '一键装齐发起失败'));
    }
  };

  if (phase.kind === 'runtime') {
    return (
      <ActionBox>
        <span style={{ color: tokens.textSecondary }}>
          {phase.stage !== '' ? phase.stage : '安装本地运行环境'} · {String(Math.round(phase.progress))}%
        </span>
        <Progress percent={Math.round(phase.progress)} size="small" showInfo={false} />
        <Button size="small" onClick={cancel}>
          取 消
        </Button>
      </ActionBox>
    );
  }
  if (phase.kind === 'download') {
    return <DownloadPhase phase={phase} onCancel={cancel} />;
  }
  if (phase.kind === 'error') {
    return (
      <ActionBox>
        <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.errorText }}>
          {phase.problem}
        </span>
        <span>
          <Button
            size="small"
            danger
            icon={<DownloadOutlined />}
            onClick={() => {
              launch(startRecommended);
            }}
          >
            重试
          </Button>
        </span>
      </ActionBox>
    );
  }
  if (phase.kind === 'done') {
    // 重拉落地前的短暂窗口：动作区让空，步骤打勾由 models.list 翻转后接管
    return null;
  }
  return (
    <ActionBox>
      {chainCandidate !== null && (
        <Button
          size="small"
          type="primary"
          disabled={running}
          icon={<DownloadOutlined />}
          onClick={() => {
            launch(startRecommended);
          }}
        >
          一键装齐推荐档（约 910MB + 运行环境）
        </Button>
      )}
      {quickCandidate !== null && (
        <Button
          size="small"
          disabled={running}
          onClick={() => {
            launch(() => {
              startQuick(quickCandidate.model_id, quickCandidate.name);
            });
          }}
        >
          快速档：Whisper Small（约 480MB，免装运行环境）
        </Button>
      )}
    </ActionBox>
  );
}

/** 包下载阶段的行内渲染：进度读全局订阅（models.download_progress），取消走链级。 */
function DownloadPhase({
  phase,
  onCancel,
}: {
  phase: ChainPhase & { kind: 'download' };
  onCancel: () => void;
}): ReactElement {
  const download = useUiStore((state) => state.modelDownloads[phase.modelId]);
  const progressText =
    download === undefined
      ? '准备下载…'
      : download.status === 'done'
        ? '下载完成，核验中…'
        : downloadingLabel(download);
  return (
    <ActionBox>
      <span style={{ color: tokens.textSecondary }}>
        {`（${String(phase.index)}/${String(phase.total)}）${phase.modelName} · ${progressText}`}
      </span>
      <Button size="small" onClick={onCancel}>
        取 消
      </Button>
    </ActionBox>
  );
}

function ActionBox({ children }: { children: React.ReactNode }): ReactElement {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'flex-start',
        gap: tokens.spaceXs,
        marginTop: layout.stack.tight,
      }}
    >
      {children}
    </div>
  );
}

/** 未完成步的序号圆点（当前步高亮主色）。 */
function StepDot({ index, current }: { index: number; current: boolean }): ReactElement {
  return (
    <span
      style={{
        width: 18,
        height: 18,
        borderRadius: tokens.radiusDot,
        border: `1px solid ${current ? tokens.colorPrimary : tokens.border}`,
        color: current ? tokens.colorPrimary : tokens.textTertiary,
        fontSize: tokens.text.badge.size,
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
        marginTop: layout.iconNudge,
      }}
    >
      {String(index)}
    </span>
  );
}
