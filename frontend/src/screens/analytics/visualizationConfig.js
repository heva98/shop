// The Data Visualizer keeps its whole state in one serialisable
// "visualization config" object, driven by `configReducer`, so a saved
// visualization is this object stored as-is.
//
//   {
//     version: 1,
//     type: 'PIVOT_TABLE',
//     columns: ['dx'], rows: ['pe'], filters: ['ou'],   // layout: dimension ids
//     items:   { dx: [...], pe: [...], ou: [...] },     // selected item ids per dimension
//     options: { ... },                                 // display options
//   }

export const AXES = ['columns', 'rows', 'filters']

// dataTransfer type for dragging a dimension onto the layout.
export const DIM_MIME = 'application/x-duka-dimension'

export const AXIS_LABELS = { columns: 'Columns', rows: 'Rows', filters: 'Filter' }

// Charts read Columns as the series and Rows as the category (DHIS2's names).
const CHART_AXIS_LABELS = { columns: 'Series', rows: 'Category', filters: 'Filter' }

// `series` / `category`: the most dimensions each axis takes.
export const VISUALIZATION_TYPES = [
  { id: 'PIVOT_TABLE', label: 'Pivot table' },
  { id: 'COLUMN', label: 'Column chart', chart: true, series: 1, category: 1 },
  { id: 'STACKED_COLUMN', label: 'Stacked column chart', chart: true, series: 1, category: 1 },
  { id: 'BAR', label: 'Bar chart', chart: true, series: 1, category: 1 },
  { id: 'LINE', label: 'Line chart', chart: true, series: 1, category: 1 },
  { id: 'PIE', label: 'Pie chart', chart: true, series: 1, category: 0 },
  { id: 'SINGLE_VALUE', label: 'Single value', chart: true, series: 1, category: 0 },
]
const TYPES_BY_ID = Object.fromEntries(VISUALIZATION_TYPES.map((t) => [t.id, t]))

export const isChart = (type) => Boolean(TYPES_BY_ID[type]?.chart)

export function axisLabels(type) {
  return isChart(type) ? CHART_AXIS_LABELS : AXIS_LABELS
}

export const DEFAULT_OPTIONS = {
  showDimensionLabels: true,
  hideEmptyRows: false,
  hideEmptyColumns: false,
  // Pivot tables only: a Total column (across Columns) and a Total row
  // (across Rows), computed by the server so ratios stay right.
  rowTotals: false,
  columnTotals: false,
  decimals: 'auto', // 'auto' | 0 | 1 | 2
  // Charts only.
  showDataLabels: false,
  sortOrder: 'none', // 'none' | 'asc' | 'desc'
  targetValue: null, // number, e.g. a monthly sales target
  targetLabel: 'Target',
}

export const FIXED_DIMENSION_LABELS = { dx: 'Data', pe: 'Period', ou: 'Stores' }
export const FIXED_DIMENSIONS = ['dx', 'pe', 'ou']
export const TOTAL = '__total'

export const initialConfig = {
  version: 1,
  type: 'PIVOT_TABLE',
  columns: ['dx'],
  rows: ['pe'],
  filters: ['ou'],
  items: { dx: [], pe: ['LAST_12_MONTHS'], ou: ['FIRM'] },
  options: DEFAULT_OPTIONS,
}

// What a first visit shows, so the screen opens on real numbers.
export const STARTER_METRICS = ['sales.net', 'sales.count', 'sales.avg_sale', 'profit.gross', 'profit.margin']

export function starterConfig(metricIds, storeId) {
  const dx = STARTER_METRICS.filter((id) => metricIds.includes(id))
  return {
    ...initialConfig,
    items: { ...initialConfig.items, dx, ou: [storeId || 'FIRM'] },
    options: { ...DEFAULT_OPTIONS, columnTotals: true },
  }
}

export function axisOf(config, dimId) {
  return AXES.find((axis) => config[axis].includes(dimId)) ?? null
}

