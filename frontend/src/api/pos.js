import { client, listAll } from './client.js'

export const listSales = (params) => client.get('/api/pos/sales/', params)
export const listAllSales = (params) => listAll('/api/pos/sales/', params)
export const getSale = (id) => client.get(`/api/pos/sales/${id}/`)
/** `items: [{product, qty}]` — prices and batches are decided by the server. */
export const createSale = (data) => client.post('/api/pos/sales/', data)
/** A whole sale the till rang up from its own copy of the catalog; safe to resend (see offline/outbox.js). */
export const recordSale = (data) => client.post('/api/pos/sales/record/', data, { timeout: 20000 })
/** Catalog, prices (with promotions), stock, payment methods, credit customers and the open shift — what the till sells from. */
export const getTillSnapshot = (store) => client.get('/api/pos/till/', { store }, { timeout: 30000 })
export const cancelSale =(id) => client.post(`/api/pos/sales/${id}/cancel/`)
export const completeSale = (id, payment) => client.post(`/api/pos/sales/${id}/complete/`, payment)
export const retrySale = (id) => client.post(`/api/pos/sales/${id}/retry/`)
export const recordFiscalReceipt = (id, receiptNumber) => client.post(`/api/pos/sales/${id}/record_fiscal/`, { receipt_number: receiptNumber })
export const voidSale = (id, { reason, approverUsername, approverPassword }) =>
  client.post(`/api/pos/sales/${id}/void/`, { reason, approver_username: approverUsername || '', approver_password: approverPassword || '' })

export const getCurrentShift = (store) => client.get('/api/pos/shifts/current/', { store })
export const getShift = (id) => client.get(`/api/pos/shifts/${id}/`)
export const openShift = (store, openingFloat) => client.post('/api/pos/shifts/', { store, opening_float: openingFloat })
export const closeShift = (id, countedCash, note) => client.post(`/api/pos/shifts/${id}/close/`, { counted_cash: countedCash, note })
