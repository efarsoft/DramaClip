/** 原生对话框（docs/desktop/00 §7）。取消返回 null，与"失败"区分。 */
import { dialog, type BaseWindow } from 'electron';

const VIDEO_FILTERS = [
  { name: '视频文件', extensions: ['mp4', 'mov', 'avi', 'mkv', 'wmv', 'webm', 'flv'] },
  { name: '全部文件', extensions: ['*'] },
];

const AUDIO_FILTERS = [
  { name: '音频文件', extensions: ['wav', 'mp3', 'flac', 'ogg', 'm4a'] },
  { name: '全部文件', extensions: ['*'] },
];

export function pickAudioFile(window: BaseWindow | null): Promise<string | null> {
  const options = { properties: ['openFile' as const], filters: AUDIO_FILTERS };
  const result = window === null ? dialog.showOpenDialogSync(options) : dialog.showOpenDialogSync(window, options);
  return Promise.resolve(result?.[0] ?? null);
}

export function pickFolder(window: BaseWindow | null): Promise<string | null> {
  const result =
    window === null
      ? dialog.showOpenDialogSync({ properties: ['openDirectory'] })
      : dialog.showOpenDialogSync(window, { properties: ['openDirectory'] });
  return Promise.resolve(result?.[0] ?? null);
}

export function pickVideoFile(window: BaseWindow | null): Promise<string | null> {
  const options = { properties: ['openFile' as const], filters: VIDEO_FILTERS };
  const result = window === null ? dialog.showOpenDialogSync(options) : dialog.showOpenDialogSync(window, options);
  return Promise.resolve(result?.[0] ?? null);
}
