// The till's own copy of what it sells (GET /api/pos/till/): products,
// units, prices (a running promotion's price where there is one), sellable
// stock, payment methods, credit customers and the cashier's open shift. The till searches and prices from this copy whether
// online or not, so a sale rings up the same way either way; the server
// still re-checks stock and prices when the sale is recorded.

import { getTillSnapshot } from '../api/pos.js'
import { kvGet, kvSet } from './db.js'
import { withLock } from './outbox.js'
import { heldVersions, mergeSnapshot } from './snapshotMerge.js'

const key = (userId, storeId) => `till:${userId}:${storeId}`

export const loadTill = (userId, storeId) => kvGet(key(userId, storeId))

/** Fetches a fresh copy; under the outbox lock, so stock never reflects a
 * sale halfway through being recorded. Only what changed since the copy
 * saved here is sent: the catalog when its version moved, and the stock and
 * prices of the products whose figures changed (see snapshotMerge.js). */
export function refreshTill(userId, storeId) {
  return withLock(async () => {
    const saved = await kvGet(key(userId, storeId)).catch(() => null)
    const held = heldVersions(saved)
    const fresh = await getTillSnapshot(storeId, held.catalog, held.sync)
    const snapshot = mergeSnapshot(saved, fresh)
    await kvSet(key(userId, storeId), snapshot)
    return snapshot
  })
}

export const todayIso = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

// Lookups the till makes on every keystroke and scan, built once per
// snapshot (a WeakMap, so an index goes when its snapshot does) instead
// of re-scanning thousands of products, stock rows and prices each time.
const indexes = new WeakMap()

function groupBy(rows, key) {
  const out = new Map()
  for (const row of rows) {
    const list = out.get(row[key])
    if (list) list.push(row)
    else out.set(row[key], [row])
  }
  return out
}

function indexOf(snapshot) {
  let index = indexes.get(snapshot)
  if (!index) {
    index = {
      searchText: snapshot.products.map((p) => `${p.name} ${p.short_name} ${p.brand} ${p.size} ${p.barcode} ${p.category_name} ${p.generic_name ?? ''}`.toLowerCase()),
      byId: new Map(snapshot.products.map((p) => [p.id, p])),
      byBarcode: groupBy(snapshot.products.filter((p) => p.barcode), 'barcode'),
      stock: groupBy(snapshot.stock, 'product'),
      prices: groupBy(snapshot.prices, 'product'),
      units: new Map(snapshot.units.map((u) => [u.id, u])),
    }
    indexes.set(snapshot, index)
  }
  return index
}

/** Products matching every word of `q` in name, short name, brand, size,
 * barcode or category — what the API's ?search= matches. */
export function searchTill(snapshot, q, limit = 6) {
  const words = q.toLowerCase().split(/\s+/).filter(Boolean)
  if (!words.length) return []
  const { searchText } = indexOf(snapshot)
  const out = []
  for (let i = 0; i < searchText.length && out.length < limit; i++) {
    if (words.every((w) => searchText[i].includes(w))) out.push(snapshot.products[i])
  }
  return out
}

export const findByBarcode = (snapshot, code) => (code && indexOf(snapshot).byBarcode.get(code)) || []

export const findProduct = (snapshot, id) => indexOf(snapshot).byId.get(id)

/** One till option per way a product can be sold: its stock unit, plus
 * any other unit that has its own price (e.g. "Crate of 24"). Stock is
 * in the stock unit, so each option knows how many stock units one of
 * it uses up. `unsynced` is stock already sold here but not yet recorded
 * in the cloud (outbox.unsyncedStock). */
export function sellOptions(snapshot, products, unsynced = {}) {
  const today = todayIso()
  const index = indexOf(snapshot)
  return products.flatMap((product) => {
    const onHand = (index.stock.get(product.id) ?? [])
      .filter((b) => b.expiry_date === null || b.expiry_date >= today)
      .reduce((sum, b) => sum + Number(b.qty_on_hand), 0)
    const stockAvailable = Math.max(0, onHand - (unsynced[product.id] ?? 0))
    const prices = index.prices.get(product.id) ?? []
    const baseUnit = index.units.get(product.uom)
    const common = {
      productId: product.id, name: product.name, size: product.size, vatClass: product.vat_class, tracksExpiry: product.tracks_expiry,
      genericName: product.generic_name ?? '', prescriptionOnly: Boolean(product.prescription_only), controlled: Boolean(product.controlled),
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
      const unit = index.units.get(row.uom)
      if (!row.uom || !unit || !baseUnit) continue
      options.push({ ...common, uomId: row.uom, unitName: unit.name, perUnit: Number(unit.unit_value) / Number(baseUnit.unit_value), ...pricing(row) })
    }
    return options
  }).map((o) => ({ ...o, key: `${o.productId}:${o.uomId ?? 'base'}`, qtyAvailable: Math.floor(o.stockAvailable / o.perUnit + 1e-9) }))
}
