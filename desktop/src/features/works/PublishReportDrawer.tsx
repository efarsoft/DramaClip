/** harness 数据报告（批二#6–#9）：只读事实表——调权永远人拍板，本页不改任何规则。
 *  聚合口径在服务端 export_report 单持，本组件只渲染与搬运。 */
import { Alert, Drawer, Empty, Select, Spin, Table, Tabs, Tag } from 'antd';
import { useEffect, useState, type ReactElement } from 'react';
import type { AbPair, AbReport, PublishReport, PublishReportRow } from '@dramaclip/protocol';
import { exportApi } from '../../services/client';
import { errorText } from '../engines/errorText';
import { tokens } from '../../styles/theme';

const DIMENSION_OPTIONS = [
  { value: 'mode', label: '模式' },
  { value: 'arc', label: '叙事母题' },
  { value: 'angle', label: '取材角度' },
  { value: 'platform', label: '平台' },
  { value: 'duration_bucket', label: '时长分桶' },
];

const SIGNAL_LABEL = { gray: '样本不足·只看趋势', yellow: '趋势参考', ok: '可作依据' } as const;

function pct(value: number | null): string {
  return value === null ? '—' : `${String(value)}%`;
}

function rate(value: number | null): string {
  return value === null ? '—' : `${(value * 100).toFixed(2)}%`;
}

const columns = [
  { title: '维度值', dataIndex: 'value', key: 'value' },
  { title: '样本', dataIndex: 'n', key: 'n' },
  {
    title: '中位完播', key: 'ret',
    render: (_: unknown, row: PublishReportRow) => pct(row.median_retention_pct),
  },
  {
    title: '点赞率', key: 'like',
    render: (_: unknown, row: PublishReportRow) => rate(row.like_rate),
  },
  {
    title: '分享率', key: 'share',
    render: (_: unknown, row: PublishReportRow) => rate(row.share_rate),
  },
  {
    title: '信号', key: 'signal',
    render: (_: unknown, row: PublishReportRow) => (
      <Tag color={row.signal === 'gray' ? 'default' : row.signal === 'yellow' ? 'warning' : 'success'}>
        {SIGNAL_LABEL[row.signal]}
      </Tag>
    ),
  },
  {
    title: '离群点名', key: 'outliers',
    render: (_: unknown, row: PublishReportRow) =>
      row.outliers.length === 0 ? '—' : row.outliers.map((id) => id.slice(0, 8)).join('、'),
  },
];

/** 对照实验页（批二#6）：四态保守读数——方向性≠统计显著，本页只渲染服务端算好的事实。 */
function AbPairsPane({ ab, abError, abLoading }: {
  ab: AbReport | null; abError: string; abLoading: boolean;
}): ReactElement {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceSm }}>
      <div style={{ fontSize: tokens.text.meta.size, color: tokens.textTertiary }}>
        同项目同平台、发布日期差≤72h 成对；双方发布满72h 且播放≥500 才比较。
        {ab !== null && ab.unpaired > 0 ? ` 未成对 ${String(ab.unpaired)} 条（缺发布日期或无同组对照）。` : ''}
      </div>
      {abError !== '' && <Alert type="error" showIcon title={`对照读数加载失败：${abError}`} />}
      {abLoading ? <Spin /> : abError === '' && (ab === null || ab.pairs.length === 0) ? (
        <Empty description="暂无可对照的组——同剧同平台发两条以上并录入发布日期后开始读数" />
      ) : ab !== null ? (
        <Table
          size="small"
          rowKey={(row) => `${row.a}-${row.b}`}
          dataSource={ab.pairs}
          pagination={false}
          columns={[
            { title: '项目', dataIndex: 'project_name', key: 'project' },
            { title: '平台', dataIndex: 'platform', key: 'platform' },
            {
              title: '对照', key: 'pair',
              render: (_: unknown, row: AbPair) =>
                `${row.a.slice(0, 8)} ${String(row.retention_a)}% vs ${row.b.slice(0, 8)} ${String(row.retention_b)}%`,
            },
            {
              title: 'Δ完播', key: 'delta',
              render: (_: unknown, row: AbPair) =>
                `${row.delta_pp > 0 ? '+' : ''}${String(row.delta_pp)}pp`,
            },
            {
              title: '状态', key: 'state',
              render: (_: unknown, row: AbPair) => (
                <Tag color={row.state === '方向性领先' ? 'success' : row.state === '证据不足' ? 'warning' : 'default'}>
                  {row.state}
                </Tag>
              ),
            },
            { title: '说明', dataIndex: 'note', key: 'note' },
          ]}
        />
      ) : null}
    </div>
  );
}

