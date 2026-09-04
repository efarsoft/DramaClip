/// <reference types="vite/client" />
import type { DramaClipBridge } from '@dramaclip/protocol';

declare global {
  interface Window {
    dramaclip: DramaClipBridge;
  }
}

export {};
