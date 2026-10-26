// The till's own storage (IndexedDB): the outbox of sales not yet recorded
// in the cloud, and a key-value store for the till snapshot. Unlike
// localStorage it survives large catalogs and is shared by every tab.

const DB_NAME = 'duka-erp-till'
const OUTBOX = 'outbox'
const KV = 'kv'

let dbPromise = null

function open() {
  dbPromise ??= new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1)
    req.onupgradeneeded = () => {
      req.result.createObjectStore(OUTBOX, { keyPath: 'id' })
      req.result.createObjectStore(KV)
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => { dbPromise = null; reject(req.error) }
  })
  return dbPromise
}

async function run(storeName, mode, fn) {
  const db = await open()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, mode)
    const req = fn(tx.objectStore(storeName))
    tx.oncomplete = () => resolve(req?.result)
    tx.onerror = () => reject(tx.error)
    tx.onabort = () => reject(tx.error)
  })
}

export const outboxAll = () => run(OUTBOX, 'readonly', (s) => s.getAll())
export const outboxPut = (record) => run(OUTBOX, 'readwrite', (s) => s.put(record))
export const outboxDelete = (id) => run(OUTBOX, 'readwrite', (s) => s.delete(id))

export const kvGet = (key) => run(KV, 'readonly', (s) => s.get(key))
export const kvSet = (key, value) => run(KV, 'readwrite', (s) => s.put(value, key))
