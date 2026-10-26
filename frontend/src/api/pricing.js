import { client, listAll } from './client.js'

export const listPrices = (params) => client.get('/api/pricing/prices/', params)
export const listAllPrices = (params) => listAll('/api/pricing/prices/', params)
export const createPrice = (data) => client.post('/api/pricing/prices/', data)
export const updatePrice = (id, data) => client.patch(`/api/pricing/prices/${id}/`, data)

export const listBundles = (params) => client.get('/api/pricing/bundles/', params)
export const createBundle = (data) => client.post('/api/pricing/bundles/', data)
export const deletePrice = (id) => client.delete(`/api/pricing/prices/${id}/`)

export const listPromotions = (params) => client.get('/api/pricing/promotions/', params)
export const listAllPromotions = (params) => listAll('/api/pricing/promotions/', params)
export const createPromotion = (data) => client.post('/api/pricing/promotions/', data)
export const updatePromotion = (id, data) => client.patch(`/api/pricing/promotions/${id}/`, data)
export const deletePromotion = (id) => client.delete(`/api/pricing/promotions/${id}/`)
