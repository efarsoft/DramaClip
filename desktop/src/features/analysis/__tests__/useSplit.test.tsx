// @vitest-environment jsdom
/** 分栏拖拽落盘时机：localStorage 同步 IO 不跟手——mousemove 只动状态，mouseup 落一次账。 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { useSplitDrag } from '../useSplit';

const KEY = 'dramaclip.split-pct';

function Harness(): React.ReactElement {
  const { pct, containerRef, onHandleDown } = useSplitDrag();
  return (
    <div ref={containerRef} data-testid="container" style={{ width: 500, height: 100 }}>
      <div data-testid="handle" onPointerDown={onHandleDown} />
      <span data-testid="pct">{String(pct)}</span>
    </div>
  );
}

/** jsdom 没有布局引擎：把容器矩形钉死成 500 宽（20%~40% 夹在 100~200px）。 */
function pinRect(container: HTMLElement): void {
  Object.defineProperty(container, 'getBoundingClientRect', {
    value: () => ({ left: 0, width: 500, top: 0, height: 100 }),
    configurable: true,
  });
}

afterEach(() => {
  window.localStorage.removeItem(KEY);
  cleanup();
});

describe('useSplitDrag 落盘时机', () => {
  it('mousemove 期间零落盘，mouseup 落一次最终值', () => {
    render(<Harness />);
    pinRect(screen.getByTestId('container'));
    fireEvent.pointerDown(screen.getByTestId('handle'));

    // 三次拖动：状态跟手（最后一次进 pct），存储里一次账都没有
    for (const x of [100, 150, 200]) {
      fireEvent.mouseMove(window, { clientX: x });
    }
    expect(screen.getByTestId('pct').textContent).toBe('40');
    expect(window.localStorage.getItem(KEY)).toBeNull();

    fireEvent.mouseUp(window);
    expect(window.localStorage.getItem(KEY)).toBe('40');
    expect(screen.getByTestId('pct').textContent).toBe('40');
  });

  it('鼠标未按下时 mousemove 不动状态也不落盘', () => {
    render(<Harness />);
    pinRect(screen.getByTestId('container'));
    fireEvent.mouseMove(window, { clientX: 400 });
    expect(window.localStorage.getItem(KEY)).toBeNull();
    expect(screen.getByTestId('pct').textContent).toBe('24');
  });
});
