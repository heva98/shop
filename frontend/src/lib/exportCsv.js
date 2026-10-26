/** Downloads rows as a CSV file Excel opens directly. `columns` is
 * [{label, value: (row) => any}]. A UTF-8 BOM makes Excel read non-ASCII
 * names (e.g. "—") correctly instead of as mojibake. */
export function downloadCsv(filename, columns, rows) {
  const escape = (v) => {
    const s = v === null || v === undefined ? '' : String(v)
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  const lines = [columns.map((c) => escape(c.label)).join(',')]
  for (const row of rows) lines.push(columns.map((c) => escape(c.value(row))).join(','))
  const blob = new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
