import { theme as antdTheme, type ThemeConfig } from 'antd';

/**
 * 设计系统 DSS v1 唯一真相源（docs/desktop/04-设计系统方案.md）。
 * 组件禁止裸写 fontSize / borderRadius / 间距数值——一律引用本 token。
 */

/** 间距基础值：antd 组件 token 只收 number，px 字符串 token 由此派生（单一真相源）。 */
const SPACING = { xs: 4, sm: 8, md: 12, lg: 16, xl: 20, xxl: 24, xxxl: 32, xxxxl: 64 } as const;

export const tokens = {
  // ---- 色彩 ----
  colorPrimary: '#7C9CFF',
  colorPrimaryHover: '#93AEFF',
  colorPrimaryActive: '#6A8AE8',
  colorAccent: '#9B7BFF',
  colorSuccess: '#34D399',
  colorWarning: '#FBBF24',
  colorError: '#F87171',
  colorInfo: '#60A5FA',
  colorWhite: '#FFFFFF',
  bgSidebar: '#0A0F1E',
  bgLayout: '#0F1526',
  bgContainer: '#161E33',
  bgElevated: '#1C2540',
  bgInput: '#131A2E',
  border: '#2A3550',
  borderSecondary: '#1F2942',
  accentSoft: 'rgba(124,156,255,0.12)',
  /** 已勾选行底（§3.2 唯一铺底语义）：比 accentSoft 更浅一档，不与悬停、当前查看抢通道。 */
  checkedSoft: 'rgba(124,156,255,0.07)',
  /** 状态色软底（§3.4）：原先 1A/44/0d/55/12 五种模板拼色表达的是同一件语义。
   * 半透明档只管铺色；框线一律读 border——用同档 Soft 描边等于描了条看不见的边。 */
  successSoft: 'rgba(52,211,153,0.12)',
  warningSoft: 'rgba(251,191,36,0.12)',
  errorSoft: 'rgba(248,113,113,0.12)',
  /** 关闭按钮热区：非重复色，收进此处后组件里不再出现裸 hex。 */
  closeHot: '#C43A3A',
  /** 海报/视频的黑底与底部渐隐（原先在四个文件里逐字重复）。 */
  posterBase: '#000000',
  posterScrim: 'linear-gradient(180deg, rgba(0,0,0,0) 50%, rgba(0,0,0,0.68) 100%)',
  posterCaption: 'rgba(0,0,0,0.72)',
  /** 压在海报上的浮板（集数芯片、更多按钮）：原先 0.55 / 0.45 两档表达同一件语义。 */
  posterPlate: 'rgba(0,0,0,0.55)',
  gradientAccent: 'linear-gradient(135deg, #6D9BFF 0%, #9B7BFF 100%)',
  textPrimary: '#F0F4FF',
  textSecondary: '#A8B4CE',
  textTertiary: '#5E6C8C',
  /** 界面字面栈（§7.1）：随包 Inter + 思源子集打头，系统字面只作兜底。
   *  思源用自别名 'DramaClip SC' 而非本名：随包的是「简体子集、无西文」，
   *  占用本名会把使用者机器上完整版的 Noto Sans SC 顶掉，反而不可复核。 */
  fontFamilyUi: "'Inter', 'DramaClip SC', 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif",
  fontFamilyMono: "'JetBrains Mono', 'Cascadia Mono', Consolas, monospace",
  // ---- CSS 侧氛围与控件色（§7.1：global.css 不得藏第二处色值真相，全部在此登记） ----
  scrollThumb: '#262F47',
  scrollThumbHover: '#3D4D73',
  selectionBg: 'rgba(124,156,255,0.28)',
  /** 背景双辐射光斑：左上主靛 5% / 右下紫 3.8%，克制到近乎看不出来才叫氛围层。 */
  ambientPrimary: 'rgba(124,156,255,0.05)',
  ambientAccent: 'rgba(155,123,255,0.038)',
  cardTopHighlight: 'rgba(255,255,255,0.045)',
  shadowHover: '0 6px 18px rgba(0,0,0,0.35)',
  shadowPrimary: '0 2px 8px rgba(124,156,255,0.28)',
  /** 主按钮渐变 = 主色→强调色；与 gradientAccent（#6D9BFF 起）不是同一枚，别合并。 */
  gradientPrimary: 'linear-gradient(135deg, #7C9CFF 0%, #9B7BFF 100%)',

  // ---- 间距（px 字符串，模板插值安全） ----
  spaceXs: `${String(SPACING.xs)}px`,
  spaceSm: `${String(SPACING.sm)}px`,
  spaceMd: `${String(SPACING.md)}px`,
  spaceLg: `${String(SPACING.lg)}px`,
  spaceXl: `${String(SPACING.xl)}px`,
  space2xl: `${String(SPACING.xxl)}px`,
  space3xl: `${String(SPACING.xxxl)}px`,
  space4xl: `${String(SPACING.xxxxl)}px`,

  // ---- 字阶（§1.1 六档：字号与行高成对写进同一个 token，配错对不成形状） ----
  // weight 给中文标题（思源 500），weightLatin 给西文与数字（Inter 600）——
  // 同一数值下两款字面观感不等重，写死一个数会让标题一半重一半轻（§1.2 ③）。
  text: {
    pageTitle: { size: '28px', leading: '36px', weight: 500, weightLatin: 600 },
    sectionTitle: { size: '20px', leading: '28px', weight: 600, weightLatin: 600 },
    cardTitle: { size: '16px', leading: '24px', weight: 600, weightLatin: 600 },
    // weightActive 给 §3.2 的「当前查看」通道：名称用主色并 600，与 badge 的选中档同源。
    body: { size: '14px', leading: '22px', weight: 400, weightLatin: 400, weightActive: 600 },
    meta: { size: '13px', leading: '18px', weight: 400, weightLatin: 400 },
    badge: { size: '11px', leading: '14px', weight: 400, weightLatin: 400, weightActive: 600 },
  },

  // ---- 图形尺寸（§1.3：图标与内容尺寸不占字号命名空间） ----
  // brandSm/brandMd 各自跟随容器（22×22 与 40×40），按容器缩放是设计不是漂移；
  // poster 一枚收掉原先 13/20/28/34 四种占位标记尺寸。
  glyph: {
    icon: '10px',
    /** 控件内图标（搜索框放大镜、告警三角）——今天真实在用的第二档图标尺寸。 */
    iconMd: '14px',
    railIcon: '20px',
    chipIcon: '17px',
    poster: '28px',
    empty: '48px',
    brandSm: '10px',
    brandMd: '22px',
    /** 关于页品牌容器边长：容器与内部符号同为图形尺寸。 */
    brandBox: '40px',
    thumbW: '34px',
    thumbH: '46px',
  },

  // ---- 圆角 / 层级 ----
  radiusCard: 14,
  radiusControl: 10,
  radiusChip: 999,
  radiusThumb: 6,
  radiusDot: 3,         // 圆点/竖条装饰
  shadowPop: '0 12px 32px rgba(0,0,0,0.45)',
  shadowCard: '0 6px 20px rgba(4,8,20,0.35)',
  /** 吸底操作栏：与 shadowCard 同色同一档，只是投影朝上（组件里不得再手写这串）。 */
  shadowSticky: '0 -6px 18px rgba(4,8,20,0.35)',
} as const;

