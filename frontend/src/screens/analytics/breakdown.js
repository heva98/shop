// Breaking one pivot cell down: the cell's own items become filters, and one
// more dimension is broken down inside it (its products, its stores, the
// days of its month…). It is an ordinary /api/analytics/query/ call.
import { FIXED_DIMENSIONS, TOTAL, flattenTree, subPeriods } from './visualizationConfig.js'

function splitSpec(spec) {
  const i = spec.indexOf(':')
  return i === -1 ? [spec, []] : [spec.slice(0, i), spec.slice(i + 1).split(';').filter(Boolean)]
}

/**
 * The cell as { dimId: [itemIds] } filters, plus its metric, or null when a
 * cell can't be named (a value nobody recorded can't be filtered on).
 *
 * @param appliedParams  the query string the table was built from
 * @param cellItems      { dimId: itemId } for the cell's layout dimensions
 */
export function cellFilters(appliedParams, cellItems) {
  const source = new URLSearchParams(appliedParams)
  const filters = {}
  let metric = cellItems.dx ?? null
  for (const spec of source.getAll('dimension')) {
    const [id, items] = splitSpec(spec)
    if (id === 'dx') {
      metric ??= items.length === 1 ? items[0] : null
      continue
    }
    const item = cellItems[id]
    // A total covers everything the axis selected; an empty selection of a
    // dynamic dimension restricts nothing.
    if (item === TOTAL || item === undefined) {
      if (items.length) filters[id] = items
    } else {
      filters[id] = [item]
    }
  }
  for (const spec of source.getAll('filter')) {
    const [id, items] = splitSpec(spec)
    filters[id] = items
  }
  return metric ? { metric, filters } : null
}

/** What a cell of `metric` can be broken down by: [{ id, items }]. */
export function breakdownOptions(metric, filters, dimensionsById) {
  const out = []
  const pe = filters.pe?.length === 1 ? subPeriods(filters.pe[0]) : null
  if (pe) out.push({ id: 'pe', items: pe })
  const ou = dimensionsById.ou
  if (ou && (!filters.ou || filters.ou.includes('FIRM') || filters.ou.length > 1)) {
    const stores = flattenTree(ou.items).filter((n) => n.level === 'store').map((n) => n.id)
    const wanted = filters.ou && !filters.ou.includes('FIRM') ? filters.ou : stores
    if (wanted.length > 1) out.push({ id: 'ou', items: wanted })
  }
  for (const dim of Object.values(dimensionsById)) {
    if (FIXED_DIMENSIONS.includes(dim.id) || dim.kind !== 'dynamic' || dim.filter_only) continue
    if (!dim.applies_to.includes(metric.source)) continue
    // Already narrowed to one item: nothing left to split.
    if (filters[dim.id]?.length === 1) continue
    out.push({ id: dim.id, items: filters[dim.id] ?? [] })
  }
  return out
}

/** The query params for `cell` broken down by `by` ({ id, items }). */
export function breakdownQuery(cell, by) {
  const params = new URLSearchParams()
  params.append('dimension', `dx:${cell.metric}`)
  params.append('dimension', `${by.id}:${by.items.join(';')}`)
  for (const [id, items] of Object.entries(cell.filters)) {
    if (id !== by.id) params.append('filter', `${id}:${items.join(';')}`)
  }
  return params
}

/** A pivot table config showing the same breakdown, to keep exploring. */
export function breakdownConfig(cell, by, options) {
  const filters = Object.keys(cell.filters).filter((id) => id !== by.id)
  return {
    version: 1,
    type: 'PIVOT_TABLE',
    columns: ['dx'],
    rows: [by.id],
    filters,
    items: { ...cell.filters, dx: [cell.metric], [by.id]: by.items },
    options: { ...options, columnTotals: true },
  }
}
