/** 关于（规格 §4.8）：导轨下组第 8 项，渲染为居中覆盖层而非整页。
 *
 * 硬约束：永不自动弹出，只能经导轨主动打开；Esc 或点遮罩关闭（深链 /about 关闭回首页）。
 * 「检查更新」与公众号/打赏二维码未实装——缺席而非假控件，实装后在此补。
 */
import { InfoOutlined } from '@ant-design/icons';
import { useEffect, useState, type ReactNode } from 'react';
import type { ReactElement } from 'react';
import { useNavigate } from 'react-router-dom';
import { appPaths, appVersion, revealInFolder, systemApi } from '../../services/client';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';

/** 开源组件清单（分发含第三方二进制与字体，许可清单是发版应有项）。 */
const OPEN_SOURCE = 'Electron · React · Ant Design · FFmpeg · PySceneDetect · OpenCV · faster-whisper · edge-tts · Kokoro';

/** 授权与合规声明（素材授权责任归使用者；全本机处理，素材不上传）。 */
const COMPLIANCE =
  '素材授权责任由使用者承担；本软件不代为取得或证明素材授权，亦不提供规避原创性检测的功能。媒体处理全部在本机完成，素材不上传。';

export function AboutPage(): ReactElement {
  const navigate = useNavigate();
  const close = (): void => {
    void navigate('/');
  };
  useEscToClose(close);

  return (
    <div
      role="presentation"
      onClick={close}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 60,
        background: 'rgba(4, 6, 12, 0.62)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <section
        aria-label="关于 DramaClip"
        onClick={(event) => {
          event.stopPropagation();
        }}
        style={{
          width: 640,
          minHeight: 460,
          display: 'flex',
          flexDirection: 'column',
          background: tokens.bgElevated,
          border: `1px solid ${tokens.borderSecondary}`,
          borderRadius: tokens.radiusCard,
          overflow: 'hidden',
        }}
      >
        <div style={{ display: 'flex', flex: 1, minWidth: 0 }}>
          <BrandColumn />
          <InfoColumn />
        </div>
        <footer
          style={{
            padding: `${String(tokens.spaceSm)} ${String(tokens.spaceLg)}`,
            borderTop: `1px solid ${tokens.borderSecondary}`,
            fontSize: tokens.fontMicro,
            color: tokens.textTertiary,
          }}
        >
          © 2026 DramaClip · 本地优先的短剧高光剪辑工具
        </footer>
      </section>
    </div>
  );
}

function useEscToClose(close: () => void): void {
  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') close();
    };
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}

/** 左栏 190px：品牌与一句话定位（公众号/打赏码待 resources/about/ 就位后补）。 */
function BrandColumn(): ReactElement {
  return (
    <aside
      style={{
        width: 190,
        flexShrink: 0,
        padding: tokens.spaceLg,
        display: 'flex',
        flexDirection: 'column',
        gap: tokens.spaceSm,
        borderRight: `1px solid ${tokens.borderSecondary}`,
        background: tokens.bgContainer,
      }}
    >
      <span
        style={{
          width: 40,
          height: 40,
          borderRadius: tokens.radiusControl,
          background: tokens.gradientAccent,
          color: '#ffffff',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: tokens.fontTitleLg,
        }}
      >
        ▶
      </span>
      <div style={{ fontSize: tokens.fontTitleLg, fontWeight: 700, color: tokens.textPrimary }}>
        DramaClip
      </div>
      <div style={{ fontSize: tokens.fontCaption, lineHeight: '19px', color: tokens.textTertiary }}>
        本地优先的短剧高光剪辑工具——分析、编剧、配音、成片全在本机完成。
      </div>
    </aside>
  );
}

/** 右栏四块：版本 / 本地数据 / 开源许可 / 授权声明。 */
function InfoColumn(): ReactElement {
  return (
    <div
      style={{
        flex: 1,
        minWidth: 0,
        padding: tokens.spaceLg,
        display: 'flex',
        flexDirection: 'column',
        gap: tokens.spaceLg,
      }}
    >
      <VersionBlock />
      <LocalDataBlock />
      <InfoBlock title="开源许可">
        <div style={{ fontSize: tokens.fontMicro, lineHeight: '18px', color: tokens.textTertiary }}>
          {OPEN_SOURCE}
        </div>
      </InfoBlock>
      <InfoBlock title="授权与合规声明">
        <div style={{ fontSize: tokens.fontMicro, lineHeight: '18px', color: tokens.textTertiary }}>
          {COMPLIANCE}
        </div>
      </InfoBlock>
    </div>
  );
}

function VersionBlock(): ReactElement {
  return (
    <InfoBlock title="版本">
      <VersionRows />
    </InfoBlock>
  );
}

function VersionRows(): ReactElement {
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
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <span style={{ fontSize: tokens.fontCaption, color: tokens.textSecondary }}>
        应用 {app === '' ? '…' : `v${app}`}
      </span>
      <span style={{ fontSize: tokens.fontCaption, color: tokens.textSecondary }}>
        Python 服务 {service === '' ? '…' : `v${service}`}
      </span>
    </div>
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
    <InfoBlock title="本地数据">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {rows.map((row) => (
          <DataPathRow key={row.key} label={row.label} pathKey={row.key} />
        ))}
      </div>
    </InfoBlock>
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
    <div style={{ ...mixins.listRow(), minHeight: 26 }}>
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
          gap: 4,
        }}
      >
        <InfoOutlined style={{ fontSize: tokens.fontIcon }} />
        打开
      </button>
    </div>
  );
}

function InfoBlock({ title, children }: { title: string; children: ReactNode }): ReactElement {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ fontSize: tokens.fontCaption, fontWeight: 600, color: tokens.textPrimary }}>
        {title}
      </div>
      {children}
    </div>
  );
}
