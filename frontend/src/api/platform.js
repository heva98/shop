import { client, listAll } from './client.js'

// The system administrator's console (core/platform.py): superuser only.
export const listAllShops = (params) => listAll('/api/platform/shops/', params)
export const registerShop = (data) => client.post('/api/platform/shops/', data)
export const updateShop = (id, data) => client.patch(`/api/platform/shops/${id}/`, data)
export const addShopOwner = (id, data) => client.post(`/api/platform/shops/${id}/owners/`, data)
