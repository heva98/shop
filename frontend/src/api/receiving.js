import { client, listAll } from './client.js'

export const listSuppliers = (params) => client.get('/api/receiving/suppliers/', params)
export const listAllSuppliers = (params) => listAll('/api/receiving/suppliers/', params)
export const createSupplier = (data) => client.post('/api/receiving/suppliers/', data)
export const updateSupplier = (id, data) => client.patch(`/api/receiving/suppliers/${id}/`, data)

export const listInvoices = (params) => client.get('/api/receiving/invoices/', params)
export const getInvoice = (id) => client.get(`/api/receiving/invoices/${id}/`)
export const createInvoice = (data) => client.post('/api/receiving/invoices/', data)
export const updateInvoice = (id, data) => client.patch(`/api/receiving/invoices/${id}/`, data)
export const receiveInvoice = (id) => client.post(`/api/receiving/invoices/${id}/receive/`)
export const payInvoice = (id, data) => client.post(`/api/receiving/invoices/${id}/pay/`, data)

export const addInvoiceLine = (data) => client.post('/api/receiving/invoice-lines/', data)
