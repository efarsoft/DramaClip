import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    // 网络类测试文件头部用 `// @vitest-environment node` 切换
    include: ['src/**/*.test.{ts,tsx}', 'main/**/*.test.ts'],
    /** 限到 4 是实测值：默认并发（≈核数−1）会让每个文件第一个重渲染用例越过
     *  `testTimeout=5000`（16 核机器上 6 次全量 4 次红）；`isolate` 必须留 true——
     *  `--no-isolate` 省 43s，但换来 6 条跨文件 store 残留红。 */
    maxWorkers: 4,
  },
});
