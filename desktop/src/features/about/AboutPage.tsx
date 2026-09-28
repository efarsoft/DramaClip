/** 关于（独立页面；业主裁决 2026-09-15 替代规格 §4.8 的覆盖层方案）。
 *
 * 「检查更新」与公众号/打赏二维码未实装——缺席而非假控件，实装后在此补。
 */
import { InfoOutlined, PlayCircleFilled } from '@ant-design/icons';
import { App as AntdApp } from 'antd';
import { useEffect, useState, type CSSProperties, type ReactElement } from 'react';
import { PageHeader, PageSection, PageShell } from '../../components/layout/PageKit';
import { appPaths, appVersion, revealInFolder, systemApi } from '../../services/client';
import { mixins } from '../../styles/mixins';
import { tokens } from '../../styles/theme';
import { OPEN_SOURCE } from './openSource';
import wechatQrcode from '../../assets/images/wechat-qrcode.jpg';

/** 授权与合规声明（素材授权责任归使用者；全本机处理，素材不上传）。 */
const COMPLIANCE =
  '素材授权责任由使用者承担；本软件不代为取得或证明素材授权，亦不提供规避原创性检测的功能。媒体处理全部在本机完成，素材不上传。';

export function AboutPage(): ReactElement {
  return (
    <PageShell>
      <PageHeader title="关于" desc="项目信息 · 版本 · 本地数据 · 许可与声明" />
      <ProjectBlock />
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: tokens.space2xl, alignItems: 'start' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.space2xl, minWidth: 0 }}>
          <LocalDataBlock />
          <WechatBlock />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.space2xl, minWidth: 0 }}>
          <VersionBlock />
          <PageSection title="开源许可">
            <div style={COPY}>{OPEN_SOURCE.join(' · ')}</div>
          </PageSection>
          <PageSection title="授权与合规声明">
            <div style={COPY}>{COMPLIANCE}</div>
          </PageSection>
        </div>
      </div>
      <div
        style={{
          fontSize: tokens.text.meta.size,
          lineHeight: tokens.text.meta.leading,
          color: tokens.textTertiary,
          textAlign: 'center',
        }}
      >
        © 2026 DramaClip · 本地优先的短剧高光剪辑工具
      </div>
    </PageShell>
  );
}

/** 卡内说明文案：完整句子最低 body 14/22（§1.2 ①），行高随字阶成对走。 */
const COPY: CSSProperties = {
  fontSize: tokens.text.body.size,
  lineHeight: tokens.text.body.leading,
  color: tokens.textTertiary,
};

/** 品牌块：Logo + 名称 + 一句话定位。 */
function ProjectBlock(): ReactElement {
  return (
    <PageSection title="项目信息">
      <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceMd }}>
        <span
          style={{
            width: tokens.glyph.brandBox,
            height: tokens.glyph.brandBox,
            borderRadius: tokens.radiusControl,
            background: tokens.gradientAccent,
            color: tokens.colorWhite,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: tokens.glyph.brandMd,
          }}
        >
          <PlayCircleFilled />
        </span>
        <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceXs, minWidth: 0 }}>
          <span
            style={{
              fontSize: tokens.text.body.size,
              lineHeight: tokens.text.body.leading,
              fontWeight: tokens.text.body.weightLatin,
              color: tokens.textPrimary,
            }}
          >
            DramaClip
          </span>
          <span
            style={{
              fontSize: tokens.text.body.size,
              lineHeight: tokens.text.body.leading,
              color: tokens.textTertiary,
            }}
          >
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
        <VersionRow label="应用" value={app} />
        <VersionRow label="Python 服务" value={service} />
      </div>
    </PageSection>
  );
}

/** 版本行：元信息字阶，版本号本身走等宽（§1.3 数字必配 mono）。 */
function VersionRow({ label, value }: { label: string; value: string }): ReactElement {
  return (
    <span
      style={{
        fontSize: tokens.text.meta.size,
        lineHeight: tokens.text.meta.leading,
        color: tokens.textSecondary,
      }}
    >
      {label}{' '}
      <span style={{ fontFamily: tokens.fontFamilyMono }}>{value === '' ? '…' : `v${value}`}</span>
    </span>
  );
}

function LocalDataBlock(): ReactElement {
  const rows: readonly { label: string; key: 'root' | 'outputs' | 'models' | 'logs' | 'trash' }[] = [
    { label: '成品目录', key: 'outputs' },
    { label: '数据与数据库', key: 'root' },
    { label: '模型目录', key: 'models' },
    { label: '日志（含 LLM 留痕）', key: 'logs' },
    { label: '回收站（删除的成片按日期暂存，清空才真删）', key: 'trash' },
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
  pathKey: 'root' | 'outputs' | 'models' | 'logs' | 'trash';
}): ReactElement {
  const { message } = AntdApp.useApp();
  const open = (): void => {
    void appPaths()
      .then((paths) => revealInFolder(paths[pathKey]))
      .then((result) => {
        if (!result.ok) message.info(result.reason ?? '打不开该目录');
      })
      .catch(() => undefined);
  };
  return (
    <div style={{ ...mixins.listRow(), padding: `${tokens.spaceSm} ${tokens.spaceLg}` }}>
      <span
        style={{
          fontSize: tokens.text.body.size,
          lineHeight: tokens.text.body.leading,
          color: tokens.textSecondary,
        }}
      >
        {label}
      </span>
      <button
        type="button"
        onClick={open}
        style={{
          marginLeft: 'auto',
          background: 'none',
          border: 'none',
          padding: 0,
          color: tokens.colorPrimary,
          fontSize: tokens.text.body.size,
          lineHeight: tokens.text.body.leading,
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          gap: tokens.spaceXs,
        }}
      >
        <InfoOutlined style={{ fontSize: tokens.glyph.icon }} />
        打开
      </button>
    </div>
  );
}

/** 公众号卡：二维码 + 引导文案。扫码后长按识别在微信内完成，故无需附链接。 */
function WechatBlock(): ReactElement {
  return (
    <PageSection title="联系与反馈">
      <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceLg }}>
        <img
          src={wechatQrcode}
          alt="微信公众号二维码"
          style={{
            width: 112,
            height: 112,
            borderRadius: tokens.radiusControl,
            flexShrink: 0,
          }}
        />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 }}>
          <span style={{ fontSize: tokens.text.body.size, fontWeight: 600, color: tokens.textPrimary }}>
            关注公众号
          </span>
          <div style={COPY}>
            获取更新动态、使用技巧与短剧推广实操内容；问题反馈与交流也在公众号进行。
          </div>
        </div>
      </div>
    </PageSection>
  );
}
