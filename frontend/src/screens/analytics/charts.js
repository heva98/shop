// Turns a pivot model (see pivot.js) into what the chart renderer draws.
// Charts read the same layout as the table: Columns are the series, Rows the
// categories, each holding at most one dimension (`layoutProblem` enforces it).
import { formatValue } from './pivot.js'

// Categorical hues in fixed order, so a series keeps its colour when the
// chart is re-sorted or filtered; a ninth series is never a generated hue
// (see MAX_SERIES). Slot 1 is the brand blue; the order was checked for
// colour-blind separation between neighbours. Light hues fall under 3:1
// against white, so charts always keep a legend, tooltips and the table view.
export const SERIES_COLORS = [
  '#0B5ED7', '#EB6834', '#1BAF7A', '#EDA100', '#E87BA4', '#008300', '#6250D6', '#E34948',
]
export const MAX_SERIES = SERIES_COLORS.length

// The one unit every value shares, or null when they're mixed.
function commonUnit(cells) {
  const units = new Set(cells.filter(Boolean).map((c) => c.unit))
  return units.size === 1 ? [...units][0] : null
}

const numeric = (c) => (c && c.value !== null && c.value !== undefined ? Number(c.value) : null)

/**
 * @returns {{
 *   type, unit,
 *   series: [{ key, name, color }],   // bar/column/line series; pie slices
 *   data: [{ category, [key]: number|null, [`${key}__label`]: string }],
 *   seriesDim, categoryDim,           // dimension ids (null for none)
 *   tooMany: number|null,             // series count over MAX_SERIES
 *   single: { name, cell, text } | undefined,
 * }}
 */
export function buildChartModel(pivot, type, options) {
  const { colDims, rowDims, colCombos, rowCombos, cell, label, isPlaceholder } = pivot
  const fmt = (c) => (c ? formatValue(c.value, c.unit, options.decimals) : '')

  if (type === 'SINGLE_VALUE') {
    const c = cell(colCombos[0], rowCombos[0])
    return {
      type,
      unit: c?.unit ?? null,
      single: { name: label(colDims[0], colCombos[0][0]), cell: c, text: fmt(c) },
    }
  }

  if (type === 'PIE') {
    const dim = colDims[0]
    let slices = colCombos.map((combo, i) => {
      const c = cell(combo, rowCombos[0])
      return { key: `s${i}`, name: label(dim, combo[0]), value: numeric(c), label: fmt(c), cell: c, color: SERIES_COLORS[i] }
    })
    const cells = slices.map((s) => s.cell)
    slices = sortBy(slices.filter((s) => s.value !== null && s.value > 0), (s) => s.value, options.sortOrder)
    return {
      type,
      unit: commonUnit(cells),
      seriesDim: dim,
      series: slices,
      data: slices,
      tooMany: colCombos.length > MAX_SERIES ? colCombos.length : null,
    }
  }

  // A layout with only a series draws its items as the categories of one
  // unnamed series, as DHIS2 does, rather than one bar per legend entry.
  let seriesDim = colDims[0]
  let categoryDim = rowDims[0]
  let seriesItems = colCombos.map((c) => c[0])
  let categoryItems = rowCombos.map((r) => r[0])
  let get = (s, c) => cell([s], [c])
  if (isPlaceholder(categoryDim)) {
    ;[seriesDim, categoryDim] = [categoryDim, seriesDim]
    ;[seriesItems, categoryItems] = [categoryItems, seriesItems]
    get = (s, c) => cell([c], [s])
  }

  const series = seriesItems.map((id, i) => ({
    key: `s${i}`,
    name: isPlaceholder(seriesDim) ? null : label(seriesDim, id),
    color: SERIES_COLORS[i],
  }))

  const allCells = []
  let data = categoryItems.map((catId) => {
    const row = { category: label(categoryDim, catId) }
    seriesItems.forEach((sId, i) => {
      const c = get(sId, catId)
      allCells.push(c)
      const key = `s${i}`
      row[key] = numeric(c)
      row[`${key}__label`] = fmt(c)
    })
    return row
  })
  data = sortBy(data, (row) => series.reduce((sum, s) => sum + (row[s.key] ?? 0), 0), options.sortOrder)

  return {
    type,
    unit: commonUnit(allCells),
    seriesDim: isPlaceholder(seriesDim) ? null : seriesDim,
    categoryDim: isPlaceholder(categoryDim) ? null : categoryDim,
    series,
    data,
    tooMany: seriesItems.length > MAX_SERIES ? seriesItems.length : null,
  }
}

function sortBy(list, valueOf, order) {
  if (order !== 'asc' && order !== 'desc') return list
  const sign = order === 'asc' ? 1 : -1
  return [...list].sort((a, b) => sign * (valueOf(a) - valueOf(b)))
}

// Axis tick text: numbers compact, with the unit when every value shares one.
export function tickFormatter(unit) {
  const nf = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 })
  return (v) => (unit === 'percent' ? `${nf.format(v)}%` : unit === 'TZS' ? `TZS ${nf.format(v)}` : nf.format(v))
}

/** How a single value stands against the target, or null without one. */
export function singleValueStatus(model, options) {
  const { cell } = model.single
  const target = options.targetValue
  if (target === null || target === undefined || !cell || cell.value === null) return null
  const diff = Number(cell.value) - target
  // The gap between two percentages is in percentage points, not percent.
  const amount = cell.unit === 'percent'
    ? `${formatValue(Math.abs(diff), 'points', options.decimals)} points`
    : formatValue(Math.abs(diff), cell.unit, options.decimals)
  const what = options.targetLabel || 'target'
  return diff >= 0
    ? { text: `▲ ${amount} above ${what}`, color: '#13693F' }
    : { text: `▼ ${amount} below ${what}`, color: '#A82020' }
}
