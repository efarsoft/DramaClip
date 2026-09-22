/** 云端配置分区：多配置列表（同域单启用）+ 新增/编辑/删除，动作见 useEngineConfigs。 */
import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons';
import type { ReactElement } from 'react';
import type { EngineConfig } from '@dramaclip/protocol';
import { tokens } from '../../styles/theme';
import { ConfigModal, type FormState } from './CloudConfigModal';
import { useEngineConfigs } from './useEngineConfigs';

const EMPTY_FORM: FormState = { name: '', base_url: '', api_key: '', model: '' };

export function CloudConfigSection({
  domain,
  onChanged,
}: {
  domain: string;
  onChanged?: () => void;
}): ReactElement {
  const actions = useEngineConfigs(domain, onChanged);
  const initial = actions.editing?.form ?? EMPTY_FORM;
  return (
    <div>
      {actions.configs.map((config) => (
        <ConfigRow
          key={config.id}
          config={config}
          onEnable={() => {
            actions.enable(config);
          }}
          onEdit={() => {
            actions.openEdit(config);
          }}
          onDelete={() => {
            actions.remove(config);
          }}
        />
      ))}
      <button type="button" onClick={actions.openAdd} style={ADD_BUTTON}>
        <PlusOutlined /> 添加配置
      </button>
      {(actions.adding || actions.editing !== null) && (
        <ConfigModal
          initial={initial}
          saving={actions.saving}
          onSave={actions.save}
          onClose={actions.close}
        />
      )}
    </div>
  );
}

function ConfigRow({
  config,
  onEnable,
  onEdit,
  onDelete,
}: {
  config: EngineConfig;
  onEnable: () => void;
  onEdit: () => void;
  onDelete: () => void;
}): ReactElement {
  const active = config.enabled === 1;
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: tokens.spaceMd,
        padding: '10px 14px',
        borderRadius: tokens.radiusControl,
        border: `1px solid ${active ? tokens.colorPrimary : tokens.borderSecondary}`,
        background: active ? tokens.accentSoft : tokens.bgLayout,
        marginBottom: tokens.spaceSm,
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: tokens.radiusDot,
          background: active ? tokens.colorSuccess : tokens.textTertiary,
          flexShrink: 0,
        }}
      />
      <span style={{ fontSize: tokens.text.meta.size, lineHeight: tokens.text.meta.leading, fontWeight: 600, color: tokens.textPrimary }}>
        {config.name}
      </span>
      <span style={{ fontSize: tokens.text.badge.size, lineHeight: tokens.text.badge.leading, color: tokens.textTertiary, flex: 1 }}>
        {config.model} · {config.base_url}
      </span>
      <RowAction
        text={active ? '使用中' : '启用'}
        color={active ? tokens.colorSuccess : tokens.textSecondary}
        onClick={onEnable}
      />
      <RowAction icon={<EditOutlined />} onClick={onEdit} />
      <RowAction icon={<DeleteOutlined />} onClick={onDelete} />
    </div>
  );
}

function RowAction({
  text,
  icon,
  color = tokens.textTertiary,
  onClick,
}: {
  text?: string;
  icon?: ReactElement;
  color?: string;
  onClick: () => void;
}): ReactElement {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        background: 'none',
        border: 'none',
        padding: 0,
        color,
        cursor: 'pointer',
        fontSize: tokens.text.badge.size,
        lineHeight: tokens.text.badge.leading,
        display: 'flex',
        alignItems: 'center',
      }}
    >
      {icon}
      {text}
    </button>
  );
}

const ADD_BUTTON: React.CSSProperties = {
  width: '100%',
  padding: '9px',
  borderRadius: tokens.radiusControl,
  border: `1px dashed ${tokens.border}`,
  background: 'none',
  color: tokens.textTertiary,
  cursor: 'pointer',
  fontSize: tokens.text.meta.size,
  lineHeight: tokens.text.meta.leading,
  marginTop: tokens.spaceSm,
};
