/** 首启三步（规格 §4.2 剧库空态）：装 ASR 模型 → 配文案 LLM → 新增项目。
 *
 * 每步带完成状态与直达入口——就绪判定与右栏「环境就绪度」同一数据源（models.list
 * 的 ASR 档 + llmBaseUrl），两边不各算一份。第三步在空态里恒为当前步：
 * 建了剧整块引导就让位给工作台，不存在「三步全勾还停在空态」的形态。
 *
 * ASR 步的动作是**一键下载推荐模型**（装测 2026-11-16 业主反馈：跳引擎中心找模型
 * 路径散）：点一下走 models.download 默认源序（国内源优先，失败自动换源），进度就地
 * 显示、可取消，完成自动打勾。清单缺席/无候选时回退「去下载」跳转。
 */
import { CheckCircleFilled } from '@ant-design/icons';
import { App as AntdApp, Button } from 'antd';
import { useEffect, useRef, useState, type ReactElement } from 'react';
import { useNavigate } from 'react-router-dom';
import type { ModelInfo } from '@dramaclip/protocol';
import { localRuntimeApi, modelsApi } from '../../services/client';
import { layout, tokens } from '../../styles/theme';
import { useUiStore } from '../../stores/ui';
import { CancelDownload, RetryDownload } from '../engines/ModelDownloadPopover';
import { errorText } from '../engines/errorText';
import { pickRecommendedModel } from './onboardingModel';

type StepAction =
  | { readonly kind: 'navigate'; readonly label: string; readonly path: string }
  | { readonly kind: 'download-recommended' };

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
  /** 推荐模型下载完成（或取消销账）后重拉 models.list——步骤勾选与环境就绪度同步翻转。 */
  onModelsChanged: () => void;
}): ReactElement {
  const navigate = useNavigate();
  // 判据=任一 ASR 模型已装（不再是 required 档）：required 只有 base，照提示装了
  // 推荐的 Small 反而不打勾——判据与推荐错位（2026-11-16 一键引导批修正）。
  const asrInstalled = (models ?? []).some((m) => m.kind === 'asr' && m.status === 'installed');
  const llmReady = llmBaseUrl !== '';
  const recommended = pickRecommendedModel(models);
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
    // 只在未就绪时出现：这一步的存在意义就是催安装，装完留着只是噪音（模型步不
    // 同——「已装 Whisper」是对选择史的如实勾选，保留）。
    ...(runtimeReady === false
      ? [
          {
            done: false,
            label: '安装本地运行环境',
            hint: '本地识别/配音共用的 torch 运行时（约 2~6GB 按需下载）；Whisper 免装可跳过',
            action: { kind: 'navigate', label: '去安装', path: '/engines/asr' } satisfies StepAction,
          },
        ]
      : []),
    {
      done: asrInstalled,
      label: '装一个 ASR 模型',
      hint: '推荐 Whisper Small（约 480MB，免装运行环境），一键下载完即可分析',
      action: asrInstalled
        ? null
        : recommended !== null
          ? { kind: 'download-recommended' }
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
          recommended={step.action?.kind === 'download-recommended' ? recommended : null}
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
  recommended,
  onModelsChanged,
}: {
  step: Step;
  index: number;
  current: boolean;
  onGo: (path: string) => void;
  recommended: ModelInfo | null;
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
        {/* 失败原因必须是行内可见文本，不是 toast——与资产行同一原话纪律 */}
        {step.action?.kind === 'download-recommended' && recommended !== null && (
          <OneClickDownload model={recommended} onChanged={onModelsChanged} />
        )}
      </div>
      {navigateButton}
    </div>
  );
}

/** 一键下载推荐模型：默认源序（国内源优先，失败自动换源）零选择直下；进度/取消/重试
 *  复用引擎中心资产行的同一套件——两处语义不各写一份。 */
function OneClickDownload({ model, onChanged }: { model: ModelInfo; onChanged: () => void }): ReactElement | null {
  const { message } = AntdApp.useApp();
  const download = useUiStore((state) => state.modelDownloads[model.model_id]);
  const [busy, setBusy] = useState(false);
  // done 只上报一次：重拉落地前 status==='done' 会随重渲染重复读到
  const reported = useRef(false);
  useEffect(() => {
    if (download?.status === 'done' && !reported.current) {
      reported.current = true;
      onChanged();
    }
  }, [download?.status, onChanged]);

  const launch = (): void => {
    setBusy(true);
    modelsApi
      .download(model.model_id)
      .then(() => undefined)
      .catch((error: unknown) => {
        // 串行闸与磁盘预算的拒绝原话必须上屏
        message.error(errorText(error, '下载任务创建失败'));
      })
      .finally(() => {
        setBusy(false);
      });
  };
  if (download?.status === 'downloading') {
    return <CancelDownload model={model} download={download} onChanged={onChanged} />;
  }
  if (download?.status === 'failed') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceXs, marginTop: layout.stack.tight }}>
        <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.errorText }}>
          {download.message}
        </span>
        <span>
          <RetryDownload model={model} onChanged={onChanged} />
        </span>
      </div>
    );
  }
  if (download?.status === 'done') {
    // 重拉落地前的短暂窗口：动作区让空，步骤打勾由 models.list 翻转后接管——
    // 这里若仍渲染按钮，等于邀请对着已装好的模型再点一次下载。
    return null;
  }
  return (
    <Button size="small" loading={busy} style={{ marginTop: layout.stack.tight }} onClick={launch}>
      一键下载推荐模型
    </Button>
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
