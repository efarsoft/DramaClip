/** 配乐 BGM 域：ACE-Step 运行环境 + 模型资产 + 生成面板 + 曲库一览。

 与 ASR/TTS 域的分工差异：配乐没有「选为生效」——模型装好即可用，生成是显式
 动作（离线批量入库，导出选曲链零改动消费）；曲库清单来自 bgm_tracks 表（服务端
 已入库的事实），不是资产目录扫描。 */
import {
  PauseCircleOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { Button, Checkbox, Input, InputNumber, Select, Table, Tabs } from 'antd';
import type { ReactElement } from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';
import type {
  BgmEmotion,
  BgmLibrary,
  BgmRuntimeStatus,
  BgmTrackRow,
  ModelInfo,
} from '@dramaclip/protocol';
import { PageSection } from '../../components/layout/PageKit';
import { bgmApi, mediaUrl, musicRuntimeApi } from '../../services/client';
import { tokens } from '../../styles/theme';
import { DownloadSourceButton } from './ModelDownloadPopover';
import { StateBadge } from './AssetKit';
import type { DomainTabProps } from './EnginesPage';
import { assetState, reportFor } from './assetState';

const EMOTIONS: readonly { key: BgmEmotion; label: string }[] = [
  { key: 'default', label: '默认' },
  { key: 'anger', label: '愤怒' },
  { key: 'triumph', label: '胜利' },
  { key: 'suspense', label: '悬疑' },
  { key: 'sadness', label: '悲情' },
];

const errText = (exc: unknown): string => (exc instanceof Error ? exc.message : String(exc));

function useBgmPlayer(onStop: (message: string) => void): {
  playingPath: string | null;
  toggle: (path: string) => void;
} {
  const [playingPath, setPlayingPath] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const playingRef = useRef<string | null>(null);

  const stop = useCallback((): void => {
    if (audioRef.current !== null) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    playingRef.current = null;
    setPlayingPath(null);
  }, []);

  const toggle = useCallback(
    (path: string): void => {
      if (audioRef.current !== null && playingRef.current === path) {
        stop();
        return;
      }
      if (audioRef.current !== null) {
        audioRef.current.pause();
      }
      const element = new Audio(mediaUrl(path));
      // 身份守卫：切曲/暂停会让旧元素的 pending play() 以 AbortError 迟到失败——
      // 只有当前元素仍是活跃元素时才清理状态，否则孤儿化新曲/误报失败。
      const mine = (): boolean => audioRef.current === element;
      element.onended = () => {
        if (!mine()) return;
        audioRef.current = null;
        playingRef.current = null;
        setPlayingPath(null);
      };
      audioRef.current = element;
      playingRef.current = path;
      setPlayingPath(path);
      element.play().catch(() => {
        if (!mine()) return;
        audioRef.current = null;
        playingRef.current = null;
        setPlayingPath(null);
        onStop('试听播放失败（文件不可读或格式不支持）');
      });
    },
    [onStop, stop],
  );
  useEffect(() => stop, [stop]);
  return { playingPath, toggle };
}

export function MusicTab({ domain }: { domain: DomainTabProps }): ReactElement {
  const musicModels = domain.models.filter(
    (model) => model.kind === 'music' && model.cloud !== true,
  );
  const [notice, setNotice] = useState('');
  const refresh = useCallback(() => {
    bgmApi.runtimeStatus().then(setRuntime).catch(() => { setRuntime(null); });
    bgmApi.library().then(setLib).catch(() => { setLib(null); });
  }, []);
  const [runtime, setRuntime] = useState<BgmRuntimeStatus | null>(null);
  const [lib, setLib] = useState<BgmLibrary | null>(null);

  useEffect(() => {
    refresh();
  }, [refresh, domain.models]);

  return (
    <div style={{ display: 'grid', gap: tokens.spaceLg }}>
      <GeneratePanel
        runtime={runtime}
        notice={notice}
        setNotice={setNotice}
        onSubmitted={refresh}
      />
      <PageSection title="模型资产">
        <div style={{ display: 'grid', gap: tokens.spaceSm }}>
          {musicModels.map((model) => (
            <AssetRow
              key={model.model_id}
              model={model}
              reports={domain.reports}
              onChanged={domain.onChanged}
            />
          ))}
          {musicModels.length === 0 && <span style={{ color: tokens.textTertiary }}>清单为空</span>}
        </div>
      </PageSection>
      <LibraryCard lib={lib} setNotice={setNotice} onChanged={refresh} />
    </div>
  );
}

function GeneratePanel({
  runtime,
  notice,
  setNotice,
  onSubmitted,
}: {
  runtime: BgmRuntimeStatus | null;
  notice: string;
  setNotice: (text: string) => void;
  onSubmitted: () => void;
}): ReactElement {
  const [selected, setSelected] = useState<readonly BgmEmotion[]>(['default']);
  const [perEmotion, setPerEmotion] = useState<number>(1);
  const [duration, setDuration] = useState<120 | 180>(120);
  const [caption, setCaption] = useState('');
  const [busy, setBusy] = useState(false);

  const generate = async (): Promise<void> => {
    if (selected.length === 0) {
      setNotice('先勾选至少一种情绪');
      return;
    }
    setBusy(true);
    setNotice('');
    try {
      const trimmed = caption.trim();
      await bgmApi.generate({
        emotions: selected,
        per_emotion: perEmotion,
        duration_s: duration,
        caption: trimmed !== '' ? trimmed : undefined,
      });
      setNotice(
        `生成任务已提交（${String(selected.length)} 情绪 × ${String(perEmotion)} 首，`
        + `${String(duration)}s 档）——进度看日志面板，完成后曲库自动入库`,
      );
      onSubmitted();
    } catch (exc) {
      setNotice(`提交失败：${errText(exc)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <PageSection title="生成 BGM（ACE-Step 本地）">
      <div style={{ display: 'grid', gap: tokens.spaceMd, maxWidth: 720 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceMd, flexWrap: 'wrap' }}>
          <span style={{ fontSize: tokens.text.body.size }}>情绪</span>
          <Checkbox.Group
            options={EMOTIONS.map((e) => ({ label: e.label, value: e.key }))}
            value={[...selected]}
            onChange={(values) => { setSelected(values); }}
          />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceMd, flexWrap: 'wrap' }}>
          <span>每情绪</span>
          <InputNumber min={1} max={5} value={perEmotion} onChange={(v) => { setPerEmotion(Number(v) || 1); }} />
          <span>首 · 时长</span>
          <Select
            value={duration}
            style={{ width: 110 }}
            onChange={(v) => { setDuration(v); }}
            options={[
              { value: 120, label: '120 秒' },
              { value: 180, label: '180 秒' },
            ]}
          />
        </div>
        <Input
          placeholder="自定义风格描述（留空用情绪预设，如：雨夜霓虹下的爵士贝斯漫步）"
          value={caption}
          onChange={(e) => { setCaption(e.target.value); }}
        />
        <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceMd }}>
          <Button
            type="primary"
            icon={<ThunderboltOutlined />}
            loading={busy}
            onClick={() => {
              void generate();
            }}
          >
            生成入库
          </Button>
          {runtime === null ? (
            <span style={{ color: tokens.textTertiary }}>运行环境状态未知</span>
          ) : runtime.installed ? (
            <span style={{ color: tokens.colorSuccess }}>
              运行环境就绪（torch {runtime.torch_variant}）
            </span>
          ) : (
            <Button
              onClick={() => {
                void musicRuntimeApi.install()
                  .then(() => { setNotice('运行环境安装任务已提交——进度看日志面板'); })
                  .catch((exc: unknown) => { setNotice(`安装提交失败：${errText(exc)}`); });
              }}
            >
              安装运行环境（首次约 3-6GB）
            </Button>
          )}
        </div>
        {notice !== '' && (
          <div style={{ fontSize: tokens.text.meta.size, color: tokens.textSecondary }}>{notice}</div>
        )}
      </div>
    </PageSection>
  );
}

function LibraryCard({
  lib,
  setNotice,
  onChanged,
}: {
  lib: BgmLibrary | null;
  setNotice: (text: string) => void;
  onChanged: () => void;
}): ReactElement {
  const { playingPath, toggle } = useBgmPlayer(setNotice);
  const [filter, setFilter] = useState<string>('all');
  const rescan = async (): Promise<void> => {
    setNotice('');
    try {
      const result = await bgmApi.rescan();
      const skipped = result.skipped?.length ?? 0;
      setNotice(
        `重扫完成：入库 ${String(result.tracks)} 首`
        + (skipped > 0 ? `，跳过 ${String(skipped)} 首（看日志）` : ''),
      );
      onChanged();
    } catch (exc) {
      setNotice(`重扫失败：${errText(exc)}`);
    }
  };
  const tracks = [...(lib?.tracks ?? [])]
    .filter((t) => filter === 'all' || t.emotion === filter)
    .sort(
      (a, b) => a.emotion.localeCompare(b.emotion) || a.file_path.localeCompare(b.file_path),
    );
  return (
    <PageSection
      title="曲库"
      extra={
        <Button
          size="small"
          icon={<ReloadOutlined />}
          onClick={() => {
            void rescan();
          }}
        >
          重扫目录
        </Button>
      }
    >
      <Tabs
        size="small"
        activeKey={filter}
        onChange={setFilter}
        items={[
          { key: 'all', label: `全部（${String(lib?.tracks.length ?? 0)}）` },
          ...EMOTIONS.map((e) => {
            const group = lib?.groups.find((g) => g.emotion === e.key);
            return {
              key: e.key,
              label: `${e.label}（${String(group?.count ?? 0)}）`,
            };
          }),
        ]}
      />
      <Table
        size="small"
        rowKey="id"
        pagination={{ pageSize: 20, hideOnSinglePage: true }}
        dataSource={tracks.map((t) => ({ ...t }))}
        columns={[
          {
            title: '情绪',
            dataIndex: 'emotion',
            width: 90,
            render: (v: string) => EMOTIONS.find((e) => e.key === v)?.label ?? v,
          },
          {
            title: '曲目',
            dataIndex: 'file_path',
            render: (_: unknown, row: BgmTrackRow) =>
              row.file_path.replaceAll('\\', '/').split('/').pop(),
          },
          {
            title: '时长',
            dataIndex: 'duration_s',
            width: 90,
            render: (v: number) => `${String(Math.round(v))}s`,
          },
          {
            title: 'BPM',
            dataIndex: 'bpm',
            width: 80,
            render: (v: number | null) => (v == null ? '—' : String(v)),
          },
          {
            title: '来源',
            dataIndex: 'license',
            width: 150,
            render: (v: string, row: BgmTrackRow) =>
              row.license.includes('本地生成') ? 'ACE-Step 生成' : v || row.attribution || '手工投放',
          },
          {
            title: '',
            key: 'play',
            width: 70,
            render: (_: unknown, row: BgmTrackRow) => (
              <PlayButton
                path={row.file_path}
                active={playingPath === row.file_path}
                onToggle={toggle}
              />
            ),
          },
        ]}
      />
    </PageSection>
  );
}

function PlayButton({
  path,
  active,
  onToggle,
}: {
  path: string;
  active: boolean;
  onToggle: (path: string) => void;
}): ReactElement {
  return (
    <Button
      size="small"
      type={active ? 'primary' : 'default'}
      icon={active ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
      onClick={() => {
        onToggle(path);
      }}
    >
      {active ? '停止' : '试听'}
    </Button>
  );
}

function AssetRow({
  model,
  reports,
  onChanged,
}: {
  model: ModelInfo;
  reports: DomainTabProps['reports'];
  onChanged: () => void;
}): ReactElement {
  const state = assetState(model, reportFor(reports, model.model_id));
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(0,1fr) auto auto',
        gap: tokens.spaceMd,
        alignItems: 'center',
        padding: `${tokens.spaceSm} ${tokens.spaceMd}`,
        border: `1px solid ${tokens.borderSecondary}`,
        borderRadius: tokens.radiusControl,
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div style={{ fontWeight: tokens.text.body.weightActive }}>{model.name}</div>
        <div style={{ fontSize: tokens.text.meta.size, color: tokens.textSecondary }}>
          {model.size_label} · {model.notes ?? model.desc}
        </div>
      </div>
      <StateBadge state={state} />
      <DownloadSourceButton model={model} onChanged={onChanged} />
    </div>
  );
}
