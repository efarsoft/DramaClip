import { App as AntdApp, Button, Card, Input, InputNumber, Select, Switch } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import { rpc } from '../../services/client';
import { tokens } from '../../styles/theme';
import { buildSections, type FieldSpec, type Option, type SettingsMap } from './sections';

/** 系统设置页：settings.get 全量载入 → 分区编辑 → 差异保存（settings.update）。 */
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
    if (changedKeys.length === 0) return;
    setSaving(true);
    try {
      const values = Object.fromEntries(changedKeys.map((key) => [key, draft[key]]));
      await rpc('settings.update', { values });
      message.success('设置已保存');
      await load();
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ maxWidth: 860, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 20 }}>
      <SaveActions
        changedCount={changedKeys.length}
        saving={saving}
        onRevert={() => {
          setDraft({ ...original });
        }}
        onSave={() => {
          void save();
        }}
      />
      <SettingsBody draft={draft} presetOptions={presetOptions} onPatch={patchDraft} />
    </div>
  );
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
        <Card key={section.title} size="small" title={section.title}>
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

function SaveActions({
  changedCount,
  saving,
  onRevert,
  onSave,
}: {
  changedCount: number;
  saving: boolean;
  onRevert: () => void;
  onSave: () => void;
}) {
  return (
    <header style={{ display: 'flex', alignItems: 'center' }}>
      <h1 style={{ margin: 0, fontSize: 20, color: tokens.textPrimary }}>偏好设置</h1>
      <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
        <Button onClick={onRevert} disabled={changedCount === 0}>
          还原
        </Button>
        <Button type="primary" loading={saving} disabled={changedCount === 0} onClick={onSave}>
          保存{changedCount > 0 ? `（${String(changedCount)} 项）` : ''}
        </Button>
      </div>
    </header>
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
  const wide = { width: 260 } as const;
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
      style={{ width: 260 }}
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
    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16, padding: '8px 0' }}>
      <div style={{ width: 160, flexShrink: 0, fontSize: 13, color: tokens.textSecondary, paddingTop: 4 }}>
        {spec.label}
      </div>
      <FieldControl spec={spec} value={value} values={values} onChange={onChange} />
      <div style={{ fontSize: 12, color: tokens.textTertiary, paddingTop: 5, minWidth: 0 }}>
        {spec.help ?? ''}
      </div>
    </div>
  );
}
