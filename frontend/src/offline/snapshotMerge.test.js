import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { heldVersions, mergeSnapshot, syncBucket, SYNC_BUCKETS } from './snapshotMerge.js'
import { MILK, SUGAR, snapshot } from './fixtures.js'

describe('syncBucket', () => {
  it('matches the server: the first 8 hex digits of the id, modulo 128 (pos.till.sync_bucket)', () => {
    assert.equal(SYNC_BUCKETS, 128)
    assert.equal(syncBucket(SUGAR), 0xa1000001 % 128)
    assert.equal(syncBucket('ffffffff-0000'), 0xffffffff % 128)
  })
})

describe('heldVersions', () => {
  it('asks for nothing it already has, and everything when the copy is incomplete', () => {
    const saved = { ...snapshot(), catalog_version: 'v1', sync_state: 'abc' }
    assert.deepEqual(heldVersions(saved), { catalog: 'v1', sync: 'abc' })
    assert.deepEqual(heldVersions({ ...saved, products: null }), { catalog: undefined, sync: 'abc' })
    assert.deepEqual(heldVersions({ ...saved, stock: undefined }), { catalog: 'v1', sync: undefined })
    assert.deepEqual(heldVersions(null), { catalog: undefined, sync: undefined })
  })
})

describe('mergeSnapshot', () => {
  const saved = snapshot()

  it('keeps the saved catalog when the server says it is unchanged', () => {
    const merged = mergeSnapshot(saved, { ...snapshot(), products: null, units: null })
    assert.equal(merged.products, saved.products)
    assert.equal(merged.units, saved.units)
  })

  it('replaces only the stock and prices of the buckets that changed', () => {
    const fresh = {
      ...snapshot(), products: null, units: null, sync_buckets: [syncBucket(SUGAR)],
      stock: [{ product: SUGAR, qty_on_hand: '3.00', expiry_date: null }],
      prices: [{ product: SUGAR, uom: null, unit_price: '3500.00', regular_price: '3500.00', promotion: null }],
    }
    const merged = mergeSnapshot(saved, fresh)
    assert.deepEqual(merged.stock.filter((r) => r.product === SUGAR).map((r) => r.qty_on_hand), ['3.00'])
    assert.deepEqual(merged.prices.filter((r) => r.product === SUGAR).map((r) => r.unit_price), ['3500.00'])
    assert.equal(merged.stock.filter((r) => r.product === MILK).length, 2, 'unchanged buckets are kept')
  })

  it('takes the whole fresh copy when the server sent everything', () => {
    const fresh = { ...snapshot(), stock: [], prices: [], sync_buckets: null }
    const merged = mergeSnapshot(saved, fresh)
    assert.deepEqual([merged.stock, merged.prices], [[], []])
  })
})
