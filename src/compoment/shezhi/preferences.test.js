import test from 'node:test'
import assert from 'node:assert/strict'
import { DEFAULT_PREFERENCES, LEGACY_NAVIGATION_KEY, normalizePreferences, PREFERENCES_KEY, readPreferences, writePreferences } from './preferences.js'

function memory(values = {}) {
  const items = new Map(Object.entries(values))
  return { getItem: key => items.get(key) ?? null, setItem: (key, value) => items.set(key, value) }
}

test('首次使用沿用原侧栏状态，设置保存后可完整恢复', () => {
  const storage = memory({ [LEGACY_NAVIGATION_KEY]: '{"collapsed":true}' })
  assert.equal(readPreferences(storage).settings.sidebarCollapsed, true)
  const settings = { nickname: '选品同学', homePage: '/tupian', sidebarCollapsed: false, autoLoadProducts: false }
  assert.equal(writePreferences(settings, storage), '')
  assert.deepEqual(readPreferences(storage).settings, settings)
})

test('损坏字段、外部首页和伪造布尔值回到安全默认值', () => {
  assert.deepEqual(normalizePreferences({ nickname: {}, homePage: 'https://evil.example', sidebarCollapsed: 'true', autoLoadProducts: 'false' }), DEFAULT_PREFERENCES)
  assert.equal(normalizePreferences({ nickname: '  选品同学  ' }).nickname, '选品同学')
  assert.equal(normalizePreferences({ nickname: '字'.repeat(21) }).nickname, DEFAULT_PREFERENCES.nickname)
  assert.equal(normalizePreferences({ homePage: '/settings' }).homePage, '/tuijian')
  const broken = readPreferences(memory({ [PREFERENCES_KEY]: 'not-json' }))
  assert.deepEqual(broken.settings, DEFAULT_PREFERENCES)
  assert.ok(broken.warning)
})

test('存储禁用或写满时给出提示，不使页面崩溃，也不谎报已保存', () => {
  const storage = { getItem() { throw new Error('blocked') }, setItem() { throw new Error('full') } }
  assert.deepEqual(readPreferences(storage).settings, DEFAULT_PREFERENCES)
  assert.ok(readPreferences(storage).warning)
  assert.match(writePreferences(DEFAULT_PREFERENCES, storage), /本次/)
})

test('恢复默认只改偏好键，保留业务数据和既有记录', () => {
  const storage = memory({ chats: 'saved-chat', images: 'saved-image', [PREFERENCES_KEY]: JSON.stringify({ nickname: '临时昵称' }) })
  writePreferences(DEFAULT_PREFERENCES, storage)
  assert.deepEqual(readPreferences(storage).settings, DEFAULT_PREFERENCES)
  assert.equal(storage.getItem('chats'), 'saved-chat')
  assert.equal(storage.getItem('images'), 'saved-image')
})
