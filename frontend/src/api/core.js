import { client, listAll, setToken } from './client.js'

export async function login(username, password) {
  const { token } = await client.post('/api/auth-token/', { username, password })
  setToken(token)
  return token
}

export function logout() {
  setToken(null)
}

export const me = () => client.get('/api/core/users/me/')
export const updateMe = (data) => client.patch('/api/core/users/me/', data)

export const listEntities = (params) => client.get('/api/core/entities/', params)
export const updateEntity = (id, data) => client.patch(`/api/core/entities/${id}/`, data)

/** `logoFileOrNull`: a File to upload as the new logo, or null to clear it. */
export function updateEntityLogo(id, logoFileOrNull) {
  if (logoFileOrNull === null) return updateEntity(id, { logo: null })
  const form = new FormData()
  form.append('logo', logoFileOrNull)
  return client.patch(`/api/core/entities/${id}/`, form)
}

export const listAllStores = (params) => listAll('/api/core/stores/', params)
export const listStores = (params) => client.get('/api/core/stores/', params)
export const createStore = (data) => client.post('/api/core/stores/', data)
export const updateStore = (id, data) => client.patch(`/api/core/stores/${id}/`, data)
export const deleteStore = (id) => client.delete(`/api/core/stores/${id}/`)

export const listAllUsers = (params) => listAll('/api/core/users/', params)
export const listUsers = (params) => client.get('/api/core/users/', params)
export const createUser = (data) => client.post('/api/core/users/', data)
export const updateUser = (id, data) => client.patch(`/api/core/users/${id}/`, data)

export const listAllStoreRoles = (params) => listAll('/api/core/store-roles/', params)
export const listStoreRoles = (params) => client.get('/api/core/store-roles/', params)
export const createStoreRole = (data) => client.post('/api/core/store-roles/', data)
export const deleteStoreRole = (id) => client.delete(`/api/core/store-roles/${id}/`)

export const listModules = (params) => client.get('/api/core/modules/', params)
export const listModuleEnablements = (params) => client.get('/api/core/module-enablements/', params)
export const createModuleEnablement = (data) => client.post('/api/core/module-enablements/', data)
export const updateModuleEnablement = (id, data) => client.patch(`/api/core/module-enablements/${id}/`, data)

export const getFeatures = () => client.get('/api/core/features/')
export const setFeature = (key, store, enabled) => client.patch('/api/core/features/', { key, store, enabled })
