/** 转写档位三选（09-10 §4.3② 硬要求）：档位决定「批量分析」发哪条真 RPC——
 * 全部精转 = analysis.start；仅推荐集精转 = analysis.prescreen(then_analyze)。
 * 第三档「粗档」服务端没有低精度 ASR 实现：灰掉并写明原因，不摆没人听的开关。 */
import { Radio, Tooltip } from 'antd';
import { parseTier, TIER_OPTIONS, type TranscribeTier } from './analysisView';

export function TierPicker({
  tier,
  onTierChange,
  disabled,
}: {
  tier: TranscribeTier;
  onTierChange: (next: TranscribeTier) => void;
  disabled: boolean;
}): React.ReactElement {
  return (
    <Radio.Group
      size="small"
      value={tier}
      disabled={disabled}
      onChange={(event) => {
        // 粗档不可点；parseTier 把一切认不出的值收回默认档，不做脏值透传
        onTierChange(parseTier(event.target.value));
      }}
      options={TIER_OPTIONS.map((option) => ({
        label:
          option.disabledReason === '' ? (
            option.label
          ) : (
            <Tooltip title={option.disabledReason}>{option.label}</Tooltip>
          ),
        value: option.value,
        disabled: option.disabledReason !== '',
      }))}
    />
  );
}
