import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { findByBarcode, findProduct, searchTill, sellOptions, unsyncedStock } from './catalog.js'
import { AMOX, BALE, MILK, SALT, SUGAR, snapshot } from './fixtures.js'

describe('searchTill', () => {
  const snap = snapshot()

  it('matches every word, in any order, across name, brand and generic name', () => {
    assert.deepEqual(searchTill(snap, 'kilombero sugar').map((p) => p.id), [SUGAR])
    assert.deepEqual(searchTill(snap, 'AMOXICILLIN').map((p) => p.id), [AMOX])
    assert.deepEqual(searchTill(snap, 'sugar milk'), [])
  })

  it('finds nothing for an empty query and stops at the limit', () => {
    assert.deepEqual(searchTill(snap, '   '), [])
    assert.equal(searchTill(snap, '1kg', 1).length, 1)
  })
})

describe('lookups', () => {
  const snap = snapshot()

  it('finds a product by barcode or id', () => {
    assert.deepEqual(findByBarcode(snap, '6201234567890').map((p) => p.id), [SUGAR])
    assert.deepEqual(findByBarcode(snap, '000'), [])
    assert.deepEqual(findByBarcode(snap, ''), [])
    assert.equal(findProduct(snap, MILK).name, 'Fresh milk 500ml')
  })

  it('builds its index once per snapshot, so a fresh snapshot is read afresh', () => {
    const first = snapshot()
    assert.equal(searchTill(first, 'sugar').length, 1)
    const second = snapshot({ products: [] })
    assert.equal(searchTill(second, 'sugar').length, 0)
  })
})

describe('sellOptions', () => {
  const snap = snapshot()
  const options = (id, unsynced) => sellOptions(snap, [findProduct(snap, id)], unsynced)

  it('offers the stock unit and every other priced unit, with how many can be sold', () => {
    const [piece, bale] = options(SUGAR)
    assert.deepEqual([piece.key, piece.unitPrice, piece.perUnit, piece.qtyAvailable], [`${SUGAR}:base`, 3200, 1, 25])
    assert.deepEqual([bale.key, bale.unitName, bale.unitPrice, bale.perUnit, bale.qtyAvailable], [`${SUGAR}:${BALE}`, 'Bale of 10', 30000, 10, 2])
  })

  it('never counts expired stock', () => {
    assert.equal(options(MILK)[0].stockAvailable, 6)
  })

  it('takes off stock sold on this till but not yet in the cloud', () => {
    assert.equal(options(SUGAR, { [SUGAR]: 21 })[1].qtyAvailable, 0)
    assert.equal(options(SUGAR, { [SUGAR]: 99 })[0].stockAvailable, 0)
  })

  it('shows a running promotion beside the regular price', () => {
    const [milk] = options(MILK)
    assert.deepEqual([milk.unitPrice, milk.regularPrice, milk.promotion], [1500, 1800, 'Milk week'])
  })

  it('offers a product without a price, priced null, so the till can say why it cannot sell it', () => {
    const [salt] = options(SALT)
    assert.deepEqual([salt.unitPrice, salt.qtyAvailable], [null, 0])
  })

  it('carries the pharmacy flags', () => {
    const [amox] = options(AMOX)
    assert.deepEqual([amox.prescriptionOnly, amox.controlled, amox.genericName], [true, false, 'Amoxicillin'])
  })
})

describe('unsyncedStock', () => {
  it('adds up the stock units taken by unsent sales of this store only', () => {
    const records = [
      { storeId: 's1', stock: [{ product: SUGAR, qty: 10 }, { product: MILK, qty: 1 }] },
      { storeId: 's1', stock: [{ product: SUGAR, qty: 2 }] },
      { storeId: 's2', stock: [{ product: SUGAR, qty: 50 }] },
    ]
    assert.deepEqual(unsyncedStock(records, 's1'), { [SUGAR]: 12, [MILK]: 1 })
  })
})
