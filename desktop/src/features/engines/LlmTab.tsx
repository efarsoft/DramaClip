/** LLM 引擎：OpenAI 兼容端点多实例（云端服务或本地 Ollama/LM Studio 同协议），单启用。 */
import { PageSection } from '../../components/layout/PageKit';
import { tokens } from '../../styles/theme';
import { CloudConfigSection } from './CloudConfigSection';

/** 文案 LLM tab：端点配置列表（启用中的配置镜像至 llm.* 设置，即时生效）。 */
export function LlmTab({ onChanged }: { onChanged: () => void }): React.ReactElement {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <PageSection title="云端 / 本地端点（OpenAI 兼容）">
        <div style={{ fontSize: tokens.fontCaption, color: tokens.textTertiary, marginBottom: 14 }}>
          可添加多个端点按需启用：云端填 DashScope 等兼容服务；本地 Ollama 填 http://127.0.0.1:11434/v1、
          LM Studio 填其服务地址。未配置时剧情与文案生成自动降级为关键词模式。
        </div>
        <CloudConfigSection domain="llm" onChanged={onChanged} />
      </PageSection>
      <PageSection title="本地大模型">
        <div style={{ fontSize: tokens.fontCaption, color: tokens.textTertiary }}>
          本地 LLM 引擎（内置推理）规划在后续版本；当前可经 Ollama / LM Studio 的 OpenAI
          兼容端点接入本地模型——添加一条配置填本地服务地址即可。
        </div>
      </PageSection>
    </div>
  );
}
