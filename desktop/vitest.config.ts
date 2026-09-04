import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    // 网络类测试文件头部用 `// @vitest-environment node` 切换
    include: ['src/**/*.test.{ts,tsx}', 'main/**/*.test.ts'],
  },
});
