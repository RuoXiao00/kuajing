import test from 'node:test'
import assert from 'node:assert/strict'
import { normalizeSnapshot, readSavedSnapshot, saveSnapshot, snapshotView, revealMoreProducts, watchSharedSnapshot } from './dailySnapshot.js'

const snapshot = (id = 'today') => ({ category: 'hot', sub_category: 'all', fetched_at: '2026-09-27T05:00:00+08:00', snapshot_id: id,
  products: Array.from({ length: 53 }, (_, n) => ({ asin: `B${String(n).padStart(9, '0')}`, title: `Product ${n}`,
    price: 12, currency: 'USD', url: `https://www.amazon.com/dp/B${String(n).padStart(9, '0')}` })) })

test('full collection is retained while scrolling reveals 20/40/53 without network', () => {
  let view = snapshotView(null, normalizeSnapshot(snapshot(), 'hot', 'all'))
  assert.equal(view.data.products.length, 53)
  assert.equal(view.visibleCount, 20)
  view = revealMoreProducts(view)
  assert.equal(view.visibleCount, 40)
  view = revealMoreProducts(view)
  assert.equal(view.visibleCount, 53)
  assert.equal(revealMoreProducts(view).visibleCount, 53)
})

test('same version preserves scroll count, daily replacement discards old list', () => {
  const data = normalizeSnapshot(snapshot(), 'hot', 'all')
  const previous = revealMoreProducts(snapshotView(null, data))
  assert.equal(snapshotView(previous, data).visibleCount, 40)
  const newData = normalizeSnapshot(snapshot('tomorrow'), 'hot', 'all')
  assert.equal(snapshotView(previous, newData).visibleCount, 20)
})

test('snapshot storage contains all products, rejects wrong filters and corrupt values', () => {
  let raw
  const storage = { setItem: (_, value) => { raw = value }, getItem: () => raw }
  assert.equal(saveSnapshot(snapshot(), 'hot', 'all', storage), true)
  assert.equal(readSavedSnapshot('hot', 'all', storage).products.length, 53)
  assert.equal(readSavedSnapshot('niche', 'all', storage), null)
  raw = 'broken'
  assert.equal(readSavedSnapshot('hot', 'all', storage), null)
})

test('blocked localStorage getter does not crash initial rendering', () => {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, get() { throw new Error('blocked') } })
  try { assert.equal(readSavedSnapshot('hot', 'all'), null); assert.equal(saveSnapshot(snapshot(), 'hot', 'all'), false) }
  finally { if (descriptor) Object.defineProperty(globalThis, 'localStorage', descriptor); else delete globalThis.localStorage }
})

test('ready snapshot needs only one read; revealMore cannot issue requests', async () => {
  const urls = [], timers = new Map()
  let result
  const stop = watchSharedSnapshot({ endpoint: '/api/remen/products/snapshot', category: 'hot', subCategory: 'all',
    fetcher: async url => { urls.push(url); return Response.json({ snapshot: snapshot(), update_status: 'ready' }) },
    onResult: value => { result = value }, onError: assert.fail,
    setTimer: (fn, delay) => { timers.set(fn, delay); return fn }, clearTimer: id => timers.delete(id) })
  await new Promise(resolve => setImmediate(resolve))
  let view = snapshotView(null, result.snapshot)
  for (let i = 0; i < 5; i++) view = revealMoreProducts(view)
  assert.equal(urls.length, 1)
  assert.ok(urls[0].startsWith('/api/remen/products/snapshot?'))
  assert.equal(timers.size, 0)
  stop()
})

test('pending updates use bounded read-only polling and stop on unmount', async () => {
  const timers = new Map()
  let calls = 0
  const stop = watchSharedSnapshot({ endpoint: '/api/remen/products/snapshot', category: 'hot', subCategory: 'all',
    fetcher: async () => { calls++; return Response.json({ snapshot: null, update_status: 'pending' }) },
    onResult: () => {}, onError: assert.fail,
    setTimer: (fn, delay) => { timers.set(fn, delay); return fn }, clearTimer: id => timers.delete(id) })
  for (let i = 0; i < 7; i++) {
    await new Promise(resolve => setImmediate(resolve))
    const entry = [...timers].find(([, delay]) => delay >= 15000)
    if (entry) { timers.delete(entry[0]); entry[0]() }
  }
  assert.equal(calls, 6)
  stop()
  assert.equal(timers.size, 0)
})
