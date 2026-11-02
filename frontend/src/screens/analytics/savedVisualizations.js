// Helpers shared by the Data Visualizer and the dashboard widgets that draw a
// saved visualization.
import { flattenTree, periodLabel, TOTAL } from './visualizationConfig.js'
import { t } from '../../i18n/index.js'

function listJoin(words) {
  if (words.length <= 1) return words.join('')
  return `${words.slice(0, -1).join(', ')} ${t('and')} ${words.at(-1)}`
}

/**
 * One sentence on why a saved visualization can't be drawn, from the API's
 * `unavailable` list ([{ kind, id, label, reason, features }]), or null when
 * everything it uses is available.
 */
export function unavailableMessage(unavailable) {
  if (!unavailable?.length) return null
  const disabled = unavailable.filter((u) => u.reason === 'feature_disabled')
  if (disabled.length) {
    const features = [...new Set(disabled.flatMap((u) => u.features))]
    return t('It uses {items}, which needs {features}: switched off for this shop under Settings > Features.', {
      items: listJoin(disabled.map((u) => t(u.label))), features: listJoin(features.map((f) => t(f))),
    })
  }
  return t('It uses data that is no longer available: {items}.', { items: listJoin(unavailable.map((u) => t(u.label))) })
}

// Catalogue item labels per dimension, the fallback for an item a query
// response doesn't name.
export function catalogueItemLabels(dimensions) {
  const out = {}
  for (const d of dimensions ?? []) {
    const list = d.kind === 'org_unit' ? flattenTree(d.items) : d.items ?? []
    out[d.id] = Object.fromEntries(list.map((i) => [i.id, i.label]))
  }
  return out
}

// (dimId, itemId) => label, preferring the response's own names (ids can
// repeat across dimensions), then the catalogue, then `extra` (names looked
// up for products and customers).
export function makeLabelFor(itemLabels, response, extra = {}) {
  return (dimId, itemId) => {
    if (itemId === TOTAL) return t('Total')
    const name = response?.metaData?.items?.[dimId]?.items?.[itemId]?.name
    if (name) return t(name)
    if (dimId === 'pe') return t(itemLabels.pe?.[itemId]) ?? periodLabel(itemId)
    return t(itemLabels[dimId]?.[itemId]) ?? extra[dimId]?.[itemId] ?? (itemId || t('(blank)'))
  }
}

// A readable message from a failed request.
export function apiErrorMessage(err, fallback) {
  const body = err?.body
  if (typeof body?.detail === 'string') return body.detail
  const field = body && ['name', 'config', 'description', 'shared'].map((k) => body[k]).find(Boolean)
  if (field) return Array.isArray(field) ? field.join(' ') : String(field)
  if (err?.status === 403) return t('You do not have access to this data.')
  if (err && !err.status) return t('The server could not be reached. Check the connection and try again.')
  return t(fallback)
}
