import { client, listAll } from './client.js'

export const listStoreProducts = (params) => client.get('/api/inventory/store-products/', params)
export const listAllStoreProducts = (params) => listAll('/api/inventory/store-products/', params)
export const createStoreProduct = (data) => client.post('/api/inventory/store-products/', data)
export const updateStoreProduct = (id, data) => client.patch(`/api/inventory/store-products/${id}/`, data)

export const listBatches = (params) => client.get('/api/inventory/batches/', params)
export const listAllBatches = (params) => listAll('/api/inventory/batches/', params)
export const createBatch = (data) => client.post('/api/inventory/batches/', data)

export const listLedger = (params) => client.get('/api/inventory/ledger/', params)
export const listAllLedger = (params) => listAll('/api/inventory/ledger/', params)

export const listAdjustments = (params) => client.get('/api/inventory/adjustments/', params)
export const createAdjustment = (data) => client.post('/api/inventory/adjustments/', data)
export const writeOffExpired = (store) => client.post('/api/inventory/adjustments/write_off_expired/', { store })

export const listStockCounts = (params) => client.get('/api/inventory/stock-counts/', params)
export const getStockCount = (id) => client.get(`/api/inventory/stock-counts/${id}/`)
export const startStockCount = (data) => client.post('/api/inventory/stock-counts/', data)
/** entries: [{id, counted_qty}] */
export const saveStockCount = (id, entries) => client.post(`/api/inventory/stock-counts/${id}/save/`, entries)
export const addFoundStock = (id, data) => client.post(`/api/inventory/stock-counts/${id}/found/`, data)
export const stockCountAction = (id, action) => client.post(`/api/inventory/stock-counts/${id}/${action}/`)
