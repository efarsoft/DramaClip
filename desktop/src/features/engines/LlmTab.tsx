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
