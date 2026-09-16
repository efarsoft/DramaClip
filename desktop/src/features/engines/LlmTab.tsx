/** LLM 引擎：OpenAI 兼容端点多实例（云端服务或本地 Ollama/LM Studio 同协议），单启用。 */
import { PageSection } from '../../components/layout/PageKit';
import { tokens } from '../../styles/theme';
import { CloudConfigSection } from './CloudConfigSection';

export function LlmTab({ onChanged }: { onChanged: () => void }): React.ReactElement {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceMd }}>
      <PageSection title="云端 / 本地端点（OpenAI 兼容）">
        <div
          style={{
            fontSize: tokens.fontCaption,
            color: tokens.textTertiary,
            marginBottom: tokens.spaceMd,
          }}
        >
          可添加多个端点按需启用：云端填 DashScope 等兼容服务；本地 Ollama 填
          http://127.0.0.1:11434/v1、LM Studio 填其服务地址。
        </div>
        <UnconfiguredNotice />
        <CloudConfigSection domain="llm" onChanged={onChanged} />
      </PageSection>
      <PageSection title="本地大模型">
        <div style={{ fontSize: tokens.fontCaption, color: tokens.textTertiary }}>
          不内置本地推理。要跑本地模型，请经 Ollama / LM Studio 的 OpenAI
          兼容端点接入——添加一条配置、填本地服务地址即可。
        </div>
      </PageSection>
    </div>
  );
}

/** 未配置的真实后果：两层分开说——分析层关键词打分是允许级降级（必须可见），
 *  解说文案无兜底是禁止级（未配置即抛错）。颜色用 status/warning（DSS §3.2）。 */
function UnconfiguredNotice(): React.ReactElement {
  return (
    <div
      style={{
        fontSize: tokens.fontCaption,
        lineHeight: '19px',
        color: tokens.colorWarning,
        border: `1px solid ${tokens.colorWarning}66`,
        background: `${tokens.colorWarning}14`,
        borderRadius: tokens.radiusControl,
        padding: `${tokens.spaceSm}px ${tokens.spaceMd}px`,
        marginBottom: tokens.spaceMd,
      }}
    >
      未配置时：分析（转写、冲突打分）改用关键词打分，仍可跑完；但解说文案必须由编剧模型产出，
      没有兜底——七个解说模式的每条方案都会失败并在任务里说明原因。
      仅「纯原片剪辑」「字幕金句流」不依赖编剧模型。
    </div>
  );
}
