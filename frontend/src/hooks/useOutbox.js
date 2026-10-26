import { useCallback, useEffect, useState } from 'react'
import { isTransient } from '../api/client.js'
import { listOutbox, subscribe, syncOutbox } from '../offline/outbox.js'
import { loadTill, refreshTill } from '../offline/till.js'

const SYNC_EVERY_MS = 30_000
const REFRESH_TILL_EVERY_MS = 5 * 60_000

/** The till's outbox (see offline/outbox.js), kept current across tabs. */
export function useOutbox() {
  const [records, setRecords] = useState([])
  useEffect(() => {
    let live = true
    const load = () => listOutbox().then((rows) => { if (live) setRecords(rows) }).catch(() => {})
    load()
    const unsubscribe = subscribe(load)
    return () => { live = false; unsubscribe() }
  }, [])
  return records
}

/** Sends `userId`'s waiting sales whenever the connection allows: now, when
 * the browser comes back online, and every 30 s in case it never said. */
export function useOutboxSync(userId) {
  useEffect(() => {
    if (userId == null) return
    const sync = () => { syncOutbox(userId).catch(() => {}) }
    sync()
    window.addEventListener('online', sync)
    const timer = setInterval(sync, SYNC_EVERY_MS)
    return () => { window.removeEventListener('online', sync); clearInterval(timer) }
  }, [userId])
}

/** The till snapshot for `storeId` (offline/till.js): the saved copy at
 * once, then a fresh one whenever online — on open, after each recorded
 * sale, on reconnecting and every few minutes. `offline` is true while the
 * latest refresh couldn't reach the server. */
export function useTill(userId, storeId) {
  const [state, setState] = useState({ snapshot: null, loading: true, offline: false, error: null })

  const refresh = useCallback(async () => {
    if (!storeId) return null
    try {
      const snapshot = await refreshTill(userId, storeId)
      setState({ snapshot, loading: false, offline: false, error: null })
      return snapshot
    } catch (error) {
      setState((s) => ({ ...s, loading: false, offline: isTransient(error), error }))
      return null
    }
  }, [userId, storeId])

  useEffect(() => {
    if (!storeId) return
    let live = true
    setState({ snapshot: null, loading: true, offline: false, error: null })
    loadTill(userId, storeId).then((snapshot) => {
      if (live && snapshot) setState((s) => (s.snapshot ? s : { ...s, snapshot, loading: false }))
    }).catch(() => {})
    refresh()
    const unsubscribe = subscribe((e) => { if (e.synced) refresh() })
    const wentOffline = () => setState((s) => ({ ...s, offline: true }))
    window.addEventListener('online', refresh)
    window.addEventListener('offline', wentOffline)
    const timer = setInterval(refresh, REFRESH_TILL_EVERY_MS)
    return () => {
      live = false; unsubscribe(); clearInterval(timer)
      window.removeEventListener('online', refresh)
      window.removeEventListener('offline', wentOffline)
    }
  }, [userId, storeId, refresh])

  return { ...state, refresh }
}
