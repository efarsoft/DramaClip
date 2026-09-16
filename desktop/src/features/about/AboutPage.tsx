/** 关于（独立页面；业主裁决 2026-09-15 替代规格 §4.8 的覆盖层方案）。
 *
 * 「检查更新」与公众号/打赏二维码未实装——缺席而非假控件，实装后在此补。
 */
import { InfoOutlined } from '@ant-design/icons';
import { useEffect, useState, type ReactElement } from 'react';
import { PageHeader, PageSection, PageShell } from '../../components/layout/PageKit';
import { appPaths, appVersion, revealInFolder, systemApi } from '../../services/client';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';

/** 开源组件清单（分发含第三方二进制与字体，许可清单是发版应有项）。 */
const OPEN_SOURCE =
  'Electron · React · Ant Design · FFmpeg · PySceneDetect · OpenCV · faster-whisper · edge-tts · Kokoro';

/** 授权与合规声明（素材授权责任归使用者；全本机处理，素材不上传）。 */
const COMPLIANCE =
  '素材授权责任由使用者承担；本软件不代为取得或证明素材授权，亦不提供规避原创性检测的功能。媒体处理全部在本机完成，素材不上传。';

export function AboutPage(): ReactElement {
  return (
    <PageShell>
      <PageHeader title="关于" desc="项目信息 · 版本 · 本地数据 · 许可与声明" />
      <ProjectBlock />
      <VersionBlock />
      <LocalDataBlock />
      <PageSection title="开源许可">
        <div style={{ fontSize: tokens.fontMicro, lineHeight: '18px', color: tokens.textTertiary }}>
          {OPEN_SOURCE}
        </div>
      </PageSection>
      <PageSection title="授权与合规声明">
        <div style={{ fontSize: tokens.fontMicro, lineHeight: '18px', color: tokens.textTertiary }}>
          {COMPLIANCE}
        </div>
      </PageSection>
      <div style={{ fontSize: tokens.fontMicro, color: tokens.textTertiary, textAlign: 'center' }}>
        © 2026 DramaClip · 本地优先的短剧高光剪辑工具
      </div>
    </PageShell>
  );
}

/** 品牌块：Logo + 名称 + 一句话定位。 */
function ProjectBlock(): ReactElement {
  return (
    <PageSection title="项目信息">
      <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceMd }}>
        <span
          style={{
            width: 40,
            height: 40,
            borderRadius: tokens.radiusControl,
            background: tokens.gradientAccent,
            color: tokens.colorWhite,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: tokens.fontTitleLg,
          }}
        >
          ▶
        </span>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
          <span style={{ fontSize: tokens.fontBodyLg, fontWeight: 600, color: tokens.textPrimary }}>
            DramaClip
          </span>
          <span style={{ fontSize: tokens.fontCaption, color: tokens.textTertiary }}>
            本地优先的短剧高光剪辑工具——分析、编剧、配音、成片全在本机完成。
          </span>
        </div>
      </div>
    </PageSection>
  );
}

function VersionBlock(): ReactElement {
  const [app, setApp] = useState('');
  const [service, setService] = useState('');
  useEffect(() => {
    void appVersion().then(setApp);
    void systemApi
      .ping()
      .then((ping) => {
        setService(ping.service_version);
      })
      .catch(() => undefined);
  }, []);
  return (
    <PageSection title="版本">
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceXs }}>
        <span style={{ fontSize: tokens.fontCaption, color: tokens.textSecondary }}>
          应用 {app === '' ? '…' : `v${app}`}
        </span>
        <span style={{ fontSize: tokens.fontCaption, color: tokens.textSecondary }}>
          Python 服务 {service === '' ? '…' : `v${service}`}
        </span>
      </div>
    </PageSection>
  );
}

function LocalDataBlock(): ReactElement {
  const rows: readonly { label: string; key: 'root' | 'outputs' | 'models' | 'logs' }[] = [
    { label: '成品目录', key: 'outputs' },
    { label: '数据与数据库', key: 'root' },
    { label: '模型目录', key: 'models' },
    { label: '日志（含 LLM 留痕）', key: 'logs' },
  ];
  return (
    <PageSection title="本地数据" dense>
      <div>
        {rows.map((row) => (
          <DataPathRow key={row.key} label={row.label} pathKey={row.key} />
        ))}
      </div>
    </PageSection>
  );
}

function DataPathRow({
  label,
  pathKey,
}: {
  label: string;
  pathKey: 'root' | 'outputs' | 'models' | 'logs';
}): ReactElement {
  const open = (): void => {
    void appPaths()
      .then((paths) => {
        return revealInFolder(paths[pathKey]);
      })
      .catch(() => undefined);
  };
  return (
    <div style={{ ...mixins.listRow(), padding: `${String(tokens.spaceSm)} ${String(tokens.spaceLg)}` }}>
      <span style={{ fontSize: tokens.fontCaption, color: tokens.textSecondary }}>{label}</span>
      <button
        type="button"
        onClick={open}
        style={{
          marginLeft: 'auto',
          background: 'none',
          border: 'none',
          padding: 0,
          color: tokens.colorPrimary,
          fontSize: tokens.fontCaption,
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          gap: tokens.spaceXs,
        }}
      >
        <InfoOutlined style={{ fontSize: tokens.fontIcon }} />
        打开
      </button>
    </div>
  );
}
