// Pure helpers behind DataTable, kept free of JSX so `node --test` can run them.

/** The value a column sorts by: its `sortValue(row)`, else `row[column.key]`. */
export function sortValueOf(column, row) {
  return column.sortValue ? column.sortValue(row) : row?.[column.key]
}

const isBlank = (v) => v == null || v === '' || (typeof v === 'number' && Number.isNaN(v))

/** Compares two sort values: numbers and dates numerically, strings with
 * the locale's collation and natural digit order ("Item 2" < "Item 10"). */
export function compareValues(a, b, collator) {
  if (a instanceof Date) a = a.getTime()
  if (b instanceof Date) b = b.getTime()
  if (typeof a === 'number' && typeof b === 'number') return a - b
  if (typeof a === 'boolean' && typeof b === 'boolean') return Number(a) - Number(b)
  return collator.compare(String(a), String(b))
}

/** Rows ordered by `sort` = {key, direction: 'asc' | 'desc'}, without
 * mutating the input. Blank values (null, '', NaN) always go last whichever
 * way the column is sorted, and ties keep their original order. */
export function sortRows(rows, columns, sort, locale) {
  if (!sort || !Array.isArray(rows)) return rows
  const column = columns.find((c) => c.key === sort.key)
  if (!column) return rows
  const collator = new Intl.Collator(locale, { numeric: true, sensitivity: 'base' })
  const sign = sort.direction === 'desc' ? -1 : 1
  return rows
    .map((row, index) => ({ row, index, value: sortValueOf(column, row) }))
    .sort((x, y) => {
      const xBlank = isBlank(x.value)
      const yBlank = isBlank(y.value)
      if (xBlank || yBlank) return xBlank === yBlank ? x.index - y.index : xBlank ? 1 : -1
      return sign * compareValues(x.value, y.value, collator) || x.index - y.index
    })
    .map((entry) => entry.row)
}

/** The sort after clicking `key`'s header: a new column starts in its
 * `firstDirection` (numbers usually read best largest-first), the same
 * column flips direction. */
export function nextSort(sort, key, firstDirection = 'asc') {
  if (sort?.key !== key) return { key, direction: firstDirection }
  return { key, direction: sort.direction === 'asc' ? 'desc' : 'asc' }
}

/** aria-sort value for a header cell. */
export function ariaSort(sort, key) {
  if (sort?.key !== key) return 'none'
  return sort.direction === 'desc' ? 'descending' : 'ascending'
}

/** A row's React key from `rowKey` (a property name or a function). */
export function rowKeyOf(rowKey, row, index) {
  if (typeof rowKey === 'function') return rowKey(row, index)
  const key = row?.[rowKey]
  return key ?? index
}
