// "Download" for the Data Visualizer: the pivot table as CSV or XLSX, the
// chart as PNG. Everything is built in the browser from what is already on
// screen.

// ── table grid ───────────────────────────────────────────────────────────────

// The pivot flattened to a grid: one header row per column dimension (labels
// repeated rather than merged, so every column is self-describing), then one
// row per row combo. Values stay raw numbers.
export function pivotGrid(pivot, dimensionLabel) {
  const { colDims, rowDims, colCombos, rowCombos, cell, label, isPlaceholder } = pivot
  // The row dimensions' names head their columns on the last header row.
  const grid = colDims.map((dim, level) => [
    ...rowDims.map((d) => (level === colDims.length - 1 && !isPlaceholder(d) ? dimensionLabel(d) : '')),
    ...colCombos.map((combo) => label(dim, combo[level])),
  ])
  for (const rowCombo of rowCombos) {
    grid.push([
      ...rowDims.map((d, level) => label(d, rowCombo[level])),
      ...colCombos.map((colCombo) => {
        const c = cell(colCombo, rowCombo)
        return !c || c.value === null || c.value === undefined ? '' : Number(c.value)
      }),
    ])
  }
  return grid
}

// ── CSV ──────────────────────────────────────────────────────────────────────

function csvField(v) {
  if (typeof v === 'number') return String(v)
  let s = String(v ?? '')
  // A label starting with = + - @ would run as a formula in Excel.
  if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

export function buildCsv(grid) {
  return grid.map((row) => row.map(csvField).join(',')).join('\r\n')
}

export function downloadCsv(grid, filename) {
  // The BOM makes Excel read the file as UTF-8.
  saveBlob(new Blob(['﻿', buildCsv(grid)], { type: 'text/csv;charset=utf-8' }), `${filename}.csv`)
}

// ── XLSX ─────────────────────────────────────────────────────────────────────
// A one-sheet workbook with inline strings, zipped uncompressed ("stored"):
// small tables don't justify a spreadsheet library.

const XML_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'

function xmlText(s) {
  return String(s)
    // Control characters are not allowed in XML 1.0.
    // eslint-disable-next-line no-control-regex
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

function columnName(i) {
  let name = ''
  for (let n = i + 1; n > 0; n = Math.floor((n - 1) / 26)) name = String.fromCharCode(65 + ((n - 1) % 26)) + name
  return name
}

function sheetXml(grid) {
  const rows = grid.map((row, r) => {
    const cells = row.map((v, c) => {
      const ref = `${columnName(c)}${r + 1}`
      if (typeof v === 'number' && Number.isFinite(v)) return `<c r="${ref}"><v>${v}</v></c>`
      if (v === '' || v === null || v === undefined) return ''
      return `<c r="${ref}" t="inlineStr"><is><t xml:space="preserve">${xmlText(v)}</t></is></c>`
    })
    return `<row r="${r + 1}">${cells.join('')}</row>`
  })
  return `${XML_HEAD}<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>${rows.join('')}</sheetData></worksheet>`
}

// The workbook's files by path, before zipping.
export function xlsxParts(grid, sheetName = 'Analytics') {
  const ns = 'http://schemas.openxmlformats.org'
  const files = {
    '[Content_Types].xml': `${XML_HEAD}<Types xmlns="${ns}/package/2006/content-types">`
      + '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
      + '<Default Extension="xml" ContentType="application/xml"/>'
      + '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
      + '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
      + '</Types>',
    '_rels/.rels': `${XML_HEAD}<Relationships xmlns="${ns}/package/2006/relationships">`
      + `<Relationship Id="rId1" Type="${ns}/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>`
      + '</Relationships>',
    'xl/workbook.xml': `${XML_HEAD}<workbook xmlns="${ns}/spreadsheetml/2006/main" xmlns:r="${ns}/officeDocument/2006/relationships">`
      + `<sheets><sheet name="${xmlText(sheetName)}" sheetId="1" r:id="rId1"/></sheets></workbook>`,
    'xl/_rels/workbook.xml.rels': `${XML_HEAD}<Relationships xmlns="${ns}/package/2006/relationships">`
      + `<Relationship Id="rId1" Type="${ns}/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>`
      + '</Relationships>',
    'xl/worksheets/sheet1.xml': sheetXml(grid),
  }
  return files
}

export function buildXlsx(grid, sheetName) {
  return new Blob([zipStored(Object.entries(xlsxParts(grid, sheetName)))], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
}

export function downloadXlsx(grid, filename, sheetName) {
  saveBlob(buildXlsx(grid, sheetName), `${filename}.xlsx`)
}

let crcTable
export function crc32(bytes) {
  if (!crcTable) {
    crcTable = new Uint32Array(256)
    for (let n = 0; n < 256; n++) {
      let c = n
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
      crcTable[n] = c >>> 0
    }
  }
  let crc = 0xffffffff
  for (const b of bytes) crc = crcTable[(crc ^ b) & 0xff] ^ (crc >>> 8)
  return (crc ^ 0xffffffff) >>> 0
}

// A ZIP archive with every entry stored uncompressed.
function zipStored(entries) {
  const enc = new TextEncoder()
  const parts = []
  const central = []
  let offset = 0
  for (const [name, text] of entries) {
    const nameBytes = enc.encode(name)
    const data = enc.encode(text)
    const crc = crc32(data)
    // version, flags (UTF-8 names), method 0, time, date (1980-01-01), crc, sizes, name length, extra length
    const common = [[20, 2], [0x0800, 2], [0, 2], [0, 2], [0x21, 2], [crc, 4], [data.length, 4], [data.length, 4], [nameBytes.length, 2], [0, 2]]
    const local = le([[0x04034b50, 4], ...common])
    parts.push(local, nameBytes, data)
    central.push(le([[0x02014b50, 4], [20, 2], ...common, [0, 2], [0, 2], [0, 2], [0, 4], [offset, 4]]), nameBytes)
    offset += local.length + nameBytes.length + data.length
  }
  const centralSize = central.reduce((n, p) => n + p.length, 0)
  const end = le([[0x06054b50, 4], [0, 2], [0, 2], [entries.length, 2], [entries.length, 2], [centralSize, 4], [offset, 4], [0, 2]])
  return new Blob([...parts, ...central, end])
}

// Little-endian fields: [[value, byteCount], ...].
function le(fields) {
  const out = new Uint8Array(fields.reduce((n, [, size]) => n + size, 0))
  const view = new DataView(out.buffer)
  let at = 0
  for (const [value, size] of fields) {
    if (size === 2) view.setUint16(at, value, true)
    else view.setUint32(at, value, true)
    at += size
  }
  return out
}

// ── PNG ──────────────────────────────────────────────────────────────────────

const PNG_SCALE = 2
const FONT = 'Poppins, system-ui, sans-serif'

async function savePng(canvas, filename) {
  const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'))
  if (!blob) throw new Error('The chart image could not be drawn.')
  saveBlob(blob, `${filename}.png`)
}

function sheet(width, height) {
  const canvas = document.createElement('canvas')
  canvas.width = width * PNG_SCALE
  canvas.height = height * PNG_SCALE
  const ctx = canvas.getContext('2d')
  ctx.scale(PNG_SCALE, PNG_SCALE)
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, width, height)
  ctx.textBaseline = 'top'
  return { canvas, ctx }
}

/**
 * Draws the chart's canvas (legend included, Chart.js draws it) onto a white
 * sheet under a title and subtitle.
 */
export async function downloadChartPng(chartCanvas, { title, subtitle, filename }) {
  const { width, height } = chartCanvas.getBoundingClientRect()
  const pad = 24
  const headH = (title ? 28 : 0) + (subtitle ? 20 : 0) + (title || subtitle ? 12 : 0)
  const { canvas, ctx } = sheet(width + pad * 2, height + headH + pad * 2)
  let y = pad
  if (title) {
    ctx.fillStyle = '#1B2333'
    ctx.font = `600 16px ${FONT}`
    ctx.fillText(title, pad, y, width)
    y += 28
  }
  if (subtitle) {
    ctx.fillStyle = '#5B6472'
    ctx.font = `12px ${FONT}`
    ctx.fillText(subtitle, pad, y, width)
    y += 20
  }
  if (title || subtitle) y += 12
  ctx.drawImage(chartCanvas, pad, y, width, height)
  await savePng(canvas, filename)
}

/** A single value drawn as its own card: name, filters, the number. */
export async function downloadSingleValuePng({ name, subtitle, text, status, filename }) {
  const width = 600
  const { canvas, ctx } = sheet(width, 260)
  ctx.textAlign = 'center'
  ctx.fillStyle = '#1B2333'
  ctx.font = `600 18px ${FONT}`
  ctx.fillText(name, width / 2, 36, width - 48)
  if (subtitle) {
    ctx.fillStyle = '#5B6472'
    ctx.font = `13px ${FONT}`
    ctx.fillText(subtitle, width / 2, 66, width - 48)
  }
  ctx.fillStyle = '#0B3D7A'
  ctx.font = `700 64px ${FONT}`
  ctx.fillText(text || '–', width / 2, 104, width - 48)
  if (status) {
    ctx.fillStyle = status.color
    ctx.font = `600 15px ${FONT}`
    ctx.fillText(status.text, width / 2, 196, width - 48)
  }
  await savePng(canvas, filename)
}

// ── shared ───────────────────────────────────────────────────────────────────

function saveBlob(blob, name) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function downloadFilename() {
  const today = new Date().toLocaleDateString('en-CA', { timeZone: 'Africa/Dar_es_Salaam' })
  return `analytics-${today}`
}