// Why `dim` can't go on `axis`, or null if it can.
export function placementError(dim, axis) {
  if (!dim) return null
  if (dim.filter_only && axis !== 'filters') return `${dim.label} can only be used as a filter.`
  return null
}

function withoutDim(config, dimId) {
  const out = { ...config }
  for (const axis of AXES) out[axis] = config[axis].filter((d) => d !== dimId)
  return out
}

export function configReducer(state, action) {
  switch (action.type) {
    case 'SET_TYPE':
      return { ...state, type: action.visType }

    case 'SET_ITEMS':
      return { ...state, items: { ...state.items, [action.dimId]: action.items } }

    // Put a dimension on an axis at `index` (end when omitted). Moving within
    // the same axis reorders it.
    case 'MOVE_DIMENSION': {
      const { dimId, axis } = action
      const next = withoutDim(state, dimId)
      const list = [...next[axis]]
      let index = action.index ?? list.length
      const from = state[axis].indexOf(dimId)
      if (from !== -1 && from < index) index -= 1
      list.splice(Math.max(0, Math.min(index, list.length)), 0, dimId)
      next[axis] = list
      return next
    }

    // Take a dimension off the layout. Its selected items are kept, so adding
    // it back restores the selection.
    case 'REMOVE_DIMENSION':
      return withoutDim(state, action.dimId)

    case 'SET_OPTIONS':
      return { ...state, options: { ...state.options, ...action.options } }

    case 'LOAD':
      return {
        ...initialConfig,
        ...action.config,
        options: { ...DEFAULT_OPTIONS, ...action.config?.options },
      }

    case 'RESET':
      return initialConfig

    default:
      return state
  }
}

// ── query ────────────────────────────────────────────────────────────────────

// Returns { error } when the layout can't be queried yet, else { params }
// (URLSearchParams) for /api/analytics/query/. Dimensions are sent columns
// first, then rows, so the response's meta columns follow the layout.
export function buildQuery(config, dimensionsById) {
  const label = (id) => FIXED_DIMENSION_LABELS[id] ?? dimensionsById[id]?.label ?? id
  const items = (id) => config.items[id] ?? []

  if (!axisOf(config, 'dx') || items('dx').length === 0) {
    return { error: 'Choose at least one data item.' }
  }
  if (config.filters.includes('dx') && items('dx').length > 1) {
    return { error: 'Data in Filter can hold only one item. Choose one, or move Data to another axis.' }
  }
  if (!axisOf(config, 'pe') || items('pe').length === 0) {
    return { error: 'Choose at least one period.' }
  }

  const params = new URLSearchParams()
  for (const id of [...config.columns, ...config.rows]) {
    const dim = dimensionsById[id]
    if (dim?.filter_only) return { error: `${label(id)} can only be used as a filter.` }
    // Dynamic dimensions without a selection show every item; the fixed ones
    // need an explicit selection.
    if (FIXED_DIMENSIONS.includes(id) && items(id).length === 0) {
      return { error: `Choose at least one item for ${label(id)}.` }
    }
    params.append('dimension', `${id}:${items(id).join(';')}`)
  }
  for (const id of config.filters) {
    // The API only takes Data as a dimension; with its single item it adds
    // no breakdown, and the pivot ignores dimensions off the layout.
    if (id === 'dx') {
      params.append('dimension', `dx:${items('dx').join(';')}`)
      continue
    }
    // An empty filter restricts nothing, so it is left out of the query.
    if (items(id).length === 0) continue
    params.append('filter', `${id}:${items(id).join(';')}`)
  }
  for (const dims of totalSpecs(config)) params.append('total', dims.join(';'))
  return { params }
}

// The `total` groups a pivot table's totals options need: the Total column
// collapses the column dimensions, the Total row the row dimensions, and
// the corner both. Data is never totalled: its items are different measures.
export function totalSpecs(config) {
  if (config.type !== 'PIVOT_TABLE') return []
  const cols = config.columns.filter((d) => d !== 'dx')
  const rows = config.rows.filter((d) => d !== 'dx')
  const { rowTotals, columnTotals } = config.options ?? {}
  const out = []
  if (rowTotals && cols.length) out.push(cols)
  if (columnTotals && rows.length) out.push(rows)
  if (rowTotals && columnTotals && cols.length && rows.length) out.push([...cols, ...rows])
  return out
}

