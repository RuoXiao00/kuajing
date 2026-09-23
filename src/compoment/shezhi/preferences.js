import { storageKey } from '../../runtime.js';
// 只保存界面偏好，不保存令牌、密码、聊天或图片数据；每个浏览器拥有自己的设置。
export const PREFERENCES_KEY = storageKey('kuajing-preferences-v1')
export const LEGACY_NAVIGATION_KEY = storageKey('kuajing-navigation-state-v1')
export const HOME_PAGES = [
  { path: '/tuijian', label: '产品推荐' },
  { path: '/zhishiku', label: '知识库' },
  { path: '/remeng', label: '热门产品' },
  { path: '/tupian', label: '图片生成' },
]
export const DEFAULT_PREFERENCES = Object.freeze({
  nickname: '跨境用户', homePage: '/tuijian', sidebarCollapsed: false, autoLoadProducts: true,
})

export function normalizePreferences(value) {
  const input = value && typeof value === 'object' ? value : {}
  const nickname = typeof input.nickname === 'string' ? input.nickname.trim() : ''
  // localStorage 可以被扩展程序或用户改写，所以路由必须来自白名单，开关只接受布尔值。
  return {
    nickname: nickname && Array.from(nickname).length <= 20 ? nickname : DEFAULT_PREFERENCES.nickname,
    homePage: HOME_PAGES.some(item => item.path === input.homePage) ? input.homePage : DEFAULT_PREFERENCES.homePage,
    sidebarCollapsed: typeof input.sidebarCollapsed === 'boolean' ? input.sidebarCollapsed : false,
    autoLoadProducts: typeof input.autoLoadProducts === 'boolean' ? input.autoLoadProducts : true,
  }
}

export function readPreferences(storage) {
  try {
    const target = storage ?? globalThis.localStorage
    if (!target) throw new Error('storage unavailable')
    const raw = target.getItem(PREFERENCES_KEY)
    if (raw !== null) return { settings: normalizePreferences(JSON.parse(raw)), warning: '' }
    // 兼容原来的侧栏折叠设置，升级后不强行重置用户习惯。
    const old = JSON.parse(target.getItem(LEGACY_NAVIGATION_KEY) || '{}')
    return { settings: normalizePreferences({ sidebarCollapsed: old?.collapsed }), warning: '' }
  } catch {
    return { settings: { ...DEFAULT_PREFERENCES }, warning: '未能读取本地设置，当前使用默认值。' }
  }
}

export function writePreferences(settings, storage) {
  try {
    const target = storage ?? globalThis.localStorage
    if (!target) throw new Error('storage unavailable')
    target.setItem(PREFERENCES_KEY, JSON.stringify(normalizePreferences(settings)))
    return ''
  } catch {
    return '浏览器未能保存设置，修改仅在本次打开期间有效。'
  }
}
