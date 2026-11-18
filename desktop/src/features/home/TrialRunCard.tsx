/** 零配置试跑卡（2026-11-18 立项）：有项目没出过片时，右栏给一条「10 分钟出
 * 第一片」的免文案快捷路径——纯原片剪辑模式全链不触 LLM，编排见 useTrialRun。
 */
import { Button, Card, Progress } from 'antd';
import type { ReactElement } from 'react';
import { useNavigate } from 'react-router-dom';
import { tokens } from '../../styles/theme';
import { useTrialRun } from './useTrialRun';

const COPY = {
  title: '试跑一条（免文案模式）',
  desc: '用第一集素材、纯原片剪辑模式出一条成片——不需要配置文案引擎。首次会先做单集分析；分析约 3-8 分钟、出片约 2-4 分钟（视机器性能）。出片后可到「作品」页查看；配好文案 LLM 可解锁解说模式。',
  idleCta: '开始试跑',
  noMaterial: '这个项目还没有导入素材——先到项目里导入再试跑。',
};

/** 过程态的一行进度（阶段名 + 进度条 + 阶段消息）。 */
function PhaseLine({ label, percent, message }: { label: string; percent: number; message: string }): ReactElement {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceXs }}>
      <span style={{ fontSize: tokens.text.badge.size, color: tokens.textSecondary }}>
        {label}
        {message !== '' ? ` · ${message}` : ''}
      </span>
      <Progress percent={Math.min(100, Math.max(0, percent))} size="small" status="active" />
    </div>
  );
}

export function TrialRunCard({ projectId, projectName }: { projectId: string; projectName: string }): ReactElement {
  const { phase, start, reset } = useTrialRun(projectId);
  const navigate = useNavigate();

  return (
    <Card title={COPY.title} size="small">
      <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spaceMd }}>
        {phase.kind === 'idle' && (
          <>
            <span style={{ fontSize: tokens.text.body.size, color: tokens.textSecondary, whiteSpace: 'pre-line' }}>
              {COPY.desc}
            </span>
            <div>
              <Button type="primary" onClick={() => void start()}>
                {COPY.idleCta}
              </Button>
            </div>
          </>
        )}
        {phase.kind === 'checking' && <PhaseLine label="检查素材" percent={100} message="" />}
        {phase.kind === 'analyzing' && (
          <PhaseLine label="① 单集分析" percent={phase.percent} message={phase.message} />
        )}
        {phase.kind === 'planning' && (
          <PhaseLine label="② 挑选高冲突片段" percent={phase.percent} message={phase.message} />
        )}
        {phase.kind === 'exporting' && (
          <PhaseLine label="③ 合成出片" percent={phase.percent} message={phase.message} />
        )}
        {phase.kind === 'no-material' && (
          <>
            <span style={{ fontSize: tokens.text.body.size, color: tokens.textSecondary }}>{COPY.noMaterial}</span>
            <div>
              <Button onClick={() => void navigate('/')}>去导入素材</Button>
            </div>
          </>
        )}
        {phase.kind === 'done' && (
          <>
            <span style={{ fontSize: tokens.text.body.size, color: tokens.colorSuccess }}>
              第一条成片已出——《{projectName}》已可在作品页查看。
            </span>
            <div style={{ display: 'flex', gap: tokens.spaceMd }}>
              <Button type="primary" onClick={() => void navigate('/works')}>
                查看作品
              </Button>
              <Button
                onClick={() => {
                  reset();
                }}
              >
                再试一条
              </Button>
            </div>
          </>
        )}
        {phase.kind === 'failed' && (
          <>
            <span style={{ fontSize: tokens.text.body.size, color: tokens.colorError }}>
              {phase.stage === 'analysis'
                ? '分析失败'
                : phase.stage === 'planning'
                  ? '挑选片段失败'
                  : '出片失败'}
              ：{phase.reason}
            </span>
            <div style={{ display: 'flex', gap: tokens.spaceMd }}>
              <Button type="primary" onClick={() => void start()}>
                重试（已完成阶段自动跳过）
              </Button>
              <Button
                onClick={() => {
                  reset();
                }}
              >
                收起
              </Button>
            </div>
          </>
        )}
      </div>
    </Card>
  );
}
