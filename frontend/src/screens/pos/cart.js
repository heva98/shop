// The till's cart rules, apart from the screen (Pos.jsx): what may go in
// the cart given the stock, what the sale comes to (discount, VAT, credit,
// change), whether it can be completed, and the record that is saved and
// sent. Pure functions over plain values, tested in cart.test.js.
//
// A cart line is a sell option (offline/catalog.js sellOptions) plus `qty`,
// in the unit it is sold in; `perUnit` stock units leave the shelf per one.

import { findProduct, sellOptions } from '../../offline/catalog.js'
import { parseAmount } from './format.js'

export const NO_RX = { patient_name: '', prescriber_name: '', prescription_ref: '' }

/** Cart lines re-priced (and their stock re-read) from a fresh snapshot;
 * a line whose product can no longer be priced is dropped. */
export function repriceCart(lines, snapshot, unsynced) {
  return lines.flatMap((line) => {
    const product = findProduct(snapshot, line.productId)
    const option = product && sellOptions(snapshot, [product], unsynced).find((o) => o.key === line.key)
    return option && option.unitPrice !== null ? [{ ...option, qty: line.qty }] : []
  })
}

/** Stock units of a product already in the cart, across all the units it's sold in. */
export const stockInCart = (lines, productId) => lines.filter((l) => l.productId === productId).reduce((sum, l) => sum + l.qty * l.perUnit, 0)

/** The cart with one more of `option`; unchanged when the stock left
 * doesn't cover it. */
export function addLine(cart, option) {
  if (stockInCart(cart, option.productId) + option.perUnit > option.stockAvailable + 1e-9) return cart
  const existing = cart.find((l) => l.key === option.key)
  if (existing) return cart.map((l) => (l.key === option.key ? { ...l, qty: l.qty + 1 } : l))
  return [...cart, { ...option, qty: 1 }]
}

/** The cart with the line `key` set to `qty`, kept within the stock left
 * after the product's other lines; 0 or less removes it. */
export function setLineQty(cart, key, qty) {
  const line = cart.find((l) => l.key === key)
  const others = stockInCart(cart, line.productId) - line.qty * line.perUnit
  const max = Math.floor((line.stockAvailable - others) / line.perUnit + 1e-9)
  return cart.map((l) => (l.key === key ? { ...l, qty: Math.min(Math.max(qty, 0), max) } : l)).filter((l) => l.qty > 0)
}

export const canAddOne = (cart, line) => stockInCart(cart, line.productId) + line.perUnit <= line.stockAvailable + 1e-9

/** {customer id: amount} of credit sales still on this till: not yet in
 * the snapshot's balances. */
export function unsentCreditByCustomer(outbox) {
  return outbox.reduce((acc, r) => {
    if (r.payload.customer) acc[r.payload.customer] = (acc[r.payload.customer] ?? 0) + Number(r.payload.credit_amount || 0)
    return acc
  }, {})
}

/** What the sale comes to, and whether it can be completed, from the cart
 * and what the cashier has entered (amounts as typed). */
export function checkout({
  cart, discountInput, isManager, discountLimit, approver, customer, onCredit, creditInput, unsentCredit,
  method, isCash, tendered, reference, busy, offline,
}) {
  const gross = cart.reduce((sum, l) => sum + l.unitPrice * l.qty, 0)
  const discount = Math.min(parseAmount(discountInput), gross)
  const total = gross - discount
  // The discount is shared over the lines on the server, so VAT shrinks with it.
  const standardGross = cart.reduce((sum, l) => sum + (l.vatClass === 'standard' ? l.unitPrice * l.qty : 0), 0)
  const vat = gross > 0 ? standardGross * (total / gross) * 18 / 118 : 0
  const needsApproval = !isManager && discount > 0 && discount * 100 > gross * discountLimit + 1e-9
  const approvalReady = !needsApproval || (approver.username.trim() && approver.password)
  const creditAmount = onCredit && customer
    ? Math.min(creditInput.trim() === '' ? total : parseAmount(creditInput), total) : 0
  const owing = customer ? Number(customer.owing) + (unsentCredit[customer.id] ?? 0) : 0
  const overLimit = creditAmount > 0 && customer.credit_limit !== null && owing + creditAmount > Number(customer.credit_limit) + 1e-9
  const payable = total - creditAmount
  const tenderedNum = parseAmount(tendered)
  const change = tenderedNum - payable
  // Pharmacies: for prescription-only and controlled medicine the till asks
  // for the patient and prescriber (optional).
  const needsRx = cart.some((l) => l.prescriptionOnly || l.controlled)
  const canComplete = Boolean(cart.length > 0 && method && !busy && approvalReady && !(needsApproval && offline)
    && !(onCredit && (!customer || overLimit))
    && (payable === 0 || (isCash ? tenderedNum >= payable : reference.trim().length > 0)))
  return { gross, discount, total, vat, needsApproval, creditAmount, owing, overLimit, payable, tenderedNum, change, needsRx, canComplete }
}

/** The sale as the till rang it up: the request that records it, and the
 * receipt to show and print until the cloud has numbered it, as the outbox
 * keeps it (offline/outbox.js). `totals` is checkout()'s result. */
export function buildSaleRecord({ id, now, userId, storeId, shift, cart, method, isCash, reference, customer, rx, totals }) {
  const { total, vat, discount, creditAmount, payable, tenderedNum, needsRx } = totals
  const paymentReference = isCash ? '' : reference.trim()
  const payload = {
    id, store: storeId, shift: shift.id, completed_at: now,
    items: cart.map((l) => ({ product: l.productId, qty: l.qty, uom: l.uomId, unit_price: l.unitPrice })),
    payment_method: method.id,
    amount_tendered: isCash && payable > 0 ? tenderedNum : null,
    payment_reference: paymentReference,
    customer: customer?.id ?? null,
    credit_amount: creditAmount,
    discount,
    efd_receipt_no: '',
    ...(needsRx ? { patient_name: rx.patient_name.trim(), prescriber_name: rx.prescriber_name.trim(), prescription_ref: rx.prescription_ref.trim() } : {}),
  }
  const amountTendered = isCash ? (payable > 0 ? tenderedNum : 0) : payable
  const receipt = {
    id, number: null, offline: true, status: 'completed', completed_at: now, cashier_name: shift.cashier_name,
    lines: cart.map((l) => ({
      product: l.productId, product_name: l.name, sell_uom: l.uomId, unit_name: l.unitName,
      sell_qty: l.qty, unit_price: l.unitPrice, amount: l.unitPrice * l.qty, discount: 0,
    })),
    total, vat_total: vat, discount_total: discount, credit_amount: creditAmount, paid_amount: payable,
    customer_name: customer?.name ?? '', customer_phone: customer?.phone ?? '',
    patient_name: needsRx ? rx.patient_name.trim() : '', prescriber_name: needsRx ? rx.prescriber_name.trim() : '',
    prescription_ref: needsRx ? rx.prescription_ref.trim() : '',
    payment_method_name: method.name, payment_reference: paymentReference,
    amount_tendered: amountTendered, change_due: amountTendered - payable, efd_receipt_no: '',
  }
  return {
    id, userId, storeId, shiftId: shift.id, createdAt: now, status: 'pending', error: '',
    payload, receipt, stock: cart.map((l) => ({ product: l.productId, qty: l.qty * l.perUnit })),
  }
}