/**
 * 语义化布局度量（规格 §2）：唯一真相源，且必须真的被引用。
 * 高度/宽度按现状逐值登记（它们不是间距，不受阶梯约束）；
 * 间距只准落 4/8/12/16/20/24/32/64 阶梯——原先两处脱阶的 14 收进 spaceLg。
 */
export const layout = {
  /** 内容页满宽（§2：1080 居中从未实现过，注释删掉，不留第二处真相）。 */
  page: { paddingBlock: tokens.space2xl, gap: tokens.space2xl },
  fullbleed: { paddingBlock: tokens.spaceXl, gap: tokens.spaceXl },
  /** 中密度对冲：字号升档后卡内留白从 16 收到 12，气靠行高给。 */
  card: { padding: tokens.spaceMd },
  listSection: { padding: 0, rowPadding: tokens.spaceMd },
  /** 列表行高派生自字阶（body 22 + 上下留白），不再由内容撑。 */
  row: { single: 36, double: 52, moveButton: { width: 18, height: 13 } },
  field: { labelWidth: 250, controlWidth: 320, labelPaddingTop: 6, helpMarginTop: 3 },
  controlHeight: { sm: 28, md: 32 },
  rail: {
    width: 68,
    button: { width: 54, height: 52 },
    divider: { width: 40 },
  },
  titleBar: {
    height: 46,
    paddingX: tokens.spaceLg,
    brand: 22,
    windowButton: { width: 44 },
    /** 搜索框：clearance 是给放大镜与角标让位的宽度，不是间距档位，故逐值登记。 */
    search: { width: 340, clearanceLeft: 28, clearanceRight: 44, iconInset: tokens.spaceSm, resultsOffset: 32 },
  },
  statusBar: { height: 26, paddingX: tokens.spaceLg },
  footer: { height: 46, paddingX: tokens.spaceLg },
  sectionBar: { width: 3, height: 13 },
  /** 芯片内边距：纵向 2px 不在阶梯上，本批只搬进唯一真相源，不改值。 */
  chip: { paddingBlock: 2, paddingInline: tokens.spaceSm },
  /** 海报角标与自检徽章芯片的 '1px 6px' 内边距：脱阶值按 §8.3 登记成具名值，不留在组件里。 */
  posterChip: { paddingBlock: 1, paddingInline: 6 },
  /** 紧凑卡身 '10px 14px' 内边距（StyleSelectCard 等小卡）：脱阶值照实登记，不新造一档。 */
  cardBodyCompact: { paddingBlock: 10, paddingInline: 14 },
  /** CurveCard 卡身 '10px 14px 6px'：底部收紧贴图表，脱阶值照实登记。 */
  cardBodyCurve: { paddingBlock: 10, paddingInline: 14, paddingBottom: 6 },
  /** StepsNav 步骤点与连接线的间距：7/10 不在阶梯上，照实登记（§8.3）。 */
  stepNav: { dotGap: 7, connectorGap: 10 },
  /** 行内编辑输入框 '3px 8px' 内边距：3 脱阶照实登记。 */
  inlineInput: { paddingBlock: 3, paddingInline: tokens.spaceSm },
  /** 图标/角标对齐的 2px 微推（首启三步）：脱阶照实登记，不新造一档。 */
  iconNudge: 2,
  /** 来源徽标/无音轨一类迷你芯片 '0 6px' 内边距：6 脱阶照实登记。 */
  badgeChip: { paddingBlock: 0, paddingInline: 6 },
  /** EnvPanel/TipsPanel 度量债偿还（全局改造批）：六处脱阶值照实登记，不新造一档。 */
  envPanel: {
    itemPaddingBlock: 9,
    actionGap: 2,
    tipPaddingBlock: 7,
    tipIconMarginTop: 1,
    bodyPaddingTop: 6,
    bodyPaddingInline: 16,
    bodyPaddingBottom: 10,
    titlePaddingTop: 10,
    titlePaddingBottom: 4,
  },
  /** mono 小字与相邻正文的顶对齐微调（原 WorksDetailPage 的 paddingTop:2）。 */
  monoAlignTop: 2,
  /** 主从编辑器左栏：五值原样搬入，只消灭散落在三处的同源数（§2）。 */
  split: { initial: 24, min: 20, max: 40, minWidth: 250, handle: 6, paddingX: tokens.spaceLg },
} as const;

