/** 偏好设置页：settings.get 全量载入 → 分区编辑 → 差异保存（settings.update）。 */
import { App as AntdApp, Button, Input, InputNumber, Select, Switch } from 'antd';
import type { CSSProperties } from 'react';
import { useCallback, useEffect, useState } from 'react';
import { PageHeader, PageSection, PageShell } from '../../components/layout/PageKit';
import { rpc } from '../../services/client';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';
import { buildSections, type FieldSpec, type Option, type SettingsMap } from './sections';

const PAGE_DESC = '分析阈值、字幕与出片参数；LLM/ASR/TTS 引擎配置在「引擎中心」管理。';

interface Notify {
  error: (text: string) => void;
  success: (text: string) => void;
}

async function saveSettings(
  entries: [string, string][],
  message: Notify,
  reload: () => Promise<void>,
  setSaving: (saving: boolean) => void,
): Promise<void> {
  setSaving(true);
  try {
    await rpc('settings.update', { values: Object.fromEntries(entries) });
    message.success('设置已保存');
    await reload();
  } catch (error) {
    message.error(error instanceof Error ? error.message : String(error));
  } finally {
    setSaving(false);
  }
}

/** 偏好设置页。 */
export function SettingsPage() {
  const { message } = AntdApp.useApp();
  const [original, setOriginal] = useState<SettingsMap | null>(null);
  const [draft, setDraft] = useState<SettingsMap | null>(null);
  const [presetOptions, setPresetOptions] = useState<readonly Option[]>([]);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    const [values, presets] = await Promise.all([
      rpc<SettingsMap>('settings.get'),
      rpc<{ preset_id: string; preset_name: string }[]>('subtitle.list_presets'),
    ]);
    setOriginal(values);
    setDraft({ ...values });
    setPresetOptions(presets.map((p) => ({ label: p.preset_name, value: p.preset_id })));
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (draft === null || original === null) {
    return (
      <PageShell>
        <PageSection>加载中…</PageSection>
      </PageShell>
    );
  }

  const changedKeys = Object.keys(draft).filter((key) => draft[key] !== original[key]);
  const save = async (): Promise<void> => {
    await saveSettings(changedKeys.map((key) => [key, draft[key] ?? '']), message, load, setSaving);
  };

  return (
    <SettingsView
      original={original}
      draft={draft}
      presetOptions={presetOptions}
      saving={saving}
      onDraft={setDraft}
      onSave={() => {
        void save();
      }}
    />
  );
}

function SettingsView(props: {
  original: SettingsMap;
  draft: SettingsMap;
  presetOptions: readonly Option[];
  saving: boolean;
  onDraft: (next: SettingsMap) => void;
  onSave: () => void;
}): React.ReactElement {
  const changedKeys = Object.keys(props.draft).filter(
    (key) => props.draft[key] !== props.original[key],
  );
  const patchDraft = (key: string, value: string): void => {
    props.onDraft({ ...props.draft, [key]: value });
  };
  return (
    <PageShell>
      <PageHeader
        title="偏好设置"
        desc={PAGE_DESC}
        actions={
          <>
            <Button
              disabled={changedKeys.length === 0}
              onClick={() => {
                props.onDraft({ ...props.original });
              }}
            >
              还原
            </Button>
            <Button
              type="primary"
              loading={props.saving}
              disabled={changedKeys.length === 0}
              onClick={props.onSave}
            >
              保存{changedKeys.length > 0 ? `（${String(changedKeys.length)} 项）` : ''}
            </Button>
          </>
        }
      />
      <SettingsBody draft={props.draft} presetOptions={props.presetOptions} onPatch={patchDraft} />
    </PageShell>
  );
}

function SettingsBody({
  draft,
  presetOptions,
  onPatch,
}: {
  draft: SettingsMap;
  presetOptions: readonly Option[];
  onPatch: (key: string, value: string) => void;
}) {
  return (
    <>
      {buildSections(presetOptions).map((section) => (
        <PageSection key={section.id} title={`${section.icon} ${section.title}`}>
          {section.fields.map((field, index, all) => (
            <FieldRow
              key={field.key}
              spec={field}
              value={draft[field.key] ?? ''}
              values={draft}
              last={index === all.length - 1}
              onChange={(next) => {
                onPatch(field.key, next);
              }}
            />
          ))}
        </PageSection>
      ))}
    </>
  );
}

function FieldControl(props: {
  spec: FieldSpec;
  value: string;
  values: SettingsMap;
  onChange: (next: string) => void;
}): React.ReactElement {
  const { spec, value, values, onChange } = props;
  switch (spec.type) {
    case 'number':
      return (
        <InputNumber
          style={{ width: '100%' }}
          value={Number(value)}
          min={spec.min}
          max={spec.max}
          onChange={(next) => {
            if (next !== null) onChange(String(next));
          }}
        />
      );
    case 'select':
      return (
        <Select
          style={{ width: '100%' }}
          value={value}
          options={spec.options?.(values).map((option) => ({ ...option }))}
          onChange={onChange}
        />
      );
    case 'switch':
      return <SwitchControl value={value} onChange={onChange} />;
    case 'password':
      return <TextField password spec={spec} value={value} onChange={onChange} />;
    default:
      return <TextField spec={spec} value={value} onChange={onChange} />;
  }
}

function SwitchControl({
  value,
  onChange,
}: {
  value: string;
  onChange: (next: string) => void;
}) {
  return (
    <Switch
      checked={value === 'true'}
      onChange={(checked) => {
        onChange(String(checked));
      }}
    />
  );
}

function TextField({
  spec,
  value,
  onChange,
  password = false,
}: {
  spec: FieldSpec;
  value: string;
  onChange: (next: string) => void;
  password?: boolean;
}): React.ReactElement {
  const Control = password ? Input.Password : Input;
  return (
    <Control
      style={{ width: '100%' }}
      value={value}
      placeholder={spec.placeholder}
      onChange={(event) => {
        onChange(event.target.value);
      }}
    />
  );
}

function FieldRow({
  spec,
  value,
  values,
  last,
  onChange,
}: {
  spec: FieldSpec;
  value: string;
  values: SettingsMap;
  last: boolean;
  onChange: (next: string) => void;
}) {
  const rowStyle: CSSProperties = last
    ? { ...mixins.fieldRow(), borderBottom: 'none' }
    : mixins.fieldRow();
  return (
    <div style={{ ...rowStyle, padding: `0 ${String(tokens.spaceLg)}` }}>
      <div style={mixins.fieldLabelCol()}>
        <div style={{ fontSize: tokens.fontBody, color: tokens.textPrimary }}>{spec.label}</div>
        {spec.help !== undefined && (
          <div
            style={{
              fontSize: tokens.fontCaption,
              color: tokens.textTertiary,
              marginTop: 3,
              lineHeight: '17px',
            }}
          >
            {spec.help}
          </div>
        )}
      </div>
      <div style={mixins.fieldControlCol()}>
        <FieldControl spec={spec} value={value} values={values} onChange={onChange} />
      </div>
    </div>
  );
}