// ── chart layout rules ──────────────────────────────────────────────────────

/**
 * What stops `config.type` drawing the current layout, or null if nothing:
 * { message, fixed, fixDescription }. `fixed` is the config rearranged to fit
 * (extra dimensions moved to Filter), which the screen offers as an auto-fix.
 */
export function layoutProblem(config, dimensionLabel) {
  const type = TYPES_BY_ID[config.type]
  if (!type?.chart) return null
  const { columns, rows } = config
  const dxCount = config.items.dx?.length ?? 0

  let message = null
  if (config.type === 'SINGLE_VALUE') {
    const ok = columns.length === 1 && columns[0] === 'dx' && rows.length === 0 && dxCount <= 1
    if (!ok) {
      message = 'A single value shows one number: Series takes only Data, with one data item, and every other dimension goes in Filter.'
    }
  } else if (type.category === 0) {
    if (columns.length !== 1 || rows.length > 0) {
      message = `A ${type.label.toLowerCase()} takes exactly one dimension in Series and none in Category.`
    }
  } else if (columns.length > type.series || rows.length > type.category || columns.length + rows.length === 0) {
    message = `A ${type.label.toLowerCase()} takes one dimension in Series and at most one in Category; other dimensions go in Filter.`
  }
  if (!message && config.filters.includes('dx') && dxCount > 1) {
    message = 'Data in Filter can hold only one item.'
  }
  if (!message) return null

  const fixed = fixLayout(config)
  const moved = [...config.columns, ...config.rows].filter((d) => fixed.filters.includes(d))
  const parts = []
  if (moved.length) parts.push(`move ${moved.map(dimensionLabel).join(', ')} to Filter`)
  if (fixed.items.dx.length < dxCount) parts.push('keep only the first data item')
  if (fixed.columns[0] !== config.columns[0] && !moved.length) parts.push(`put ${dimensionLabel(fixed.columns[0])} in Series`)
  return { message, fixed, fixDescription: parts.join(' and ') || 'rearrange the layout' }
}

function fixLayout(config) {
  const type = TYPES_BY_ID[config.type]
  const dxItems = config.items.dx ?? []
  let onAxes = [...config.columns, ...config.rows]
  let items = config.items

  let kept
  if (config.type === 'SINGLE_VALUE') {
    kept = ['dx']
    if (dxItems.length > 1) items = { ...items, dx: dxItems.slice(0, 1) }
  } else {
    const slots = type.series + type.category
    // Data with several items can't be a filter, so it keeps an axis.
    if (dxItems.length > 1 && !onAxes.slice(0, slots).includes('dx')) {
      onAxes = ['dx', ...onAxes.filter((d) => d !== 'dx')]
    }
    if (onAxes.length === 0) onAxes = ['dx']
    kept = onAxes.slice(0, slots)
  }

  return {
    ...config,
    items,
    columns: kept.slice(0, 1),
    rows: kept.slice(1),
    filters: [
      ...onAxes.filter((d) => !kept.includes(d)),
      ...config.filters.filter((d) => !kept.includes(d)),
    ],
  }
}

// ── periods ──────────────────────────────────────────────────────────────────

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]
const MON = MONTHS.map((m) => m.slice(0, 3))
const pad = (n) => String(n).padStart(2, '0')
const isoDay = (d) => `${d.getUTCFullYear()}${pad(d.getUTCMonth() + 1)}${pad(d.getUTCDate())}`

export const FIXED_PERIOD_TYPES = [
  { id: 'DAY', label: 'Day' },
  { id: 'WEEK', label: 'Week' },
  { id: 'MONTH', label: 'Month' },
  { id: 'QUARTER', label: 'Quarter' },
  { id: 'YEAR', label: 'Year' },
]

