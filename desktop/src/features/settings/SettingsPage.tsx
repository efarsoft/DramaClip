/** 偏好设置页：settings.get 全量载入 → 分区编辑 → 差异保存（settings.update）。 */
import { App as AntdApp, Button, Card, Input, InputNumber, Select, Switch } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import { rpc } from '../../services/client';
import { tokens } from '../../styles/theme';
import { buildSections, type FieldSpec, type Option, type SettingsMap } from './sections';

const PAGE_DESC = '分析阈值、字幕与出片参数；LLM/ASR/TTS 引擎配置在「引擎中心」管理。';

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
      <div style={{ maxWidth: 860, margin: '0 auto' }}>
        <Card loading />
      </div>
    );
  }

  const changedKeys = Object.keys(draft).filter((key) => draft[key] !== original[key]);
  const patchDraft = (key: string, value: string): void => {
    setDraft(patchIn(draft, key, value));
  };
  const save = async (): Promise<void> => {
    await saveSettings(changedKeys.map((key) => [key, draft[key] ?? '']), message, load, setSaving);
  };

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 18 }}>
      <header style={{ display: 'flex', alignItems: 'flex-end' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: tokens.textPrimary }}>偏好设置</h1>
          <div style={{ fontSize: 13, color: tokens.textTertiary, marginTop: 6 }}>{PAGE_DESC}</div>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <Button
            onClick={() => {
              setDraft({ ...original });
            }}
            disabled={changedKeys.length === 0}
          >
            还原
          </Button>
          <Button type="primary" loading={saving} disabled={changedKeys.length === 0} onClick={() => void save()}>
            保存{changedKeys.length > 0 ? `（${String(changedKeys.length)} 项）` : ''}
          </Button>
        </div>
      </header>
      <SettingsBody draft={draft} presetOptions={presetOptions} onPatch={patchDraft} />
    </div>
  );
}

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

function patchIn(map: SettingsMap, key: string, value: string): SettingsMap {
  return { ...map, [key]: value };
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
        <Card key={section.title} size="small" title={<SectionTitle text={section.title} />}>
          {section.fields.map((field) => (
            <FieldRow
              key={field.key}
              spec={field}
              value={draft[field.key] ?? ''}
              values={draft}
              onChange={(next) => {
                onPatch(field.key, next);
              }}
            />
          ))}
        </Card>
      ))}
    </>
  );
}

function SectionTitle({ text }: { text: string }): React.ReactElement {
  return (
    <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <span style={{ width: 3, height: 13, borderRadius: 2, background: tokens.gradientAccent }} />
      <span style={{ fontSize: 13.5, fontWeight: 600, color: tokens.textPrimary }}>{text}</span>
    </span>
  );
}

function FieldControl({
  spec,
  value,
  values,
  onChange,
}: {
  spec: FieldSpec;
  value: string;
  values: SettingsMap;
  onChange: (next: string) => void;
}) {
  const wide = { width: 280 } as const;
  switch (spec.type) {
    case 'password':
      return (
        <Input.Password
          value={value}
          placeholder={spec.placeholder}
          onChange={(event) => {
            onChange(event.target.value);
          }}
        />
      );
    case 'number':
      return (
        <InputNumber
          style={wide}
          value={Number(value)}
          min={spec.min}
          max={spec.max}
          onChange={(next) => {
            if (next !== null) onChange(String(next));
          }}
        />
      );
    case 'select':
      return <SelectField spec={spec} value={value} values={values} onChange={onChange} />;
    case 'switch':
      return (
        <Switch
          checked={value === 'true'}
          onChange={(checked) => {
            onChange(String(checked));
          }}
        />
      );
    default:
      return (
        <Input
          style={wide}
          value={value}
          placeholder={spec.placeholder}
          onChange={(event) => {
            onChange(event.target.value);
          }}
        />
      );
  }
}

function SelectField({
  spec,
  value,
  values,
  onChange,
}: {
  spec: FieldSpec;
  value: string;
  values: SettingsMap;
  onChange: (next: string) => void;
}) {
  return (
    <Select
      style={{ width: 280 }}
      value={value}
      options={spec.options?.(values).map((option) => ({ ...option }))}
      onChange={onChange}
    />
  );
}

function FieldRow({
  spec,
  value,
  values,
  onChange,
}: {
  spec: FieldSpec;
  value: string;
  values: SettingsMap;
  onChange: (next: string) => void;
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 18,
        padding: '10px 0',
        borderBottom: `1px solid ${tokens.borderSecondary}`,
      }}
    >
      <div style={{ width: 200, flexShrink: 0 }}>
        <div style={{ fontSize: 13, color: tokens.textPrimary }}>{spec.label}</div>
        {spec.help !== undefined && (
          <div style={{ fontSize: 11.5, color: tokens.textTertiary, marginTop: 3, lineHeight: '17px' }}>
            {spec.help}
          </div>
        )}
      </div>
      <FieldControl spec={spec} value={value} values={values} onChange={onChange} />
    </div>
  );
}
