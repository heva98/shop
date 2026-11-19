import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { findProduct, sellOptions } from '../../offline/catalog.js'
import { AMOX, MILK, SUGAR, snapshot } from '../../offline/fixtures.js'
import {
  addLine, buildSaleRecord, canAddOne, checkout, NO_RX, repriceCart, setLineQty, stockInCart, unsentCreditByCustomer,
} from './cart.js'

const snap = snapshot()
const option = (id, i = 0) => sellOptions(snap, [findProduct(snap, id)])[i]
const sugar = option(SUGAR)
const sugarBale = option(SUGAR, 1)

const CASH = { id: 'cash', name: 'Cash', implementation: 'cash' }
const MPESA = { id: 'mpesa', name: 'M-Pesa', implementation: 'mobile_money' }

/** checkout() with a cash sale and nothing entered, overridden by `inputs`. */
const totals = (cart, inputs = {}) => checkout({
  cart, discountInput: '', isManager: false, discountLimit: 10, approver: { username: '', password: '' },
  customer: null, onCredit: false, creditInput: '', unsentCredit: {}, method: CASH, isCash: true,
  tendered: '', reference: '', busy: false, offline: false, ...inputs,
})

describe('adding to the cart', () => {
  it('adds one, then counts up the same line', () => {
    const cart = addLine(addLine([], sugar), sugar)
    assert.equal(cart.length, 1)
    assert.equal(cart[0].qty, 2)
  })

  it('never puts more in the cart than the stock left, across every unit the product is sold in', () => {
    let cart = addLine(addLine([], sugarBale), sugarBale) // 20 of 25 pieces
    assert.equal(stockInCart(cart, SUGAR), 20)
    assert.equal(addLine(cart, sugarBale), cart, 'a third bale needs 30')
    for (let i = 0; i < 5; i++) cart = addLine(cart, sugar)
    assert.equal(stockInCart(cart, SUGAR), 25)
    assert.equal(addLine(cart, sugar), cart)
    assert.equal(canAddOne(cart, cart[0]), false)
  })
})

describe('changing a quantity', () => {
  const cart = [{ ...sugarBale, qty: 1 }, { ...sugar, qty: 3 }]

  it('caps it at the stock the product\'s other lines leave', () => {
    assert.equal(setLineQty(cart, sugar.key, 99).find((l) => l.key === sugar.key).qty, 15)
    assert.equal(setLineQty(cart, sugarBale.key, 99).find((l) => l.key === sugarBale.key).qty, 2)
  })

  it('removes the line at zero or below', () => {
    assert.deepEqual(setLineQty(cart, sugar.key, 0).map((l) => l.key), [sugarBale.key])
    assert.deepEqual(setLineQty(cart, sugar.key, -4).map((l) => l.key), [sugarBale.key])
  })
})

describe('repriceCart', () => {
  it('re-reads prices from a fresh snapshot and drops what can no longer be priced', () => {
    const fresh = snapshot({
      prices: [{ product: SUGAR, uom: null, unit_price: '3500.00', regular_price: '3500.00', promotion: null }],
    })
    const repriced = repriceCart([{ ...sugar, qty: 2 }, { ...sugarBale, qty: 1 }], fresh, {})
    assert.deepEqual(repriced.map((l) => [l.key, l.unitPrice, l.qty]), [[sugar.key, 3500, 2]])
  })
})

