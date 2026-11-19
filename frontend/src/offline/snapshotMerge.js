// Merging a fresh till snapshot (GET /api/pos/till/) into the copy the till
// already holds. Kept free of imports so it can be checked on its own.
//
// The catalog (products, units) comes back null when the till's
// catalog_version is current. Stock and prices come back in part when the
// till sent its sync_state: every product falls in one of SYNC_BUCKETS
// groups, and only the rows of the groups listed in sync_buckets are sent;
// they replace the till's rows of those groups. Must match
// pos.views.TillSnapshotView.sync_bucket on the server.

export const SYNC_BUCKETS = 128

export const syncBucket = (productId) => parseInt(String(productId).slice(0, 8), 16) % SYNC_BUCKETS

/** The query values that let the server leave out what `saved` already has. */
export function heldVersions(saved) {
  return {
    catalog: saved?.catalog_version && saved.products && saved.units ? saved.catalog_version : undefined,
    sync: saved?.sync_state && Array.isArray(saved.stock) && Array.isArray(saved.prices) ? saved.sync_state : undefined,
  }
}

export function mergeSnapshot(saved, fresh) {
  const snapshot = { ...fresh }
  if (fresh.products === null || fresh.units === null) {
    snapshot.products = saved.products
    snapshot.units = saved.units
  }
  if (Array.isArray(fresh.sync_buckets)) {
    const changed = new Set(fresh.sync_buckets)
    const keep = (row) => !changed.has(syncBucket(row.product))
    snapshot.stock = saved.stock.filter(keep).concat(fresh.stock)
    snapshot.prices = saved.prices.filter(keep).concat(fresh.prices)
  }
  return snapshot
}
