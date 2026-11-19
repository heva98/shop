import { test } from 'node:test'
import assert from 'node:assert/strict'
import { ariaSort, nextSort, rowKeyOf, sortRows } from './dataTable.js'

const columns = [
  { key: 'name' },
  { key: 'qty' },
  { key: 'price', sortValue: (r) => Number(r.price) },
]

test('sorts strings naturally and case-insensitively', () => {
  const rows = [{ name: 'item 10' }, { name: 'Item 2' }, { name: 'apple' }]
  const out = sortRows(rows, columns, { key: 'name', direction: 'asc' }, 'en')
  assert.deepEqual(out.map((r) => r.name), ['apple', 'Item 2', 'item 10'])
})

test('sorts numbers descending and does not mutate the input', () => {
  const rows = [{ qty: 3 }, { qty: 12 }, { qty: 1 }]
  const out = sortRows(rows, columns, { key: 'qty', direction: 'desc' }, 'en')
  assert.deepEqual(out.map((r) => r.qty), [12, 3, 1])
  assert.deepEqual(rows.map((r) => r.qty), [3, 12, 1])
})

test('uses sortValue, so decimal strings from the API sort as numbers', () => {
  const rows = [{ price: '900.00' }, { price: '1500.00' }, { price: '25.50' }]
  const out = sortRows(rows, columns, { key: 'price', direction: 'asc' }, 'en')
  assert.deepEqual(out.map((r) => r.price), ['25.50', '900.00', '1500.00'])
})

test('blank values go last in both directions', () => {
  const rows = [{ qty: null }, { qty: 2 }, { qty: '' }, { qty: 5 }]
  assert.deepEqual(sortRows(rows, columns, { key: 'qty', direction: 'asc' }, 'en').map((r) => r.qty), [2, 5, null, ''])
  assert.deepEqual(sortRows(rows, columns, { key: 'qty', direction: 'desc' }, 'en').map((r) => r.qty), [5, 2, null, ''])
})

test('ties keep their original order (stable)', () => {
  const rows = [{ name: 'a', qty: 1 }, { name: 'b', qty: 1 }, { name: 'c', qty: 0 }]
  const out = sortRows(rows, columns, { key: 'qty', direction: 'desc' }, 'en')
  assert.deepEqual(out.map((r) => r.name), ['a', 'b', 'c'])
})

test('unknown sort key or no sort returns rows unchanged', () => {
  const rows = [{ name: 'b' }, { name: 'a' }]
  assert.equal(sortRows(rows, columns, null, 'en'), rows)
  assert.equal(sortRows(rows, columns, { key: 'missing', direction: 'asc' }, 'en'), rows)
})

test('nextSort starts a new column in its first direction and flips the same one', () => {
  assert.deepEqual(nextSort(null, 'qty', 'desc'), { key: 'qty', direction: 'desc' })
  assert.deepEqual(nextSort({ key: 'qty', direction: 'desc' }, 'qty'), { key: 'qty', direction: 'asc' })
  assert.deepEqual(nextSort({ key: 'qty', direction: 'asc' }, 'name'), { key: 'name', direction: 'asc' })
})

test('ariaSort and rowKeyOf', () => {
  assert.equal(ariaSort({ key: 'a', direction: 'desc' }, 'a'), 'descending')
  assert.equal(ariaSort({ key: 'a', direction: 'asc' }, 'b'), 'none')
  assert.equal(rowKeyOf('id', { id: 7 }, 0), 7)
  assert.equal(rowKeyOf((r) => `x${r.id}`, { id: 7 }, 0), 'x7')
  assert.equal(rowKeyOf('id', {}, 3), 3)
})
