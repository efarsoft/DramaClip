/** 提示词 tab：八处 LLM 提示词的查看/编辑/重置（覆盖存 settings，默认在代码）。 */
import type { ReactElement } from 'react';
import { PromptCard, PromptHint } from './PromptCard';
import { PromptEditor } from './PromptEditor';
import { tokens } from '../../styles/theme';
import { usePrompts } from './usePrompts';

export function PromptsTab(): ReactElement {
  const { prompts, editing, setEditing, draft, setDraft, saving, save, reset } = usePrompts();
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceLg }}>
      <PromptHint />
      {(prompts ?? []).map((info) => (
        <PromptCard key={info.key} info={info} onEdit={setEditing} onReset={reset} />
      ))}
      <PromptEditor
        editing={editing}
        draft={draft}
        saving={saving}
        onDraft={setDraft}
        onSave={() => {
          void save();
        }}
        onClose={() => {
          setEditing(null);
        }}
      />
    </div>
  );
}
