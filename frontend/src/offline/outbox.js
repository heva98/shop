// Sales the till rang up that the cloud hasn't recorded yet
// (architecture.txt §4, outbox pattern). Every sale is written here first,
// so a dropped connection — or a closed browser — can't lose one; it's
// then sent to POST /api/pos/sales/record/, which uses the sale's own id,
// so sending it twice records it once.
//
// A record is { id, userId, storeId, shiftId, createdAt, status, error,
// payload, receipt, stock }: `payload` is the request body, `receipt` the
// sale as the till printed it, `stock` [{product, qty}] in stock units.
// status 'pending' = waiting to be sent; 'rejected' = the server refused it
// (e.g. not enough stock in the cloud) and a person must retry or discard it.

import { isTransient } from '../api/client.js'
import { recordSale } from '../api/pos.js'
import { apiErrorText } from '../lib/apiError.js'
import { outboxAll, outboxDelete, outboxPut } from './db.js'

const listeners = new Set()
const channel = typeof BroadcastChannel === 'undefined' ? null : new BroadcastChannel('duka-erp-outbox')

/** fn(event) on every change, in this tab or another; event.synced is the
 * server's sale when one was just recorded. Returns an unsubscribe. */
export function subscribe(fn) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

function emit(event = {}) {
  listeners.forEach((fn) => fn(event))
  channel?.postMessage({ synced: !!event.synced })
}
if (channel) channel.onmessage = (e) => listeners.forEach((fn) => fn(e.data))

/** One sender at a time across tabs, so a sale is never sent twice at once
 * and the till's snapshot is never fetched mid-sync. */
export function withLock(fn) {
  if (navigator.locks) return navigator.locks.request('duka-erp-outbox', fn)
  return fn()
}

export const listOutbox = () => outboxAll().then((rows) => rows.sort((a, b) => a.createdAt.localeCompare(b.createdAt)))

/** Saves the sale, then — if the connection allows — records it straight
 * away. Returns { sale } when recorded, { queued: true } when it's kept for
 * later, and throws the server's refusal (removing it from the outbox) so
 * the cashier can fix the cart while the customer is still there.
 *
 * `secret` (a manager's approval login) goes with this one request only
 * and is never saved on the till; a sale queued without it is recorded
 * later as unapproved, and the server's audit log says so. */
export function placeSale(record, secret = {}) {
  return withLock(async () => {
    await outboxPut(record)
    emit()
    try {
      // strict: refuse rather than record a price the cloud has changed
      const sale = await recordSale({ ...record.payload, ...secret, strict: true })
      await outboxDelete(record.id)
      emit({ synced: sale })
      return { sale }
    } catch (err) {
      if (isTransient(err)) return { queued: true }
      await outboxDelete(record.id)
      emit()
      throw err
    }
  })
}

/** Sends every pending sale of `userId` (the server records it as theirs),
 * oldest first, stopping at the first connection problem. */
export function syncOutbox(userId) {
  return withLock(async () => {
    const pending = (await listOutbox()).filter((r) => r.status === 'pending' && r.userId === userId)
    for (const record of pending) {
      try {
        const sale = await recordSale(record.payload)
        await outboxDelete(record.id)
        emit({ synced: sale })
      } catch (err) {
        if (isTransient(err)) return
        await outboxPut({ ...record, status: 'rejected', error: apiErrorText(err, 'The server refused this sale.') })
        emit()
      }
    }
  })
}

export async function retryRejected(record, userId) {
  await outboxPut({ ...record, status: 'pending', error: '' })
  emit()
  return syncOutbox(userId)
}

/** Adds the EFD receipt number to a sale still in the outbox, so it's sent
 * with the sale. False when the sale has already been recorded (record the
 * number online instead). */
export function setUnsentEfdNumber(id, receiptNumber) {
  return withLock(async () => {
    const record = (await outboxAll()).find((r) => r.id === id)
    if (!record) return false
    await outboxPut({
      ...record,
      payload: { ...record.payload, efd_receipt_no: receiptNumber },
      receipt: { ...record.receipt, efd_receipt_no: receiptNumber },
    })
    emit()
    return true
  })
}

export async function discard(record) {
  await outboxDelete(record.id)
  emit()
}

/** Stock units of each product that the outbox's sales have taken from
 * `storeId` but the cloud's figures don't show yet. */
export function unsyncedStock(records, storeId) {
  const out = {}
  for (const r of records) {
    if (r.storeId !== storeId) continue
    for (const s of r.stock) out[s.product] = (out[s.product] ?? 0) + s.qty
  }
  return out
}
