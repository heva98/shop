import { client, listAll } from './client.js'

export const listCustomers = (params) => client.get('/api/credit/customers/', params)
export const listAllCustomers = (params) => listAll('/api/credit/customers/', params)
export const createCustomer = (data) => client.post('/api/credit/customers/', data)
export const updateCustomer = (id, data) => client.patch(`/api/credit/customers/${id}/`, data)
export const getCreditSummary = () => client.get('/api/credit/customers/summary/')
export const getStatement = (id) => client.get(`/api/credit/customers/${id}/statement/`)

export const listCreditPayments = (params) => client.get('/api/credit/payments/', params)
/** {customer, store, amount, payment_method, reference, note}. A cash payment taken by a cashier counts in their open shift. */
export const receivePayment = (data) => client.post('/api/credit/payments/', data)
export const voidPayment = (id, reason) => client.post(`/api/credit/payments/${id}/void/`, { reason })
