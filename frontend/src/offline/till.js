// The till's own copy of what it sells (GET /api/pos/till/): products,
// units, prices (a running promotion's price where there is one), sellable
// stock, payment methods, credit customers and the cashier's open shift. The till searches and prices from this copy whether
// online or not, so a sale rings up the same way either way; the server
// still re-checks stock and prices when the sale is recorded.

import { getTillSnapshot } from '../api/pos.js'
import { kvGet, kvSet } from './db.js'
import { withLock } from './outbox.js'

const key = (userId, storeId) => `till:${userId}:${storeId}`

export const loadTill = (userId, storeId) => kvGet(key(userId, storeId))

/** Fetches a fresh copy; under the outbox lock, so stock never reflects a
 * sale halfway through being recorded. */
export function refreshTill(userId, storeId) {
  return withLock(async () => {
    const snapshot = await getTillSnapshot(storeId)
    await kvSet(key(userId, storeId), snapshot)
    return snapshot
  })
}

export const todayIso = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** Products matching every word of `q` in name, short name, brand, size,
 * barcode or category — what the API's ?search= matches. */
export function searchTill(snapshot, q, limit = 6) {
  const words = q.toLowerCase().split(/\s+/).filter(Boolean)
  if (!words.length) return []
  const out = []
  for (const p of snapshot.products) {
    const text = `${p.name} ${p.short_name} ${p.brand} ${p.size} ${p.barcode} ${p.category_name}`.toLowerCase()
    if (words.every((w) => text.includes(w))) out.push(p)
    if (out.length >= limit) break
  }
  return out
}

export const findByBarcode = (snapshot, code) => snapshot.products.filter((p) => p.barcode && p.barcode === code)

/** One till option per way a product can be sold: its stock unit, plus
 * any other unit that has its own price (e.g. "Crate of 24"). Stock is
 * in the stock unit, so each option knows how many stock units one of
 * it uses up. `unsynced` is stock already sold here but not yet recorded
 * in the cloud (outbox.unsyncedStock). */
export function sellOptions(snapshot, products, unsynced = {}) {
  const today = todayIso()
  const unitById = Object.fromEntries(snapshot.units.map((u) => [u.id, u]))
  return products.flatMap((product) => {
    const onHand = snapshot.stock
      .filter((b) => b.product === product.id && (b.expiry_date === null || b.expiry_date >= today))
      .reduce((sum, b) => sum + Number(b.qty_on_hand), 0)
    const stockAvailable = Math.max(0, onHand - (unsynced[product.id] ?? 0))
    const prices = snapshot.prices.filter((p) => p.product === product.id)
    const baseUnit = unitById[product.uom]
    const common = {
      productId: product.id, name: product.name, size: product.size, vatClass: product.vat_class,
      stockAvailable,
    }
    const base = prices.find((p) => p.uom === null)
    const pricing = (row) => ({
      unitPrice: row ? Number(row.unit_price) : null,
      regularPrice: row?.regular_price != null ? Number(row.regular_price) : null,
      promotion: row?.promotion ?? null,
    })
    const options = [{ ...common, uomId: null, unitName: baseUnit?.name ?? '', perUnit: 1, ...pricing(base) }]
    for (const row of prices) {
      const unit = unitById[row.uom]
      if (!row.uom || !unit || !baseUnit) continue
      options.push({ ...common, uomId: row.uom, unitName: unit.name, perUnit: Number(unit.unit_value) / Number(baseUnit.unit_value), ...pricing(row) })
    }
    return options
  }).map((o) => ({ ...o, key: `${o.productId}:${o.uomId ?? 'base'}`, qtyAvailable: Math.floor(o.stockAvailable / o.perUnit + 1e-9) }))
}
