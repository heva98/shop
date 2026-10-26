import { client } from './client.js'

export const listEnquiries = (params) => client.get('/api/enquiry/enquiries/', params)
export const createEnquiry = (data) => client.post('/api/enquiry/enquiries/', data)
export const rejectEnquiry = (id) => client.post(`/api/enquiry/enquiries/${id}/reject/`)
export const cancelEnquiry = (id) => client.post(`/api/enquiry/enquiries/${id}/cancel/`)
/** lines: [{product, qty}] — the server picks the batches, earliest expiry first. */
export const fulfillEnquiry = (id, { fromStore, lines, note }) =>
  client.post(`/api/enquiry/enquiries/${id}/fulfill/`, { from_store: fromStore, lines, note })

export const listTransfers = (params) => client.get('/api/enquiry/transfers/', params)
export const sendTransfer = ({ fromStore, toStore, lines, note }) =>
  client.post('/api/enquiry/transfers/', { from_store: fromStore, to_store: toStore, lines, note })
export const confirmReceipt = (id, { receivedQtyByLine, note } = {}) =>
  client.post(`/api/enquiry/transfers/${id}/confirm_receipt/`, { received_qty_by_line: receivedQtyByLine, note })
export const resolveTransfer = (id, { resolution, note } = {}) =>
  client.post(`/api/enquiry/transfers/${id}/resolve/`, { resolution, note })
export const cancelTransfer = (id, reason) => client.post(`/api/enquiry/transfers/${id}/cancel/`, { reason })
export const payTransfer = (id, { paymentMethod, reference }) =>
  client.post(`/api/enquiry/transfers/${id}/pay/`, { payment_method: paymentMethod, reference })
