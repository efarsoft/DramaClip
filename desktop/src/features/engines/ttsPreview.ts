/** 试听放行判断：只挡「点了必然听不到所选声音」的几种确定情况。
 *
 *  这里刻意不做「资产是否就绪」的判断——那是 models.verify 的活儿，服务端合成时才见
 *  分晓；在按钮上猜就绪等于把 P1 缺陷又写回来一遍。
 */
import type { AssetState } from './assetState';

export function previewNotice(input: {
  engine: string;
  voice: string;
  /** 所选资产的体检/落盘态；云端引擎没有本地资产，传 null。 */
  state: AssetState | null;
}): string | undefined {
  if (input.engine === '') return '先选引擎再试听';
  if (input.voice === '') return '先选音色再试听';
  if (input.state === 'reserve') return '该引擎未接入，还不能出声';
  if (input.state === 'missing') return '模型未下载，先下载后再试听';
  return undefined;
}
