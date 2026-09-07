/** preload：contextBridge 暴露 window.dramaclip（渲染层唯一入口，docs/desktop/00 §3）。 */
import { contextBridge, ipcRenderer, type IpcRendererEvent } from 'electron';
import type { DramaClipBridge, ServiceEvent } from '@dramaclip/protocol';

const api = {
  rpc: (method: string, params: Record<string, unknown> = {}): Promise<unknown> =>
    ipcRenderer.invoke('rpc', method, params),
  appVersion: (): Promise<string> => ipcRenderer.invoke('app:version') as Promise<string>,
  restartService: (): Promise<void> => ipcRenderer.invoke('service:restart') as Promise<void>,
  pickFolder: (): Promise<string | null> =>
    ipcRenderer.invoke('dialog:pickFolder') as Promise<string | null>,
  pickVideoFile: (): Promise<string | null> =>
    ipcRenderer.invoke('dialog:pickVideoFile') as Promise<string | null>,
  revealInFolder: (path: string): Promise<void> =>
    ipcRenderer.invoke('shell:reveal', path) as Promise<void>,
  windowControl: (action: 'minimize' | 'maximize-toggle' | 'close'): Promise<void> =>
    ipcRenderer.invoke('window:control', action) as Promise<void>,
  onServiceEvent: (callback: (event: ServiceEvent) => void): (() => void) => {
    const listener = (_event: IpcRendererEvent, payload: ServiceEvent): void => {
      callback(payload);
    };
    ipcRenderer.on('service:event', listener);
    return () => ipcRenderer.removeListener('service:event', listener);
  },
} as const satisfies DramaClipBridge;

contextBridge.exposeInMainWorld('dramaclip', api);
