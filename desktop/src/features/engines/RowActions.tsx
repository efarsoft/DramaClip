/** 资产行动作：未装给下载，已装才谈「选为生效」，体检/定位/删除只在已落盘后出现。 */
import { App as AntdApp, Button, Popconfirm } from 'antd';
import { DeleteOutlined, FolderOpenOutlined } from '@ant-design/icons';
import type { ReactElement } from 'react';
import type { ModelInfo, VerifyReport } from '@dramaclip/protocol';
import { modelsApi, revealInFolder } from '../../services/client';
import { tokens } from '../../styles/theme';
import { type AssetState, canActivate, stateLabel } from './assetState';
import { DownloadSourceButton } from './ModelDownloadPopover';

export function RowActions({
  model,
  state,
  report,
  detail,
  onToggleDetail,
  onActivate,
  onChanged,
  onVerify,
}: {
  model: ModelInfo;
  state: AssetState;
  report: VerifyReport | undefined;
  detail: boolean;
  onToggleDetail: () => void;
  onActivate: (model: ModelInfo) => void;
  onChanged: () => void;
  onVerify: (modelId: string) => void;
}): ReactElement {
  const installed = model.status === 'installed';
  return (
    <span style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm, justifyContent: 'flex-end' }}>
      {!installed && <DownloadSourceButton model={model} onChanged={onChanged} />}
      {installed && model.engine_ready && (
        <ActivateButton model={model} state={state} report={report} onActivate={onActivate} />
      )}
      {installed && (
        <InstalledActions
          model={model}
          detail={detail}
          onToggleDetail={onToggleDetail}
          onChanged={onChanged}
          onVerify={onVerify}
        />
      )}
    </span>
  );
}

function ActivateButton({
  model,
  state,
  report,
  onActivate,
}: {
  model: ModelInfo;
  state: AssetState;
  report: VerifyReport | undefined;
  onActivate: (model: ModelInfo) => void;
}): ReactElement {
  const ready = canActivate(model, report);
  return (
    <Button
      size="small"
      type={ready ? 'primary' : 'text'}
      disabled={!ready}
      title={ready ? undefined : `${stateLabel(state)}：补齐资产后才能生效`}
      onClick={() => {
        onActivate(model);
      }}
    >
      选为生效
    </Button>
  );
}

function InstalledActions({
  model,
  detail,
  onToggleDetail,
  onChanged,
  onVerify,
}: {
  model: ModelInfo;
  detail: boolean;
  onToggleDetail: () => void;
  onChanged: () => void;
  onVerify: (modelId: string) => void;
}): ReactElement {
  const { message } = AntdApp.useApp();
  return (
    <>
      <Button
        size="small"
        type="text"
        onClick={() => {
          onToggleDetail();
          if (!detail) onVerify(model.model_id);
        }}
      >
        {detail ? '收起' : '体检'}
      </Button>
      {model.path !== undefined && (
        <Button
          size="small"
          type="text"
          icon={<FolderOpenOutlined />}
          onClick={() => {
            void revealInFolder(model.path ?? '');
          }}
        />
      )}
      <Popconfirm
        title="删除模型"
        description="删除后可随时重新下载。"
        okText="删除"
        cancelText="取消"
        onConfirm={() => {
          modelsApi
            .remove(model.model_id)
            .then(onChanged)
            .catch(() => {
              message.error('删除失败');
            });
        }}
      >
        <Button size="small" danger icon={<DeleteOutlined />} />
      </Popconfirm>
    </>
  );
}