describe('checkout totals', () => {
  const cart = [{ ...sugar, qty: 2 }, { ...option(MILK), qty: 2 }] // 6,400 standard-rated + 3,000 exempt

  it('takes VAT as the 18/118 share of standard-rated lines only', () => {
    const t = totals(cart)
    assert.equal(t.gross, 9400)
    assert.equal(Math.round(t.vat * 100) / 100, Math.round(6400 * 18 / 118 * 100) / 100)
  })

  it('shares a sale discount into the VAT, and never lets it pass the gross', () => {
    const t = totals(cart, { discountInput: '940' })
    assert.equal(t.total, 8460)
    assert.ok(Math.abs(t.vat - 6400 * (8460 / 9400) * 18 / 118) < 1e-9)
    assert.equal(totals(cart, { discountInput: '1,000,000', isManager: true }).total, 0)
  })

  it('needs a manager above the cashier\'s discount limit, and the connection to approve it', () => {
    assert.equal(totals(cart, { discountInput: '940' }).needsApproval, false, 'exactly 10% is allowed')
    const over = totals(cart, { discountInput: '941', tendered: '10000' })
    assert.deepEqual([over.needsApproval, over.canComplete], [true, false])
    const approved = { username: 'manager', password: 'secret' }
    assert.equal(totals(cart, { discountInput: '941', tendered: '10000', approver: approved }).canComplete, true)
    assert.equal(totals(cart, { discountInput: '941', tendered: '10000', approver: approved, offline: true }).canComplete, false)
    assert.equal(totals(cart, { discountInput: '941', isManager: true }).needsApproval, false)
  })

  it('cash must cover what is payable; other methods need a reference', () => {
    assert.equal(totals(cart, { tendered: '9,399' }).canComplete, false)
    const paid = totals(cart, { tendered: '10 000' })
    assert.deepEqual([paid.canComplete, paid.change], [true, 600])
    assert.equal(totals(cart, { method: MPESA, isCash: false }).canComplete, false)
    assert.equal(totals(cart, { method: MPESA, isCash: false, reference: ' QK7 ' }).canComplete, true)
  })

  it('puts all (blank) or part of the sale on credit, within the limit, counting unsent credit sales', () => {
    const customer = { id: 'c1', name: 'Asha', owing: '1000', credit_limit: '5000' }
    const all = totals(cart, { customer, onCredit: true, unsentCredit: { c1: 500 } })
    assert.deepEqual([all.creditAmount, all.payable, all.owing, all.overLimit, all.canComplete], [9400, 0, 1500, true, false])
    const part = totals(cart, { customer, onCredit: true, creditInput: '3000', unsentCredit: { c1: 500 }, tendered: '6400' })
    assert.deepEqual([part.creditAmount, part.payable, part.overLimit, part.canComplete], [3000, 6400, false, true])
    assert.equal(totals(cart, { onCredit: true, tendered: '10000' }).canComplete, false, 'credit needs a customer')
  })

  it('cannot complete an empty cart or while busy', () => {
    assert.equal(totals([], { tendered: '0' }).canComplete, false)
    assert.equal(totals(cart, { tendered: '10000', busy: true }).canComplete, false)
  })

  it('asks for the prescription only when the cart has medicine that needs one', () => {
    assert.equal(totals(cart).needsRx, false)
    assert.equal(totals([{ ...option(AMOX), qty: 1 }]).needsRx, true)
  })
})

describe('buildSaleRecord', () => {
  const cart = [{ ...sugarBale, qty: 1 }, { ...option(AMOX), qty: 2 }]
  const shift = { id: 'sh1', cashier_name: 'Juma' }
  const build = (inputs = {}, extra = {}) => {
    const sums = totals(cart, inputs)
    return buildSaleRecord({
      id: 'sale-1', now: '2026-11-19T10:00:00.000Z', userId: 7, storeId: 's1', shift, cart,
      method: inputs.method ?? CASH, isCash: inputs.isCash ?? true, reference: inputs.reference ?? '',
      customer: inputs.customer ?? null, rx: NO_RX, totals: sums, ...extra,
    })
  }

  it('sends what the till charged, and keeps the stock it took in stock units', () => {
    const record = build({ tendered: '35000' })
    assert.deepEqual(record.payload.items, [
      { product: SUGAR, qty: 1, uom: sugarBale.uomId, unit_price: 30000 },
      { product: AMOX, qty: 2, uom: null, unit_price: 500 },
    ])
    assert.deepEqual(record.stock, [{ product: SUGAR, qty: 10 }, { product: AMOX, qty: 2 }])
    assert.deepEqual([record.status, record.shiftId, record.payload.amount_tendered, record.receipt.change_due], ['pending', 'sh1', 35000, 4000])
  })

  it('sends the prescription, trimmed, only when the cart needs one', () => {
    const rx = { patient_name: ' Asha ', prescriber_name: '', prescription_ref: ' R1 ' }
    const record = build({ tendered: '35000' }, { rx })
    assert.deepEqual([record.payload.patient_name, record.payload.prescription_ref, record.receipt.patient_name], ['Asha', 'R1', 'Asha'])
    const noRx = buildSaleRecord({
      id: 'x', now: 'n', userId: 7, storeId: 's1', shift, cart: [{ ...sugar, qty: 1 }], method: CASH, isCash: true,
      reference: '', customer: null, rx, totals: totals([{ ...sugar, qty: 1 }], { tendered: '3200' }),
    })
    assert.equal('patient_name' in noRx.payload, false)
  })

  it('a non-cash sale carries its reference and is taken for exactly what is payable', () => {
    const record = build({ method: MPESA, isCash: false, reference: ' QK7 ' })
    assert.deepEqual([record.payload.payment_reference, record.payload.amount_tendered, record.receipt.amount_tendered], ['QK7', null, 31000])
  })
})

describe('unsentCreditByCustomer', () => {
  it('adds up credit still on this till per customer', () => {
    const outbox = [
      { payload: { customer: 'c1', credit_amount: 1000 } },
      { payload: { customer: 'c1', credit_amount: '500' } },
      { payload: { customer: null, credit_amount: 0 } },
    ]
    assert.deepEqual(unsentCreditByCustomer(outbox), { c1: 1500 })
  })
})
