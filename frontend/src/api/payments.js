import { client } from './client.js'

export const listPaymentMethods = (params) => client.get('/api/payments/payment-methods/', params)
export const updatePaymentMethod = (id, data) => client.patch(`/api/payments/payment-methods/${id}/`, data)