// Monday of ISO week 1 of `year`, as a UTC date.
function isoWeekOne(year) {
  const jan4 = new Date(Date.UTC(year, 0, 4))
  return new Date(Date.UTC(year, 0, 4 - ((jan4.getUTCDay() + 6) % 7)))
}

function weeksInYear(year) {
  return Math.round((isoWeekOne(year + 1) - isoWeekOne(year)) / (7 * 864e5))
}

function weekStart(year, week) {
  const d = isoWeekOne(year)
  d.setUTCDate(d.getUTCDate() + (week - 1) * 7)
  return d
}

// Mirrors analytics/periods.py `period_label`.
export function periodLabel(id) {
  let m
  if ((m = /^(\d{4})$/.exec(id))) return m[1]
  if ((m = /^(\d{4})Q([1-4])$/.exec(id))) return `Q${m[2]} ${m[1]}`
  if ((m = /^(\d{4})W(\d{2})$/.exec(id))) {
    const start = weekStart(Number(m[1]), Number(m[2]))
    const end = new Date(start)
    end.setUTCDate(end.getUTCDate() + 6)
    return `Week ${Number(m[2])} ${m[1]} (${start.getUTCDate()} ${MON[start.getUTCMonth()]} – ${end.getUTCDate()} ${MON[end.getUTCMonth()]})`
  }
  if ((m = /^(\d{4})(0[1-9]|1[0-2])$/.exec(id))) return `${MONTHS[Number(m[2]) - 1]} ${m[1]}`
  if ((m = /^(\d{4})(\d{2})(\d{2})$/.exec(id))) return `${Number(m[3])} ${MON[Number(m[2]) - 1]} ${m[1]}`
  return id
}

function daysOf(year, month) {
  const out = []
  const d = new Date(Date.UTC(year, month - 1, 1))
  while (d.getUTCMonth() === month - 1) {
    out.push(isoDay(d))
    d.setUTCDate(d.getUTCDate() + 1)
  }
  return out
}

// Concrete period ids of `type` within `year` (and `month`, for days).
export function fixedPeriods(type, year, month = 1) {
  switch (type) {
    case 'YEAR':
      return [String(year)]
    case 'QUARTER':
      return [1, 2, 3, 4].map((q) => `${year}Q${q}`)
    case 'MONTH':
      return MONTHS.map((_, i) => `${year}${pad(i + 1)}`)
    case 'WEEK':
      return Array.from({ length: weeksInYear(year) }, (_, i) => `${year}W${pad(i + 1)}`)
    case 'DAY':
      return daysOf(year, month)
    default:
      return []
  }
}

export { MONTHS }

/**
 * The next level down of a concrete period, for drilling into a cell: a
 * year into months, a quarter into months, a month or week into days. Null
 * for a day, or for anything that isn't a concrete period.
 */
export function subPeriods(id) {
  let m
  if ((m = /^(\d{4})$/.exec(id))) return fixedPeriods('MONTH', Number(m[1]))
  if ((m = /^(\d{4})Q([1-4])$/.exec(id))) {
    const q = Number(m[2])
    return [1, 2, 3].map((i) => `${m[1]}${pad(3 * (q - 1) + i)}`)
  }
  if ((m = /^(\d{4})W(\d{2})$/.exec(id))) {
    const d = weekStart(Number(m[1]), Number(m[2]))
    return Array.from({ length: 7 }, () => {
      const day = isoDay(d)
      d.setUTCDate(d.getUTCDate() + 1)
      return day
    })
  }
  if ((m = /^(\d{4})(0[1-9]|1[0-2])$/.exec(id))) return daysOf(Number(m[1]), Number(m[2]))
  return null
}

// ── org units ────────────────────────────────────────────────────────────────

// The `ou` tree flattened depth-first, with `depth` for indentation.
export function flattenTree(nodes, depth = 0, out = []) {
  for (const node of nodes ?? []) {
    out.push({ id: node.id, label: node.label, depth, level: node.level })
    flattenTree(node.children, depth + 1, out)
  }
  return out
}
