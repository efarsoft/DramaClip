/** 开源组件清单（分发含第三方二进制与字体，许可清单是发版应有项——规格 §7.2）。
 *  单列成模块是为了让门禁能直接断言它，而不是去渲染整页（关于页要打通服务握手）。 */
export const OPEN_SOURCE: readonly string[] = [
  'Electron',
  'React',
  'Ant Design',
  'FFmpeg',
  'PySceneDetect',
  'OpenCV',
  'faster-whisper',
  'edge-tts',
  'Kokoro',
  // 两款界面字面随包分发，SIL OFL 1.1 要求许可文本随包——文本在 desktop/src/assets/fonts/OFL-*.txt
  'Inter（SIL OFL 1.1）',
  'Noto Sans SC 思源黑体（SIL OFL 1.1）',
];
