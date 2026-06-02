import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import electron from 'vite-plugin-electron';
import renderer from 'vite-plugin-electron-renderer';
import path from 'path';

export default defineConfig(({ command, mode }) => {
  // dev:full 模式下由 dev-electron.js 负责启动 Electron，vite 插件不要自动 startup
  const isFullDev = mode === 'development' && process.env.DEV_ELECTRON_MANUAL === '1';

  return {
    plugins: [
      react(),
      electron([
        {
          // Main process entry
          entry: 'main/app.ts',
          onstart(options) {
            if (!isFullDev) {
              options.startup();
            }
          },
          vite: {
            build: {
              outDir: 'dist-electron/main',
              rollupOptions: {
                external: ['electron'],
              },
            },
          },
        },
        {
          // Preload script entry
          entry: 'main/preload.ts',
          onstart(options) {
            options.reload();
          },
          vite: {
            build: {
              outDir: 'dist-electron/preload',
              rollupOptions: {
                external: ['electron'],
              },
            },
          },
        },
      ]),
      renderer(),
    ],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
        '@main': path.resolve(__dirname, './main'),
      },
    },
    build: {
      outDir: 'dist',
      emptyOutDir: true,
    },
  };
});
