/** 云端能力域的形态差异（组件文件之外的一处真相，供弹窗与配置段共用）。 */

/**
 * 该域是否由服务商 SDK 固定端点——接口地址在这里没有生效路径。
 * 口径与后端 engine_configs._DOMAIN_FIELDS 同一份：那边拒收，这边就不给填。
 */
export function usesSdkEndpoint(domain: string): boolean {
  return domain === 'asr_cloud' || domain === 'tts_cloud';
}
