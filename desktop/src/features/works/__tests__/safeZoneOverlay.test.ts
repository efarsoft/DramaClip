import { describe, expect, it } from 'vitest';
import type { SafeZoneMask } from '@dramaclip/protocol';
import { overlayRects } from '../safeZoneOverlay';

const mask: SafeZoneMask = {
  reference: [1080, 1920],
  top: 150 / 1920,
  right: 150 / 1080,
  bottom: 300 / 1920,
  note: '',
};

describe('overlayRects', () => {
  it('三条矩形按顶/右/底铺排，百分比与遮罩比例一致', () => {
    const rects = overlayRects(mask);
    expect(rects.map((r) => r.key)).toEqual(['top', 'right', 'bottom']);
    expect(rects[0]?.style).toEqual({ top: '0%', left: '0%', width: '100%', height: '7.81%' });
    expect(rects[1]?.style.left).toBe('86.11%');
    expect(rects[1]?.style.width).toBe('13.89%');
    expect(rects[2]?.style.top).toBe('84.38%');
    expect(rects[2]?.style.height).toBe('15.63%');
  });
});