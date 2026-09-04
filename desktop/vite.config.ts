import { fileURLToPath } from 'node:url';
import path from 'node:path';
import react from '@vitejs/plugin-react';
import electron from 'vite-plugin-electron';
import { defineConfig } from 'vite';

const rootDir = fileURLToPath(new URL('.', import.meta.url));

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    electron([
      {
        // 主进程入口（dev 下构建后自动拉起 Electron）
        entry: 'main/index.ts',
        vite: {
          build: {
            outDir: 'dist-electron/main',
            rollupOptions: { external: ['electron'] },
          },
        },
      },
      {
        entry: 'main/preload.ts',
        onstart: ({ reload }) => reload(),
        vite: {
          build: {
            outDir: 'dist-electron/preload',
            rollupOptions: { external: ['electron'] },
          },
        },
      },
    ]),
  ],
  resolve: {
    alias: { '@': path.resolve(rootDir, 'src') },
  },
  // 固定端口（docs/desktop/02 §2：消灭动态嗅探）
  server: { port: 5180, strictPort: true },
  build: { outDir: 'dist' },
});
