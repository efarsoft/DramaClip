/** 偏好设置页：settings.get 全量载入 → 分区编辑 → 差异保存（settings.update）。
 * 目录类选项（解说风格 / 字幕预设）异步取回后注入 spec；取不到要说「目录取不到 + 原因」并给重试，
 * 不静默吞成空目录——空目录里的裸 id 会被当成名字（规格 H3 §3.2.2）。 */
import { App as AntdApp, Button, Input, InputNumber, Select, Switch } from 'antd';
import type { CSSProperties } from 'react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { PageHeader, PageSection, PageShell } from '../../components/layout/PageKit';
import { narrationApi, rpc, subtitleApi } from '../../services/client';
import { errorText } from '../engines/errorText';
import { mixins } from '../../styles/mixins';
import { layout, tokens } from '../../styles/theme';
import {
  buildSections,
  type CatalogName,
  type DynamicOptions,
  type FieldSpec,
  type Option,
  type SectionSpec,
  type SettingsMap,
} from './sections';

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
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    const values = await rpc<SettingsMap>('settings.get');
    setOriginal(values);
    setDraft({ ...values });
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const [catalog, setCatalog] = useState<{ styles: Option[]; presets: Option[] }>({
    styles: [],
    presets: [],
  });
  const [problems, setProblems] = useState<Record<CatalogName, string>>({
    styles: '',
    presets: '',
  });

  // 目录各自独立取：一个失败不拖垮另一个；失败侧目录留空（不编选项），原话进故障行（可重试）
  const loadCatalog = useCallback((catalogName: CatalogName) => {
    const options: Promise<Option[]> =
      catalogName === 'styles'
        ? narrationApi
            .listStyles()
            .then((styles) => styles.map((style) => ({ label: style.name, value: style.style_id })))
        : subtitleApi
            .listPresets()
            .then((presets) => presets.map((preset) => ({ label: preset.preset_name, value: preset.preset_id })));
    void options
      .then((next) => {
        setCatalog((prev) => ({ ...prev, [catalogName]: next }));
        setProblems((prev) => ({ ...prev, [catalogName]: '' }));
      })
      .catch((error: unknown) => {
        setProblems((prev) => ({ ...prev, [catalogName]: errorText(error, '服务端未给出原因') }));
      });
  }, []);

  useEffect(() => {
    loadCatalog('styles');
    loadCatalog('presets');
  }, [loadCatalog]);

  const dynamic: DynamicOptions = useMemo(
    () => ({ styles: catalog.styles, presets: catalog.presets, problems, retry: loadCatalog }),
    [catalog, problems, loadCatalog],
  );

  const sections = useMemo(() => buildSections(dynamic), [dynamic]);

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
      saving={saving}
      sections={sections}
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
  saving: boolean;
  sections: readonly SectionSpec[];
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
      <PageHeader title="偏好设置" desc={PAGE_DESC} />
      <SettingsBody draft={props.draft} sections={props.sections} onPatch={patchDraft} />
      {/* 吸底保存栏：仅在存在改动时出现，长表单滚动到底也能看见动作 */}
      {changedKeys.length > 0 && (
        <div
          style={{
            position: 'sticky',
            bottom: 0,
            zIndex: 10,
            // 负边距已撤（§3.4 单层滚动原则）：不留唯一负边距撑出横向滚动条
            padding: `${tokens.spaceMd} ${tokens.space2xl}`,
            display: 'flex',
            alignItems: 'center',
            gap: tokens.spaceMd,
            background: tokens.bgElevated,
            borderTop: `1px solid ${tokens.border}`,
            boxShadow: tokens.shadowSticky,
          }}
        >
          <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, color: tokens.textSecondary }}>
            已修改 {String(changedKeys.length)} 项
          </span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: tokens.spaceSm }}>
            <Button
              onClick={() => {
                props.onDraft({ ...props.original });
              }}
            >
              还原
            </Button>
            <Button type="primary" loading={props.saving} onClick={props.onSave}>
              保存
            </Button>
          </span>
        </div>
      )}
    </PageShell>
  );
}

function SettingsBody({
  draft,
  sections,
  onPatch,
}: {
  draft: SettingsMap;
  sections: readonly SectionSpec[];
  onPatch: (key: string, value: string) => void;
}) {
  return (
    <>
      {sections.map((section) => (
        <PageSection key={section.id} title={section.title}>
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
    <div style={{ ...rowStyle, padding: `0 ${tokens.spaceLg}` }}>
      <div style={mixins.fieldLabelCol()}>
        <div style={{ fontSize: tokens.text.body.size, lineHeight: tokens.text.body.leading, color: tokens.textPrimary }}>{spec.label}</div>
        {spec.help !== undefined && (
          <div
            style={{
              fontSize: tokens.text.meta.size,
              color: tokens.textTertiary,
              marginTop: layout.field.helpMarginTop,
              lineHeight: tokens.text.meta.leading,
            }}
          >
            {spec.help}
          </div>
        )}
      </div>
      <div style={mixins.fieldControlCol()}>
        <FieldControl spec={spec} value={value} values={values} onChange={onChange} />
        {spec.problem !== undefined && (
          <div
            style={{
              marginTop: layout.field.helpMarginTop,
              display: 'flex',
              alignItems: 'center',
              gap: tokens.spaceSm,
            }}
          >
            <span
              style={{
                fontSize: tokens.text.meta.size,
                lineHeight: tokens.text.meta.leading,
                color: tokens.errorText,
              }}
            >
              {spec.problem.text}
            </span>
            <Button size="small" onClick={spec.problem.onRetry}>
              重试
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