export function PublishReportDrawer({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}): ReactElement {
  const [dimension, setDimension] = useState('mode');
  const [report, setReport] = useState<PublishReport | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [ab, setAb] = useState<AbReport | null>(null);
  const [abError, setAbError] = useState('');
  const [abLoading, setAbLoading] = useState(false);
  useEffect(() => {
    if (!open) return;
    let active = true;
    setAbLoading(true);
    setAbError('');
    setAb(null); // 先清旧对照：重开失败时不拿上次的配对冒充本次读数
    void exportApi
      .abReport()
      .then((result) => { if (active) setAb(result); })
      .catch((e: unknown) => { if (active) setAbError(errorText(e, '对照读数加载失败')); })
      .finally(() => { if (active) setAbLoading(false); });
    return () => { active = false; };
  }, [open]);
  useEffect(() => {
    if (!open) return;
    let active = true;
    setLoading(true);
    setError('');
    setReport(null); // 先清旧表：切换维度失败时不拿上一维度的数据冒充
    void exportApi
      .publishReport(dimension)
      .then((result) => { if (active) setReport(result); })
      .catch((e: unknown) => { if (active) setError(errorText(e, '报告加载失败')); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [open, dimension]);

  return (
    <Drawer title="数据报告" size={780} open={open} onClose={onClose}>
      <Tabs
        items={[{
          key: 'aggregate',
          label: '维度聚合',
          children: (
            <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceSm }}>
              <span style={{ display: 'flex', gap: tokens.spaceSm, alignItems: 'center' }}>
                <Select
                  size="small"
                  value={dimension}
                  onChange={setDimension}
                  options={DIMENSION_OPTIONS}
                  style={{ width: 140 }}
                />
                {report !== null && (
                  <span style={{ fontSize: tokens.text.meta.size, color: tokens.textTertiary }}>
                    已录 {report.recorded} 条{report.zero_plays_excluded > 0
                      ? `，剔除零播放 ${String(report.zero_plays_excluded)} 条` : ''}
                  </span>
                )}
              </span>
              {report !== null && (
                <Alert
                  type="info"
                  showIcon
                  title={`健康线：前3秒留存 ≥${String(report.health.line_3s)}% · 整体完播 ≥${String(report.health.line_retention)}%（${report.health.note}）`}
                  description={report.health.below.length > 0 ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceXs }}>
                      {report.health.below.map((item) => (
                        <div key={`${item.export_id}-${item.metric}`}>
                          {item.project_name}（{item.export_id.slice(0, 8)}）{item.metric === 'retention_3s' ? '前3秒' : '完播'} {item.value}%：{item.suggestion}
                        </div>
                      ))}
                    </div>
                  ) : undefined}
                />
              )}
              {error !== '' && <Alert type="error" showIcon title={`报告加载失败：${error}`} />}
              {loading ? <Spin /> : error === '' && (report === null || report.rows.length === 0) ? (
                <Empty description="暂无回流数据——在成片详情页「发布数据」录入后这里开始累积" />
              ) : report !== null ? (
                <Table
                  size="small"
                  rowKey="value"
                  columns={columns}
                  dataSource={report.rows}
                  pagination={false}
                />
              ) : null}
              <div style={{ fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary }}>
                分享率=分享数/播放量；视频号社交裂变权重最高（实测分享/点赞比 2.2~2.5）。灰标禁作调权依据，黄标仅趋势参考。
              </div>
            </div>
          ),
        },
        {
          key: 'ab',
          label: '对照实验',
          children: <AbPairsPane ab={ab} abError={abError} abLoading={abLoading} />,
        }]}
      />
    </Drawer>
  );
}
