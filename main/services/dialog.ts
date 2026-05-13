/**
 * 原生对话框服务
 */

import { dialog, BrowserWindow } from 'electron';

export interface DialogResult<T> {
  success: boolean;
  data?: T;
  error?: string;
}

export class DialogService {
  static async openFile(options?: Electron.OpenDialogOptions): Promise<DialogResult<string[]>> {
    try {
      const result = await dialog.showOpenDialog({
        title: '选择视频文件',
        filters: [
          { name: '视频文件', extensions: ['mp4', 'mkv', 'avi', 'mov', 'wmv', 'flv', 'webm'] },
          { name: '所有文件', extensions: ['*'] },
        ],
        properties: ['openFile', 'multiSelections'],
        ...options,
      });

      if (result.canceled) {
        return { success: false, error: 'User canceled' };
      }

      return { success: true, data: result.filePaths };
    } catch (error) {
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error',
      };
    }
  }

  static async openFolder(options?: Electron.OpenDialogOptions): Promise<DialogResult<string>> {
    try {
      const result = await dialog.showOpenDialog({
        title: '选择文件夹',
        properties: ['openDirectory'],
        ...options,
      });

      if (result.canceled) {
        return { success: false, error: 'User canceled' };
      }

      return { success: true, data: result.filePaths[0] };
    } catch (error) {
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error',
      };
    }
  }

  static async saveFile(options?: Electron.SaveDialogOptions): Promise<DialogResult<string>> {
    try {
      const result = await dialog.showSaveDialog({
        title: '保存文件',
        filters: [
          { name: 'MP4 视频', extensions: ['mp4'] },
          { name: '所有文件', extensions: ['*'] },
        ],
        ...options,
      });

      if (result.canceled || !result.filePath) {
        return { success: false, error: 'User canceled' };
      }

      return { success: true, data: result.filePath };
    } catch (error) {
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error',
      };
    }
  }

  static async showMessage(
    options: Electron.MessageBoxOptions
  ): Promise<DialogResult<Electron.MessageBoxReturnValue>> {
    try {
      const mainWindow = BrowserWindow.getAllWindows()[0];
      const result = await dialog.showMessageBox(mainWindow!, options);
      return { success: true, data: result };
    } catch (error) {
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error',
      };
    }
  }
}
