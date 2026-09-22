/**
 * 引擎中心：单页六段（§10.4）——就绪与修复 / 转写 / 配音 / 文案 / 提示词 / 环境。
 * 五个 tab 合并为同一页的纵向流，用户不必在「看到异常 → 跳屏 → 滚动找那一行」之间来回跳；
 * `/engines/:tab` 降级为同页锚点深链（engineAnchors），既有 navigate 调用点一行不改。
 * 216px 左导航随 tab 骨架一起退场；段标题走 text.sectionTitle（§10.4），段间分隔用 space.*。
 */
import { useEffect } from 'react';
import type { ReactElement, ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import type { ImportRecord, ModelInfo, SelftestResults } from '@dramaclip/protocol';
import { PageHeader, PageSection, PageShell } from '../../components/layout/PageKit';
import { tokens } from '../../styles/theme';
import { AsrTab } from './AsrTab';
import { TtsTab } from './TtsTab';
import { LlmTab } from './LlmTab';
import { PromptsTab } from './PromptsTab';
import { EnvSection } from './EnvSection';
import { ReadinessCard } from './ReadinessCard';
import { ImportModelModal } from './ImportModelModal';
import type { EngineTab, Reports } from './assetState';
import { anchorFromPath, SECTION_IDS } from './engineAnchors';
import type { MachineSpecs } from './machineFit';
import { type EnginesData, useEnginesData } from './useEnginesData';
import { useModelImport } from './useModelImport';
import { workReadiness } from './workReadiness';

export type SettingsMap = Record<string, string>;

/** ASR / TTS 两段同构：同一份数据、同一批回调（分段不分数据流）。 */
export interface DomainTabProps {
  readonly models: ModelInfo[];
  /** 「本地导入」登记本原样交下来：哪几条属于本域，由 externalAssets 判，段里不重写。 */
  readonly imported: ImportRecord[];
  /** 登记本读坏了的原话，空串 = 读通了；坏了不等于库里没货。 */
  readonly importError: string;
  readonly settings: SettingsMap;
  readonly reports: Reports;
  /** 自检账本：就绪 = 校验过 + 自检过（§10.1），能力层那一半从这里来。 */
  readonly selftests?: SelftestResults;
  readonly machine: MachineSpecs;
  readonly onSave: (values: SettingsMap) => void;
  readonly onChanged: () => void;
  readonly onVerify: (modelId: string) => void;
  readonly onForget: (path: string) => void;
  readonly onImport: () => void;
}

/** 引擎中心页（导航「引擎」）。 */
export function EnginesPage(): ReactElement {
  const navigate = useNavigate();
  const location = useLocation();
  const { data, load, saveSettings, verifyOne } = useEnginesData();
  const hub = useModelImport(data?.models ?? [], load, saveSettings);
  const anchor = anchorFromPath(location.pathname);
  useEffect(() => {
    if (data === null) return;
    // 段随数据落地才渲染，滚定位必须等这一帧画完；key 进依赖：同一段锚点重复点也要重新定位
    const timer = window.setTimeout(() => {
      const target = document.getElementById(anchor);
      // jsdom 没有 scrollIntoView：探测到才调，测试环境不炸、真浏览器行为不变
      if (target !== null && typeof target.scrollIntoView === 'function') {
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }, 0);
    return () => {
      window.clearTimeout(timer);
    };
  }, [data, anchor, location.key]);
  return (
    <PageShell>
      <PageHeader title="引擎中心" desc="一页六段：就绪与修复、转写、配音、文案、提示词、环境——看到异常，就地修" />
      {data === null ? (
        <PageSection>加载中…</PageSection>
      ) : (
        <Sections
          data={data}
          onForget={hub.forget}
          onImport={hub.open}
          onSave={saveSettings}
          onLoaded={load}
          onVerify={verifyOne}
          onGo={(tab) => {
            void navigate(`/engines/${tab}`);
          }}
        />
      )}
      <ImportModelModal
        open={hub.importing}
        onClose={hub.close}
        onChanged={() => {
          void load();
        }}
        onActivate={hub.activateLanded}
      />
    </PageShell>
  );
}

/** 六段纵向流。段序即 §10.4 的 1–6，锚点 id 与 engineAnchors 的表一一对应。 */
function Sections({
  data,
  onForget,
  onImport,
  onSave,
  onLoaded,
  onVerify,
  onGo,
}: {
  data: EnginesData;
  onForget: (path: string) => void;
  onImport: () => void;
  onSave: (values: SettingsMap) => Promise<void>;
  onLoaded: () => Promise<void>;
  onVerify: (modelId: string) => Promise<void>;
  onGo: (tab: EngineTab) => void;
}): ReactElement {
  const domain = domainProps(data, onSave, onLoaded, onVerify, onForget, onImport);
  const steps = workReadiness({
    models: data.models,
    reports: data.reports,
    selftests: data.selftests,
    settings: data.settings,
    ffmpegVersion: data.ffmpegVersion,
  });
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.space2xl }}>
      <SectionShell id={SECTION_IDS.readiness} title="就绪与修复">
        <ReadinessCard
          steps={steps}
          models={data.models}
          reports={data.reports}
          selftests={data.selftests}
          settings={data.settings}
          onGo={onGo}
          onChanged={domain.onChanged}
          onVerify={domain.onVerify}
        />
      </SectionShell>
      <SectionShell id={SECTION_IDS.asr} title="转写（ASR）">
        <AsrTab {...domain} />
      </SectionShell>
      <SectionShell id={SECTION_IDS.tts} title="配音（TTS）">
        <TtsTab {...domain} />
      </SectionShell>
      <SectionShell id={SECTION_IDS.llm} title="文案（LLM）">
        <LlmTab onChanged={domain.onChanged} />
      </SectionShell>
      <SectionShell id={SECTION_IDS.prompts} title="提示词">
        <PromptsTab />
      </SectionShell>
      <SectionShell id={SECTION_IDS.env} title="环境">
        <EnvSection models={data.models} settings={data.settings} />
      </SectionShell>
    </div>
  );
}

/** 两段共用的域 props：Promise 回调在这里收口成同步签名，段内不写 void 包装。 */
function domainProps(
  data: EnginesData,
  onSave: (values: SettingsMap) => Promise<void>,
  onLoaded: () => Promise<void>,
  onVerify: (modelId: string) => Promise<void>,
  onForget: (path: string) => void,
  onImport: () => void,
): DomainTabProps {
  return {
    models: data.models,
    imported: data.imported,
    importError: data.importError,
    settings: data.settings,
    reports: data.reports,
    selftests: data.selftests,
    machine: data.machine,
    onSave: (values) => {
      void onSave(values);
    },
    onChanged: () => {
      void onLoaded();
    },
    onVerify: (modelId) => {
      void onVerify(modelId);
    },
    onForget,
    onImport,
  };
}

/** 段壳：锚点 id + sectionTitle 字阶标题（20/28，§1）；卡容器由段内组件自理。 */
function SectionShell({ id, title, children }: { id: string; title: string; children: ReactNode }): ReactElement {
  return (
    <div
      id={id}
      style={{ scrollMarginTop: tokens.spaceLg, display: 'flex', flexDirection: 'column', gap: tokens.spaceMd }}
    >
      <h2
        style={{
          margin: 0,
          fontSize: tokens.text.sectionTitle.size,
          lineHeight: tokens.text.sectionTitle.leading,
          fontWeight: tokens.text.sectionTitle.weight,
          color: tokens.textPrimary,
        }}
      >
        {title}
      </h2>
      {children}
    </div>
  );
}
