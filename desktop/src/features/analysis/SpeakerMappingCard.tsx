/** 说话人真名映射（v0.2.5 2.2）：角色标签 → 真名，喂文案链的确定性输入——
 * audit 的「未解析标签」从 LLM 猜变为映射表查表。存 project.settings 单键
 * （随项目复制）；未映射标签照旧显示原标签。 */
import { App as AntdApp, Card, Input } from 'antd';
import { useEffect, useState } from 'react';
import type { ReactElement } from 'react';
import { analysisApi } from '../../services/client';
import { tokens } from '../../styles/theme';

/** 行样式（与热词条同款 meta 字号）。 */
const META = {
  fontSize: tokens.text.meta.size,
  lineHeight: tokens.text.meta.leading,
} as const;

export function SpeakerMappingCard({
  projectId,
  labels,
  mapping,
  onMapping,
  onSaved,
}: {
  projectId: string;
  /** 当前集出现过的角色标签（首现顺序）；无分离数据的集整卡不渲染。 */
  labels: readonly string[];
  /** 当前映射（project.settings 读出，由父层持有——转写卡 Chip 同源显示）。 */
  mapping: Record<string, string>;
  onMapping: (next: Record<string, string>) => void;
  /** 任一映射保存成功后的外泄钩子（父层当前用 Reload 语义，可空转）。 */
  onSaved: () => void;
}): ReactElement {
  const { message } = AntdApp.useApp();
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  useEffect(() => {
    let alive = true;
    analysisApi
      .speakerMapping(projectId)
      .then((res) => {
        if (alive) onMapping(res.mapping);
      })
      .catch(() => {
        /* 读不到=无映射可编辑，静默（增强项不挡分析页） */
      });
    return () => {
      alive = false;
    };
  }, [projectId, onMapping]);

  const save = async (label: string): Promise<void> => {
    const name = (drafts[label] ?? '').trim();
    if (name === (mapping[label] ?? '')) return;
    // 不用 delete：no-dynamic-delete 禁动态键删除——重建映射表逐键拷贝
    const next: Record<string, string> = {};
    for (const [key, value] of Object.entries(mapping)) {
      if (key !== label) next[key] = value;
    }
    if (name !== '') next[label] = name;
    try {
      const res = await analysisApi.speakerMapping(projectId, next);
      onMapping(res.mapping);
      setDrafts(res.mapping);
      message.success('真名已保存——下次生成方案按真名称呼角色');
      onSaved();
    } catch (error) {
      message.error(`真名映射没存上：${String(error)}`);
    }
  };

  return (
    <Card
      size="small"
      title="说话人真名（声纹标签 → 剧中真名；解说与文案按真名称呼，留空保持「角色X」）"
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceSm }}>
        {labels.map((label) => (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm }}>
            <span
              style={{
                ...META,
                color: tokens.textSecondary,
                fontFamily: tokens.fontFamilyMono,
                width: 72,
                flexShrink: 0,
              }}
            >
              {label}
            </span>
            <Input
              size="small"
              style={{ width: 220 }}
              placeholder="剧中真名（留空=不映射）"
              value={drafts[label] ?? mapping[label] ?? ''}
              onChange={(event) => {
                setDrafts((prev) => ({ ...prev, [label]: event.target.value }));
              }}
              onBlur={() => {
                void save(label);
              }}
              onPressEnter={(event) => {
                void save(label);
                event.currentTarget.blur();
              }}
            />
          </div>
        ))}
        <span style={{ ...META, color: tokens.textTertiary }}>
          保存后下次生成方案生效；未填的标签保持「角色X」
        </span>
      </div>
    </Card>
  );
}
