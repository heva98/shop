import { client, listAll } from './client.js'

export const listCategories = (params) => client.get('/api/catalog/categories/', params)
export const createCategory = (data) => client.post('/api/catalog/categories/', data)

export const listUnitsOfMeasure = (params) => client.get('/api/catalog/units-of-measure/', params)
export const listAllUnitsOfMeasure = (params) => listAll('/api/catalog/units-of-measure/', params)
export const createUnitOfMeasure = (data) => client.post('/api/catalog/units-of-measure/', data)

export const listProducts = (params) => client.get('/api/catalog/products/', params)
export const listAllProducts = (params) => listAll('/api/catalog/products/', params)
export const createProduct = (data) => client.post('/api/catalog/products/', data)
export const updateProduct = (id, data) => client.patch(`/api/catalog/products/${id}/`, data)

export const searchProducts = (search) => client.get('/api/catalog/products/', { search })
export const listAllCategories = (params) => listAll('/api/catalog/categories/', params)
export const updateUnitOfMeasure = (id, data) => client.patch(`/api/catalog/units-of-measure/${id}/`, data)
