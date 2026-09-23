// @vitest-environment jsdom
/** ?focus= 段内导航：纯映射钉死认值范围，滚动效应打桩断言滚对了区段。 */
import { cleanup, render } from '@testing-library/react';
import type { ReactElement } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { focusSectionId, useFocusScroll } from '../useFocusScroll';

const scrolled: string[] = [];

function Probe(): ReactElement {
  const { planningRef, exportRef } = useFocusScroll();
  return (
    <div>
      <div ref={planningRef} data-testid="planning" />
      <div ref={exportRef} data-testid="export" />
    </div>
  );
}

function renderAt(search: string): void {
  render(
    <MemoryRouter initialEntries={[`/projects/p1/produce${search}`]}>
      <Routes>
        <Route path="/projects/:projectId/produce" element={<Probe />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeAll(() => {
  // jsdom 没有滚动实现：打桩记录「哪个区段被滚到」
  Element.prototype.scrollIntoView = function (this: Element) {
    scrolled.push((this as HTMLElement).dataset.testid ?? '');
  };
});

beforeEach(() => {
  scrolled.length = 0;
});

afterEach(() => {
  cleanup();
});

describe('focusSectionId 纯映射', () => {
  it('只认 planning/export；认不出的值沉默返回 null', () => {
    expect(focusSectionId('planning')).toBe('planning');
    expect(focusSectionId('export')).toBe('export');
    expect(focusSectionId('intake')).toBeNull();
    expect(focusSectionId('analysis')).toBeNull();
    expect(focusSectionId('')).toBeNull();
    expect(focusSectionId(null)).toBeNull();
  });
});

describe('useFocusScroll 滚动效应', () => {
  it('focus=export 滚到出片区', () => {
    renderAt('?focus=export');
    expect(scrolled).toEqual(['export']);
  });

  it('focus=planning 滚到规划区', () => {
    renderAt('?focus=planning');
    expect(scrolled).toEqual(['planning']);
  });

  it('没有 focus 或值认不出：不滚——缺席而非假动作', () => {
    renderAt('');
    expect(scrolled).toEqual([]);
    cleanup();
    renderAt('?focus=intake');
    expect(scrolled).toEqual([]);
  });
});
