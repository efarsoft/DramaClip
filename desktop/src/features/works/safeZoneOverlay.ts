/** 安全区叠层几何：遮罩比例 → 三条百分比矩形（纯函数，单测钉形状）。 */
import type { SafeZoneMask } from '@dramaclip/protocol';

export interface OverlayRect {
  readonly key: 'top' | 'right' | 'bottom';
  readonly label: string;
  readonly style: {
    readonly top: string;
    readonly left: string;
    readonly width: string;
    readonly height: string;
  };
}

const pct = (value: number): string => `${(value * 100).toFixed(2)}%`;

export function overlayRects(mask: SafeZoneMask): OverlayRect[] {
  return [
    { key: 'top', label: '顶栏', style: { top: '0%', left: '0%', width: '100%', height: pct(mask.top) } },
    {
      key: 'right',
      label: '互动区',
      style: {
        top: pct(mask.top),
        left: pct(1 - mask.right),
        width: pct(mask.right),
        height: pct(1 - mask.top - mask.bottom),
      },
    },
    {
      key: 'bottom',
      label: '底部信息区',
      style: { top: pct(1 - mask.bottom), left: '0%', width: '100%', height: pct(mask.bottom) },
    },
  ];
}