// Turns an /api/analytics/query/ response (DHIS2 shape: meta columns, then
// value) into a pivot-table model for a given layout.
import { TOTAL } from './visualizationConfig.js'

// Stands in for an empty Columns or Rows axis, so the table still has one
// header column / row to hang the values on.
const NONE = '__none'

function product(lists) {
  return lists.reduce(
    (acc, list) => acc.flatMap((prefix) => list.map((item) => [...prefix, item])),
    [[]],
  )
}

/**
 * The combinations of one axis. With totals, every non-Data dimension also
 * gets a TOTAL item, but only combos where all of them are TOTAL are kept:
 * the server collapses an axis as a whole, it doesn't compute subtotals.
 * TOTAL sorts last in each list, so a total sits after its group.
 */
function combos(dims, itemsOf, withTotals) {
  const lists = dims.map((d) => (withTotals && d !== 'dx' && d !== NONE ? [...itemsOf(d), TOTAL] : itemsOf(d)))
  const all = product(lists)
  if (!withTotals) return all
  return all.filter((combo) => {
    const marks = combo.filter((item, i) => dims[i] !== 'dx' && item === TOTAL).length
    const totallable = dims.filter((d) => d !== 'dx' && d !== NONE).length
    return marks === 0 || marks === totallable
  })
}

/**
 * @param response  the query response
 * @param layout    { columns, rows } as sent with the query
 * @param options   the config's display options
 * @param labelFor  (dimId, itemId) => display label
 */
export function buildPivot(response, layout, options, labelFor) {
  const { headers, rows, metaData } = response
  const index = Object.fromEntries(headers.map((h, i) => [h.name, i]))
  const valueIdx = index.value

  const colDims = layout.columns.length ? layout.columns : [NONE]
  const rowDims = layout.rows.length ? layout.rows : [NONE]
  const itemsOf = (dim) => (dim === NONE ? [NONE] : metaData.dimensions[dim] ?? [])

  const keyOf = (colCombo, rowCombo) => {
    const parts = []
    colDims.forEach((d, i) => d !== NONE && parts.push(`${d}=${colCombo[i]}`))
    rowDims.forEach((d, i) => d !== NONE && parts.push(`${d}=${rowCombo[i]}`))
    return parts.sort().join('\u0001')
  }

  const cells = new Map()
  let hasTotals = false
  // Keyed on the layout's dimensions only: a single-item Data filter is sent
  // as a dimension (the API requires one) but isn't on either axis.
  const layoutDims = [...layout.columns, ...layout.rows]
  for (const row of rows) {
    const parts = layoutDims.map((d) => `${d}=${row[index[d]]}`).sort()
    const dx = row[index.dx]
    const total = layoutDims.some((d) => row[index[d]] === TOTAL)
    hasTotals ||= total
    cells.set(parts.join('\u0001'), {
      value: row[valueIdx],
      total,
      unit: metaData.items.dx?.items?.[dx]?.unit ?? 'count',
    })
  }

  const totalled = (dims) => dims.some((d) => metaData.items[d]?.items?.[TOTAL])
  let colCombos = combos(colDims, itemsOf, totalled(colDims))
  let rowCombos = combos(rowDims, itemsOf, totalled(rowDims))
  const has = (c, r) => cells.has(keyOf(c, r))
  if (options.hideEmptyColumns) colCombos = colCombos.filter((c) => rowCombos.some((r) => has(c, r)))
  if (options.hideEmptyRows) rowCombos = rowCombos.filter((r) => colCombos.some((c) => has(c, r)))

  const label = (dim, id) => (dim === NONE ? 'Value' : id === TOTAL ? 'Total' : labelFor(dim, id))
  const isTotal = (combo) => combo.includes(TOTAL)

  return {
    colDims,
    rowDims,
    colCombos,
    rowCombos,
    hasTotals,
    isEmpty: rows.length === 0,
    cell: (colCombo, rowCombo) => cells.get(keyOf(colCombo, rowCombo)) ?? null,
    // { dimId: itemId } naming a cell, for drill-down.
    cellItems: (colCombo, rowCombo) => {
      const items = {}
      colDims.forEach((d, i) => { if (d !== NONE) items[d] = colCombo[i] })
      rowDims.forEach((d, i) => { if (d !== NONE) items[d] = rowCombo[i] })
      return items
    },
    label,
    isTotal,
    isPlaceholder: (dim) => dim === NONE,
  }
}

// Header cells for one level of a (column or row) header: consecutive combos
// sharing the prefix up to `level` merge into one cell spanning them.
export function headerSpans(combos, level) {
  const spans = []
  combos.forEach((combo, i) => {
    const prev = spans[spans.length - 1]
    const samePrefix = prev && combo.slice(0, level + 1).every((v, j) => v === combos[prev.start][j])
    if (samePrefix) prev.span += 1
    else spans.push({ start: i, span: 1, id: combo[level] })
  })
  return spans
}

const numberFormats = new Map()
function numberFormat(digits) {
  const key = String(digits)
  if (!numberFormats.has(key)) {
    numberFormats.set(key, new Intl.NumberFormat('en-US', {
      minimumFractionDigits: digits === 'auto' ? 0 : digits,
      maximumFractionDigits: digits === 'auto' ? 2 : digits,
    }))
  }
  return numberFormats.get(key)
}

// Money is shown in whole shillings unless a precision is chosen.
const AUTO_DIGITS = { count: 0, TZS: 0 }

export function formatValue(value, unit, decimals) {
  if (value === null || value === undefined) return ''
  const digits = decimals === 'auto' ? (AUTO_DIGITS[unit] ?? 'auto') : decimals
  const text = numberFormat(digits).format(value)
  return unit === 'percent' ? `${text}%` : text
}

export const UNIT_LABELS = { TZS: 'TZS', qty: 'units', count: '', percent: '%' }
