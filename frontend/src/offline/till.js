// The till's own copy of what it sells (GET /api/pos/till/): products,
// units, prices (a running promotion's price where there is one), sellable
// stock, payment methods, credit customers and the cashier's open shift. The till searches and prices from this copy whether
// online or not, so a sale rings up the same way either way; the server
// still re-checks stock and prices when the sale is recorded.
//
// This file keeps the copy (load, refresh); offline/catalog.js reads it.

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