/**
 * global.css 用的 CSS 自定义属性（§7.1）。
 * 值一律直接取自 tokens——`cssContract` 门禁逐条验：派生表自己藏了值，就等于
 * CSS 是第二处色值真相，而这次重设计要收的正是「同一语义两档值」。
 * 名字不带 `--`：注入时统一加，CSS 侧写 `var(--dc-…)`。
 */
export const cssVars = {
  'dc-font-ui': tokens.fontFamilyUi,
  'dc-bg-layout': tokens.bgLayout,
  'dc-text-primary': tokens.textPrimary,
  'dc-scroll-thumb': tokens.scrollThumb,
  'dc-scroll-thumb-hover': tokens.scrollThumbHover,
  'dc-selection-bg': tokens.selectionBg,
  'dc-ambient-primary': tokens.ambientPrimary,
  'dc-ambient-accent': tokens.ambientAccent,
  'dc-card-top-highlight': tokens.cardTopHighlight,
  'dc-shadow-hover': tokens.shadowHover,
  'dc-shadow-primary': tokens.shadowPrimary,
  'dc-gradient-primary': tokens.gradientPrimary,
} as const;

/** 把 cssVars 注到 :root。CSS 拿不到 TS，只能在此单点导出后由入口注入——不注入这些 var 全部悬空。 */
export function applyCssVars(root: HTMLElement = document.documentElement): void {
  for (const [name, value] of Object.entries(cssVars)) {
    root.style.setProperty(`--${name}`, value);
  }
}

export const dramaTheme: ThemeConfig = {
  algorithm: antdTheme.darkAlgorithm,
  token: {
    colorPrimary: tokens.colorPrimary,
    colorSuccess: tokens.colorSuccess,
    colorWarning: tokens.colorWarning,
    colorError: tokens.colorError,
    colorInfo: tokens.colorInfo,
    colorBgBase: tokens.bgLayout,
    colorBgContainer: tokens.bgContainer,
    colorBgElevated: tokens.bgElevated,
    colorBorder: tokens.border,
    colorBorderSecondary: tokens.borderSecondary,
    colorText: tokens.textPrimary,
    colorTextSecondary: tokens.textSecondary,
    colorTextTertiary: tokens.textTertiary,
    borderRadius: tokens.radiusControl,
    // 与 tokens.text.body 同值：漏这一条，Table/Input/Modal/Select 继续 13，
    // 界面变成一半 13 一半 14，比改之前更糟（规格 §1.4）。
    fontSize: 14,
    // 同理：不写这条，antd 组件继续用它自己的系统字面栈，随包字体只覆盖到自绘元素。
    fontFamily: tokens.fontFamilyUi,
  },
  components: {
    Card: { colorBorderSecondary: tokens.borderSecondary, paddingLG: SPACING.lg },
    Layout: { siderBg: tokens.bgSidebar, headerBg: tokens.bgLayout, bodyBg: tokens.bgLayout },
    Button: { fontWeight: 600, controlHeight: layout.controlHeight.md },
    Table: { headerBg: tokens.bgElevated },
    Tag: { borderRadiusSM: tokens.radiusThumb },
  },
};
