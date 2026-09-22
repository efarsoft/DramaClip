/** 资产行动作：未装给下载，已装才谈试听与「选为生效」，体检/定位/删除只在已落盘后出现。
 *  删除的提示按来源说清会动到哪一份——本地导入的那一份与仅登记的那一份，代价不是一回事。
 *  异常态自带修法（§10.2）：修复动作按体检判据出现，摆在动作区最前——先修再谈别的。 */
import { App as AntdApp, Button, Popconfirm } from 'antd';
import { DeleteOutlined, FolderOpenOutlined } from '@ant-design/icons';
import type { ReactElement } from 'react';
import type { ModelInfo, SelftestResult, VerifyReport } from '@dramaclip/protocol';
import { modelsApi, revealInFolder } from '../../services/client';
import { tokens } from '../../styles/theme';
import { type AssetState, canActivate, deleteNote, stateLabel } from './assetState';
import { DownloadSourceButton } from './ModelDownloadPopover';
import { RepairActions } from './RepairActions';

export function RowActions({
  model,
  state,
  report,
  selftest,
  detail,
  onToggleDetail,
  onActivate,
  onChanged,
  onVerify,
  preview,
}: {
  model: ModelInfo;
  state: AssetState;
  report: VerifyReport | undefined;
  selftest: SelftestResult | undefined;
  detail: boolean;
  onToggleDetail: () => void;
  onActivate: (model: ModelInfo) => void;
  onChanged: () => void;
  onVerify: (modelId: string) => void;
  preview?: ReactElement;
}): ReactElement {
  const installed = model.status === 'installed';
  const wired = installed && model.engine_ready;
  return (
    <span style={{ display: 'flex', alignItems: 'center', gap: tokens.spaceSm, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
      <RepairActions model={model} report={report} selftest={selftest} onChanged={onChanged} onVerify={onVerify} />
      {!installed && <DownloadSourceButton model={model} onChanged={onChanged} />}
      {wired && preview}
      {wired && <ActivateButton model={model} state={state} report={report} onActivate={onActivate} />}
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
          aria-label="定位所在目录"
          icon={<FolderOpenOutlined />}
          onClick={() => {
            void revealInFolder(model.path ?? '');
          }}
        />
      )}
      <Popconfirm
        title="删除模型"
        description={deleteNote(model)}
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
        <Button size="small" danger aria-label="删除这一份" icon={<DeleteOutlined />} />
      </Popconfirm>
    </>
  );
}
