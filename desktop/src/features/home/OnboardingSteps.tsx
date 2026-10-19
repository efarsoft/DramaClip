/** 首启三步（规格 §4.2 剧库空态）：装 ASR 模型 → 配文案 LLM → 新增项目。
 *
 * 每步带完成状态与直达入口——就绪判定与右栏「环境就绪度」同一数据源（models.list
 * 的 required ASR 档 + llmBaseUrl），两边不各算一份。第三步在空态里恒为当前步：
 * 建了剧整块引导就让位给工作台，不存在「三步全勾还停在空态」的形态。
 */
import { CheckCircleFilled } from '@ant-design/icons';
import { Button } from 'antd';
import { useNavigate } from 'react-router-dom';
import { useEffect, useState, type ReactElement } from 'react';
import type { ModelInfo } from '@dramaclip/protocol';
import { layout, tokens } from '../../styles/theme';
import { localRuntimeApi } from '../../services/client';

interface Step {
  readonly done: boolean;
  readonly label: string;
  readonly hint: string;
  readonly action: { readonly label: string; readonly path: string } | null;
}

export function OnboardingSteps({
  models,
  llmBaseUrl,
}: {
  models: ModelInfo[] | null;
  llmBaseUrl: string;
}): ReactElement {
  const navigate = useNavigate();
  const asrInstalled = (models ?? []).some((m) => m.required && m.status === 'installed');
  const llmReady = llmBaseUrl !== '';
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
            action: { label: '去安装', path: '/engines/asr' } satisfies Step['action'],
          },
        ]
      : []),
    {
      done: asrInstalled,
      label: '装一个 ASR 模型',
      hint: '推荐 Whisper Small（约 480MB），装完才能分析',
      action: asrInstalled ? null : { label: '去下载', path: '/engines/asr' },
    },
    {
      done: llmReady,
      label: '配文案 LLM',
      hint: '任意 OpenAI 兼容端点；跳过也能先用纯原片剪辑',
      action: llmReady ? null : { label: '去配置', path: '/engines/llm' },
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
        <StepRow key={step.label} step={step} index={index + 1} current={index === steps.length - 1} onGo={(path) => void navigate(path)} />
      ))}
    </div>
  );
}

function StepRow({
  step,
  index,
  current,
  onGo,
}: {
  step: Step;
  index: number;
  current: boolean;
  onGo: (path: string) => void;
}): ReactElement {
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
      </div>
      {step.action !== null && (
        <Button
          size="small"
          style={{ flexShrink: 0, marginTop: layout.iconNudge }}
          onClick={() => {
            onGo(step.action?.path ?? '');
          }}
        >
          {step.action.label}
        </Button>
      )}
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
