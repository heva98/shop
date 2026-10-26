import { client } from './client.js'

export const getAnalyticsDimensions = () => client.get('/api/analytics/dimensions/')

// `params` is a URLSearchParams: the query repeats `dimension`, `filter` and
// `total`, which a plain params object can't express.
export const runAnalyticsQuery = (params, options) =>
  client.get(`/api/analytics/query/?${params.toString()}`, undefined, options)

// Products and customers are too many to list up front: search them, and
// name a saved selection by id.
export const searchDimensionItems = (dimension, search, ids = []) =>
  client.get('/api/analytics/items/', { dimension, search, ids: ids.join(',') || undefined })

// ── saved visualizations ─────────────────────────────────────────────────────

const VIZ = '/api/analytics/visualizations/'

// params: { search, pinned: 'true' }
export const listVisualizations = (params) => client.get(VIZ, params)
export const getVisualization = (id) => client.get(`${VIZ}${id}/`)
// data: { name, description, config, shared }
export const createVisualization = (data) => client.post(VIZ, data)
export const updateVisualization = (id, data) => client.patch(`${VIZ}${id}/`, data)
export const deleteVisualization = (id) => client.delete(`${VIZ}${id}/`)
export const pinVisualization = (id) => client.post(`${VIZ}${id}/pin/`)
export const unpinVisualization = (id) => client.delete(`${VIZ}${id}/pin/`)
