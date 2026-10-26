import { Fragment, useEffect, useMemo, useState } from 'react'
import { Button, Card, Checkbox, Field, Icon, Input, NoticeBox, PageHeader, Radio, Select, Tag } from '../components/ds/index.js'
import PrintArea from '../components/PrintArea.jsx'
import { useApi } from '../hooks/useApi.js'
import { useOutbox, useTill } from '../hooks/useOutbox.js'
import { isTransient } from '../api/client.js'
import { recordFiscalReceipt, voidSale, listAllSales, openShift, closeShift } from '../api/pos.js'
import { discard, placeSale, retryRejected, setUnsentEfdNumber, subscribe, unsyncedStock } from '../offline/outbox.js'
import { findByBarcode, searchTill, sellOptions } from '../offline/till.js'
import { fmt } from '../appData.js'
import { apiErrorText } from '../lib/apiError.js'

const MANAGER_ROLES = ['store_manager', 'entity_admin']

// cashiers type amounts like "10,000" or "10 000"; parseFloat alone would stop at the separator
const parseAmount = (v) => parseFloat(String(v).replace(/[,\s]/g, '')) || 0

// crypto.randomUUID needs a secure context; getRandomValues doesn't.
function newId() {
  if (crypto.randomUUID) return crypto.randomUUID()
  const b = crypto.getRandomValues(new Uint8Array(16))
  b[6] = (b[6] & 0x0f) | 0x40
  b[8] = (b[8] & 0x3f) | 0x80
  const h = [...b].map((x) => x.toString(16).padStart(2, '0')).join('')
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`
}

const offlineNo = (sale) => sale.id.slice(0, 8).toUpperCase()

export default function Pos({ storeId, userId, role, entity, features }) {
  const till = useTill(userId, storeId)
  const outbox = useOutbox()
  const [zReport, setZReport] = useState(null)
  const snapshot = till.snapshot?.store === storeId ? till.snapshot : null
  const store = snapshot?.store_details

  if (!storeId) return <NoticeBox variant="warning" title="No store selected">Select a store to start a sale.</NoticeBox>
  if (zReport) return <ZReport shift={zReport} entity={entity} store={store} onDone={() => setZReport(null)} />
  if (till.loading && !snapshot) return <NoticeBox variant="info">Loading…</NoticeBox>
  if (!snapshot) {
    return till.offline
      ? (
        <NoticeBox variant="warning" title="This till isn't ready to sell offline yet">
          It needs to connect once to save a copy of the catalog, prices and stock. Open the point of sale while online; after that it keeps selling when the connection drops.
        </NoticeBox>
      )
      : <NoticeBox variant="error" title="Could not load the till">{apiErrorText(till.error, 'Try again in a moment.')}</NoticeBox>
  }
  if (!snapshot.shift) return <OpenShift storeId={storeId} offline={till.offline} onOpened={till.refresh} />
  return (
    <Till
      key={snapshot.shift.id} snapshot={snapshot} outbox={outbox} offline={till.offline} refresh={till.refresh}
      userId={userId} storeId={storeId} store={store} entity={entity} role={role} features={features}
      onShiftClosed={(closed) => { setZReport(closed); till.refresh() }}
    />
  )
}

function OpenShift({ storeId, offline, onOpened }) {
  const [openingFloat, setOpeningFloat] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit() {
    setBusy(true); setError('')
    try {
      await openShift(storeId, parseAmount(openingFloat))
      await onOpened()
    } catch (err) {
      setError(isTransient(err)
        ? 'No connection. Opening a shift needs the connection; once it is open, the till keeps selling offline.'
        : apiErrorText(err, 'Could not open the shift.'))
    } finally { setBusy(false) }
  }

  return (
    <div style={{ maxWidth: 420 }}>
      <PageHeader title="Open shift" subtitle="Count the cash in the drawer to start trading." />
      <Card>
        <p style={{ fontSize: 14, color: 'var(--fg-muted)', margin: '0 0 16px' }}>
          Count the cash in the drawer before your first sale. It is checked against the drawer when you close the shift.
        </p>
        {offline && <NoticeBox variant="warning" style={{ marginBottom: 12 }}>You are offline. Opening a shift needs the connection.</NoticeBox>}
        <Field label="Opening float (cash in drawer)">
          <Input value={openingFloat} onChange={(e) => setOpeningFloat(e.target.value)} placeholder="0" />
        </Field>
        {error && <NoticeBox variant="error" style={{ marginTop: 12 }}>{error}</NoticeBox>}
        <Button variant="primary" onClick={submit} disabled={busy} style={{ marginTop: 16, width: '100%', height: 43 }}>Open shift</Button>
      </Card>
    </div>
  )
}

/** Cart lines re-priced (and their stock re-read) from a fresh snapshot;
 * a line whose product can no longer be priced is dropped. */
function repriceCart(lines, snapshot, unsynced) {
  return lines.flatMap((line) => {
    const product = snapshot.products.find((p) => p.id === line.productId)
    const option = product && sellOptions(snapshot, [product], unsynced).find((o) => o.key === line.key)
    return option && option.unitPrice !== null ? [{ ...option, qty: line.qty }] : []
  })
}

function Till({ snapshot, outbox, offline, refresh, userId, storeId, store, entity, role, features, onShiftClosed }) {
  const shift = snapshot.shift
  const isManager = MANAGER_ROLES.includes(role)
  const takesCredit = features?.customer_credit !== false
  const [query, setQuery] = useState('')
  const [cart, setCart] = useState([])
  const [paymentMethodId, setPaymentMethodId] = useState('')
  const [tendered, setTendered] = useState('')
  const [reference, setReference] = useState('')
  const [customerId, setCustomerId] = useState('')
  const [onCredit, setOnCredit] = useState(false)
  const [creditInput, setCreditInput] = useState('') // blank = everything still to pay
  const [discountInput, setDiscountInput] = useState('')
  const [approver, setApprover] = useState({ username: '', password: '' })
  const [busy, setBusy] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')
  const [completed, setCompleted] = useState(null) // the last completed sale, shown until "New sale"
  const [panel, setPanel] = useState(null) // null | 'sales' | 'close'
  const [printSale, setPrintSale] = useState(null)

  const activeMethods = snapshot.payment_methods
  const method = activeMethods.find((m) => m.id === paymentMethodId) ?? activeMethods.find((m) => m.implementation === 'cash')
  const isCash = method?.implementation === 'cash'

  const customers = takesCredit ? (snapshot.customers ?? []) : []
  const customer = customers.find((c) => c.id === customerId) ?? null

  const unsynced = useMemo(() => unsyncedStock(outbox, storeId), [outbox, storeId])
  // Credit sales still on this till aren't in the snapshot's balances yet.
  const unsentCredit = useMemo(() => outbox.reduce((acc, r) => {
    if (r.payload.customer) acc[r.payload.customer] = (acc[r.payload.customer] ?? 0) + Number(r.payload.credit_amount || 0)
    return acc
  }, {}), [outbox])
  const unsent = outbox.filter((r) => r.shiftId === shift.id)
  const suggestions = useMemo(
    () => (query.trim() ? sellOptions(snapshot, searchTill(snapshot, query.trim()), unsynced) : []),
    [query, snapshot, unsynced],
  )

  /** A barcode scanner types the code and presses Enter. An exact barcode
   * match goes straight into the cart in its stock unit; otherwise Enter
   * picks the only suggestion, if there is just one. */
  function onSearchKeyDown(e) {
    if (e.key !== 'Enter') return
    const q = query.trim()
    if (!q) return
    e.preventDefault()
    const byBarcode = findByBarcode(snapshot, q)
    if (byBarcode.length === 1) {
      const [option] = sellOptions(snapshot, byBarcode, unsynced)
      if (option.unitPrice === null) setErrorMessage(`${option.name} has no selling price set.`)
      else if (option.qtyAvailable <= 0) setErrorMessage(`${option.name} is out of stock.`)
      else addToCart(option)
      setQuery('')
      return
    }
    if (suggestions.length === 1) addToCart(suggestions[0])
  }

  /** Stock units of a product already in the cart, across all the units it's sold in. */
  const stockInCart = (lines, productId) => lines.filter((l) => l.productId === productId).reduce((sum, l) => sum + l.qty * l.perUnit, 0)

  function addToCart(s) {
    if (s.unitPrice === null || s.qtyAvailable <= 0) return
    setErrorMessage('')
    setCart((prev) => {
      if (stockInCart(prev, s.productId) + s.perUnit > s.stockAvailable + 1e-9) return prev
      const existing = prev.find((l) => l.key === s.key)
      if (existing) return prev.map((l) => (l.key === s.key ? { ...l, qty: l.qty + 1 } : l))
      return [...prev, { ...s, qty: 1 }]
    })
    setQuery('')
  }
  const setQty = (key, qty) => setCart((prev) => {
    const line = prev.find((l) => l.key === key)
    const others = stockInCart(prev, line.productId) - line.qty * line.perUnit
    const max = Math.floor((line.stockAvailable - others) / line.perUnit + 1e-9)
    return prev.map((l) => (l.key === key ? { ...l, qty: Math.min(Math.max(qty, 0), max) } : l)).filter((l) => l.qty > 0)
  })
  const canAddOne = (line) => stockInCart(cart, line.productId) + line.perUnit <= line.stockAvailable + 1e-9

  function newSale() {
    setCart([]); setTendered(''); setReference(''); setErrorMessage(''); setCompleted(null)
    setCustomerId(''); setOnCredit(false); setCreditInput(''); setDiscountInput('')
    setApprover({ username: '', password: '' })
  }

  const gross = cart.reduce((sum, l) => sum + l.unitPrice * l.qty, 0)
  const discount = Math.min(parseAmount(discountInput), gross)
  const total = gross - discount
  // The discount is shared over the lines on the server, so VAT shrinks with it.
  const standardGross = cart.reduce((sum, l) => sum + (l.vatClass === 'standard' ? l.unitPrice * l.qty : 0), 0)
  const vat = gross > 0 ? standardGross * (total / gross) * 18 / 118 : 0
  const discountLimit = Number(snapshot.cashier_discount_limit ?? 0)
  const needsApproval = !isManager && discount > 0 && discount * 100 > gross * discountLimit + 1e-9
  const approvalReady = !needsApproval || (approver.username.trim() && approver.password)
  const creditAmount = onCredit && customer
    ? Math.min(creditInput.trim() === '' ? total : parseAmount(creditInput), total) : 0
  const owing = customer ? Number(customer.owing) + (unsentCredit[customer.id] ?? 0) : 0
  const overLimit = creditAmount > 0 && customer.credit_limit !== null && owing + creditAmount > Number(customer.credit_limit) + 1e-9
  const payable = total - creditAmount
  const tenderedNum = parseAmount(tendered)
  const change = tenderedNum - payable
  const canComplete = cart.length > 0 && method && !busy && approvalReady && !(needsApproval && offline)
    && !(onCredit && (!customer || overLimit))
    && (payable === 0 || (isCash ? tenderedNum >= payable : reference.trim().length > 0))

  /** The sale as the till rang it up: the request that records it, and
   * the receipt to show and print until the cloud has numbered it. */
  function buildSale() {
    const id = newId()
    const now = new Date().toISOString()
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
      payment_method_name: method.name, payment_reference: paymentReference,
      amount_tendered: amountTendered, change_due: amountTendered - payable, efd_receipt_no: '',
    }
    return {
      id, userId, storeId, shiftId: shift.id, createdAt: now, status: 'pending', error: '',
      payload, receipt, stock: cart.map((l) => ({ product: l.productId, qty: l.qty * l.perUnit })),
    }
  }

  async function completeSale() {
    setBusy(true); setErrorMessage('')
    try {
      const record = buildSale()
      const secret = needsApproval ? { approver_username: approver.username.trim(), approver_password: approver.password } : {}
      const result = await placeSale(record, secret)
      setCompleted(result.sale ?? record.receipt)
      setCart([])
      // The customer's balance in the till's copy is now out of date.
      if (result.sale && creditAmount > 0) refresh()
    } catch (err) {
      // The cloud refused it (stock or price changed, a rule not met): it
      // wasn't kept, so fix the cart and try again with the customer here.
      setErrorMessage(apiErrorText(err, 'Could not record the sale.'))
      const fresh = await refresh()
      if (fresh) setCart((prev) => repriceCart(prev, fresh, unsynced))
    } finally { setBusy(false) }
  }

  function print(sale) {
    setPrintSale(sale)
    setTimeout(() => window.print(), 50)
  }

  const summary = shift.summary
  const salesCount = summary.sales_count + unsent.length
  const shiftTotal = Number(summary.gross_total) + unsent.reduce((sum, r) => sum + Number(r.receipt.total), 0)

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 16, marginBottom: 24, flexWrap: 'wrap' }}>
        <div>
          <h1 className="page-title">Point of sale</h1>
          <div className="page-subtitle">
            Shift opened {new Date(shift.opened_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} by {shift.cashier_name}
            {' · '}{salesCount} sale{salesCount === 1 ? '' : 's'} · {fmt(shiftTotal)}
            {unsent.length > 0 && ` · ${unsent.length} not yet sent`}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <Button onClick={() => setPanel(panel === 'sales' ? null : 'sales')}>{panel === 'sales' ? 'Back to till' : 'Shift sales'}</Button>
          <Button onClick={() => setPanel(panel === 'close' ? null : 'close')}>{panel === 'close' ? 'Back to till' : 'Close shift'}</Button>
        </div>
      </div>

      {offline && (
        <NoticeBox variant="warning" title="Offline: keep selling" style={{ marginBottom: 16 }}>
          Sales are saved on this till and sent as soon as the connection returns. Stock and prices are as of {new Date(snapshot.generated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}.
        </NoticeBox>
      )}
      <UnsentSales records={outbox.filter((r) => r.storeId === storeId)} userId={userId} />

      {panel === 'sales' && <ShiftSales shift={shift} unsent={unsent} isManager={isManager} onPrint={print} onChanged={refresh} />}
      {panel === 'close' && <CloseShift shift={shift} unsent={unsent} onClosed={onShiftClosed} />}

      {panel === null && (
        <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', alignItems: 'flex-start' }}>
          <div style={{ flex: '1 1 480px', minWidth: 320, display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div style={{ position: 'relative' }}>
              <div onKeyDown={onSearchKeyDown}>
                <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Scan a barcode, or search by name, brand or size" prefixIcon="search" disabled={!!completed || busy} />
              </div>
              {suggestions.length > 0 && (
                <div style={{ position: 'absolute', top: 44, left: 0, right: 0, background: 'var(--white)', borderRadius: 'var(--radius-md)', boxShadow: 'var(--shadow-popover)', zIndex: 10, overflow: 'hidden' }}>
                  {suggestions.map((s) => {
                    const blocked = s.unitPrice === null || s.qtyAvailable <= 0
                    return (
                      <div
                        key={s.key}
                        onClick={() => addToCart(s)}
                        style={{ display: 'flex', justifyContent: 'space-between', gap: 12, padding: '10px 16px', cursor: blocked ? 'not-allowed' : 'pointer', fontSize: 14, borderBottom: '1px solid var(--grey-300)', opacity: blocked ? 0.6 : 1 }}
                      >
                        <div>
                          <div style={{ color: 'var(--grey-900)', display: 'flex', gap: 8, alignItems: 'center' }}>
                            {s.name}
                            <span style={{ fontSize: 12, color: 'var(--fg-subtle)' }}>per {s.unitName}</span>
                            {s.promotion && <Tag variant="positive">Offer</Tag>}
                          </div>
                          <div style={{ fontSize: 12, color: 'var(--fg-subtle)' }}>
                            {s.qtyAvailable > 0 ? `${s.qtyAvailable} ${s.unitName} in stock` : 'Out of stock'}
                            {s.unitPrice === null && ' · no selling price set'}
                          </div>
                        </div>
                        <div style={{ color: 'var(--grey-700)', whiteSpace: 'nowrap', textAlign: 'right' }}>
                          {s.unitPrice === null ? '—' : fmt(s.unitPrice)}
                          {s.promotion && s.regularPrice !== null && <div style={{ fontSize: 12, color: 'var(--fg-subtle)', textDecoration: 'line-through' }}>{fmt(s.regularPrice)}</div>}
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
            <div style={{ background: 'var(--white)', borderRadius: 'var(--radius-lg)', boxShadow: 'var(--shadow-card)' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr>
                    <th style={thStyle('center', 32)}>#</th>
                    <th style={thStyle('left')}>Product</th>
                    <th style={thStyle('center')}>Qty</th>
                    <th style={thStyle('right')}>Line total</th>
                    <th style={{ width: 36, borderBottom: '1px solid var(--grey-300)' }} />
                  </tr>
                </thead>
                <tbody>
                  {cart.map((line, i) => (
                    <tr key={line.key}>
                      <td style={tdStyle('center')}>{i + 1}</td>
                      <td style={tdStyle('left', true)}>
                        <div style={{ fontSize: 14, color: 'var(--grey-900)' }}>{line.name}</div>
                        <div style={{ fontSize: 12, color: 'var(--fg-subtle)' }}>
                          {fmt(line.unitPrice)} per {line.unitName}{line.vatClass === 'standard' ? ' (incl. 18% VAT)' : ''}{line.promotion ? ` · ${line.promotion}` : ''}
                        </div>
                      </td>
                      <td style={tdStyle()}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
                          <button onClick={() => setQty(line.key, line.qty - 1)} disabled={busy} style={stepBtnStyle}>−</button>
                          <span style={{ minWidth: 20, textAlign: 'center', fontSize: 14 }}>{line.qty}</span>
                          <button onClick={() => setQty(line.key, line.qty + 1)} disabled={busy || !canAddOne(line)} style={stepBtnStyle}>+</button>
                        </div>
                      </td>
                      <td style={{ ...tdStyle('right'), color: 'var(--grey-900)' }}>{fmt(line.unitPrice * line.qty)}</td>
                      <td style={tdStyle()}>
                        <button onClick={() => setQty(line.key, 0)} disabled={busy} title="Remove" style={removeBtnStyle}>
                          <Icon name="cross" size={16} />
                        </button>
                      </td>
                    </tr>
                  ))}
                  {cart.length === 0 && (
                    <tr><td colSpan={5} style={{ padding: '32px 16px', textAlign: 'center', fontSize: 14, color: 'var(--fg-subtle)' }}>
                      {completed ? 'Sale complete. Start a new sale when ready.' : 'Cart is empty. Search for a product to add it.'}
                    </td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div style={{ flex: '0 1 360px', minWidth: 300, background: 'var(--white)', borderRadius: 'var(--radius-lg)', boxShadow: 'var(--shadow-card)', padding: 16, display: 'flex', flexDirection: 'column', gap: 16 }}>
            {completed
              ? <CompletedSale sale={completed} onUpdated={setCompleted} onPrint={() => print(completed)} onNewSale={newSale} />
              : (
                <>
                  <div>
                    {discount > 0 && <div style={summaryRowStyle}><span>Before discount</span><span>{fmt(gross)}</span></div>}
                    {discount > 0 && <div style={summaryRowStyle}><span>Discount</span><span>− {fmt(discount)}</span></div>}
                    <div style={summaryRowStyle}><span>Subtotal (excl. VAT)</span><span>{fmt(total - vat)}</span></div>
                    <div style={summaryRowStyle}><span>VAT (18%, included)</span><span>{fmt(vat)}</span></div>
                    <div style={{ ...summaryRowStyle, fontSize: 17, fontWeight: 500, color: 'var(--grey-900)', padding: '8px 0', borderTop: '1px solid var(--grey-300)', marginTop: 4 }}>
                      <span>Total</span><span>{fmt(total)}</span>
                    </div>
                    {creditAmount > 0 && (
                      <>
                        <div style={summaryRowStyle}><span>On {customer.name}&rsquo;s account</span><span>{fmt(creditAmount)}</span></div>
                        <div style={{ ...summaryRowStyle, fontSize: 17, fontWeight: 500, color: 'var(--grey-900)' }}><span>To pay now</span><span>{fmt(payable)}</span></div>
                      </>
                    )}
                  </div>

                  <Field label="Discount on the sale (TZS)">
                    <Input value={discountInput} onChange={(e) => setDiscountInput(e.target.value)} placeholder="0" disabled={busy || cart.length === 0} />
                  </Field>
                  {needsApproval && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: 12, background: 'var(--grey-100)', borderRadius: 'var(--radius-sm)' }}>
                      <div style={{ fontSize: 13, color: 'var(--grey-900)' }}>
                        This discount is more than the {discountLimit}% a cashier may give. A manager approves it by entering their own login.
                      </div>
                      {offline
                        ? <NoticeBox variant="warning">Approving a discount needs the connection.</NoticeBox>
                        : (
                          <>
                            <Field label="Manager username"><Input value={approver.username} onChange={(e) => setApprover({ ...approver, username: e.target.value })} /></Field>
                            <Field label="Manager password"><Input type="password" value={approver.password} onChange={(e) => setApprover({ ...approver, password: e.target.value })} /></Field>
                          </>
                        )}
                    </div>
                  )}

                  {customers.length > 0 && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: customer ? 12 : 0, background: customer ? 'var(--grey-100)' : undefined, borderRadius: 'var(--radius-sm)' }}>
                      <Field label="Customer">
                        <Select
                          value={customerId}
                          onChange={(e) => { setCustomerId(e.target.value); if (!e.target.value) setOnCredit(false) }}
                          options={[{ value: '', label: 'Walk-in customer' }, ...customers.map((c) => ({ value: c.id, label: c.phone ? `${c.name} · ${c.phone}` : c.name }))]}
                        />
                      </Field>
                      {customer && (
                        <>
                          <div style={{ fontSize: 12, color: 'var(--fg-subtle)' }}>
                            Owes {fmt(owing)}{customer.credit_limit !== null ? ` · credit limit ${fmt(Number(customer.credit_limit))}` : ' · no credit limit'}
                          </div>
                          <Checkbox checked={onCredit} onChange={() => setOnCredit((v) => !v)} label="Put on the customer's account (credit)" />
                          {onCredit && (
                            <Field label="Amount on credit (blank = all of it)">
                              <Input value={creditInput} onChange={(e) => setCreditInput(e.target.value)} placeholder={String(Math.round(total))} disabled={busy} />
                            </Field>
                          )}
                          {overLimit && (
                            <NoticeBox variant="warning">
                              {customer.name} would owe {fmt(owing + creditAmount)}, over their limit of {fmt(Number(customer.credit_limit))}.
                              Take at most {fmt(Math.max(Number(customer.credit_limit) - owing, 0))} on credit.
                            </NoticeBox>
                          )}
                        </>
                      )}
                    </div>
                  )}

                  {payable === 0 && cart.length > 0
                    ? <NoticeBox variant="info">Nothing to pay now: the whole sale goes on {customer?.name}&rsquo;s account.</NoticeBox>
                    : (
                      <>
                  <div>
                    <div style={{ fontSize: 14, color: 'var(--grey-700)', marginBottom: 8 }}>Payment method</div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                      {activeMethods.map((m) => (
                        <Radio key={m.id} checked={method?.id === m.id} onChange={() => setPaymentMethodId(m.id)} label={m.name} />
                      ))}
                    </div>
                  </div>

                  {isCash
                    ? (
                      <div>
                        <Field label="Amount tendered">
                          <Input value={tendered} onChange={(e) => setTendered(e.target.value)} placeholder="0" disabled={busy} />
                        </Field>
                        {tenderedNum > 0 && (
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 15, fontWeight: 500, color: change < 0 ? 'var(--status-error)' : 'var(--grey-900)', marginTop: 8 }}>
                            <span>{change < 0 ? 'Amount still due' : 'Change due'}</span><span>{fmt(Math.abs(change))}</span>
                          </div>
                        )}
                      </div>
                    )
                    : (
                      <Field label={`${method?.name ?? 'Payment'} transaction reference`} required>
                        <Input value={reference} onChange={(e) => setReference(e.target.value)} placeholder="e.g. QK7Y2ZT1" disabled={busy} />
                      </Field>
                    )}
                      </>
                    )}

                  {errorMessage && <NoticeBox variant="error" title="Sale not completed">{errorMessage}</NoticeBox>}
                  <Button variant="primary" onClick={completeSale} disabled={!canComplete} style={{ width: '100%', height: 43 }}>
                    {busy ? 'Recording…' : 'Complete sale'}
                  </Button>
                  {cart.length > 0 && <Button onClick={newSale} disabled={busy}>Clear cart</Button>}
                </>
              )}
          </div>
        </div>
      )}

      {printSale && <PrintArea kind="receipt"><Receipt sale={printSale} entity={entity} store={store} /></PrintArea>}
    </div>
  )
}

function CompletedSale({ sale, onUpdated, onPrint, onNewSale }) {
  return (
    <>
      <NoticeBox variant="valid" title={sale.offline ? 'Sale saved on this till' : `Sale #${sale.number} complete`}>
        {Number(sale.credit_amount) > 0
          ? <>{fmt(Number(sale.credit_amount))} on {sale.customer_name}&rsquo;s account{Number(sale.paid_amount) > 0 && <>, {fmt(Number(sale.paid_amount))} paid by {sale.payment_method_name}</>}.</>
          : <>{fmt(Number(sale.total))} paid by {sale.payment_method_name}.</>}
        {sale.change_due !== null && Number(sale.change_due) > 0 && <> Give change: <b>{fmt(Number(sale.change_due))}</b>.</>}
        {sale.offline && <div style={{ marginTop: 4 }}>No connection right now: it is sent, and gets its receipt number, as soon as the connection returns.</div>}
      </NoticeBox>
      <EfdReceiptEntry sale={sale} onUpdated={onUpdated} />
      <Button onClick={onPrint}><Icon name="download" size={16} /> Print receipt</Button>
      <Button variant="primary" onClick={onNewSale} style={{ width: '100%', height: 43 }}>New sale</Button>
    </>
  )
}

/** The till can't talk to the store's EFD machine (see
 * fiscal.drivers.manual_efd): the cashier rings the sale up on it and
 * types the printed receipt number in here. For a sale not yet sent, the
 * number is kept with it and sent along. */
function EfdReceiptEntry({ sale, onUpdated }) {
  const [number, setNumber] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  if (sale.efd_receipt_no) {
    return <div style={{ fontSize: 13, color: 'var(--grey-700)' }}>EFD receipt no. <b>{sale.efd_receipt_no}</b></div>
  }
  async function save() {
    setBusy(true); setError('')
    try {
      if (sale.offline && await setUnsentEfdNumber(sale.id, number.trim())) {
        onUpdated({ ...sale, efd_receipt_no: number.trim() })
        return
      }
      onUpdated(await recordFiscalReceipt(sale.id, number.trim()))
    } catch (err) {
      setError(apiErrorText(err, 'Could not save the EFD receipt number.'))
    } finally { setBusy(false) }
  }
  return (
    <div style={{ padding: 12, background: 'var(--grey-100)', borderRadius: 'var(--radius-sm)', display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ fontSize: 13, color: 'var(--grey-900)' }}>
        Issue this sale on the EFD machine ({fmt(Number(sale.total))}), then enter the receipt number it prints.
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <Input value={number} onChange={(e) => setNumber(e.target.value)} placeholder="EFD receipt no." />
        <Button onClick={save} disabled={busy || !number.trim()}>Save</Button>
      </div>
      {error && <div style={{ fontSize: 12, color: 'var(--status-error)' }}>{error}</div>}
    </div>
  )
}

/** Sales on this till the cloud refused when they were sent (e.g. its
 * stock figures show too little left), and sales another cashier left
 * waiting. A refused sale stays here until someone fixes the cause and
 * retries it, or discards it. */
function UnsentSales({ records, userId }) {
  const [busyId, setBusyId] = useState(null)
  const rejected = records.filter((r) => r.status === 'rejected')
  const othersWaiting = records.filter((r) => r.status === 'pending' && r.userId !== userId).length
  if (!rejected.length && !othersWaiting) return null

  async function retry(record) {
    setBusyId(record.id)
    try { await retryRejected(record, userId) } finally { setBusyId(null) }
  }
  function remove(record) {
    if (!window.confirm(`Discard this ${fmt(Number(record.receipt.total))} sale? It will not count in takings or come off stock. Only do this if the sale was reversed: money returned and goods back on the shelf.`)) return
    discard(record)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 16 }}>
      {rejected.length > 0 && (
        <NoticeBox variant="error" title={`${rejected.length} sale${rejected.length === 1 ? '' : 's'} made on this till could not be recorded`}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 4 }}>
            {rejected.map((r) => (
              <div key={r.id} style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
                <span style={{ flex: '1 1 240px' }}>
                  {new Date(r.createdAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} · {fmt(Number(r.receipt.total))}: {r.error}
                </span>
                {r.userId === userId
                  ? <Button size="small" onClick={() => retry(r)} disabled={busyId === r.id}>Try again</Button>
                  : <span style={{ fontSize: 12 }}>Rung up by another cashier: they can retry it here.</span>}
                <Button size="small" variant="destructive" onClick={() => remove(r)} disabled={busyId === r.id}>Discard</Button>
              </div>
            ))}
            <div style={{ fontSize: 12 }}>Fix the cause first, for example by receiving the stock that was sold, then try again.</div>
          </div>
        </NoticeBox>
      )}
      {othersWaiting > 0 && (
        <NoticeBox variant="info">
          {othersWaiting} sale{othersWaiting === 1 ? '' : 's'} by another cashier {othersWaiting === 1 ? 'is' : 'are'} saved on this till. They are sent when that cashier next signs in here.
        </NoticeBox>
      )}
    </div>
  )
}

function ShiftSales({ shift, unsent, isManager, onPrint, onChanged }) {
  const { data, loading, error, refetch: refetchSales } = useApi(() => listAllSales({ shift: shift.id }), [shift.id])
  const sales = (data ?? []).filter((s) => s.status !== 'open')
  const refetch = () => { refetchSales(); onChanged() }
  const [voiding, setVoiding] = useState(null)
  const [efdFor, setEfdFor] = useState(null)

  // A waiting sale that just got recorded moves from the till's list to the server's.
  useEffect(() => subscribe((e) => { if (e.synced) refetchSales() }), [refetchSales])

  if (loading && !data && !unsent.length) return <NoticeBox variant="info">Loading…</NoticeBox>
  return (
    <div className="ds-table-card">
      {error && (
        <NoticeBox variant="warning" style={{ margin: 16 }}>
          {isTransient(error) ? 'Offline: only the sales still saved on this till are shown.' : apiErrorText(error, 'Could not load the shift\'s sales.')}
        </NoticeBox>
      )}
      <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 720 }}>
        <thead>
          <tr>
            <th style={thStyle('left')}>No.</th><th style={thStyle('left')}>Time</th><th style={thStyle('left')}>Paid by</th>
            <th style={thStyle('right')}>Total</th><th style={thStyle('left')}>EFD receipt</th><th style={thStyle('left')}>Status</th><th style={thStyle('right')} />
          </tr>
        </thead>
        <tbody>
          {[...unsent].reverse().map((r) => (
            <tr key={r.id}>
              <td style={tdStyle('left', true)}>{offlineNo(r.receipt)}</td>
              <td style={tdStyle('left', true)}>{new Date(r.createdAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</td>
              <td style={tdStyle('left', true)}><PaidBy sale={r.receipt} /></td>
              <td style={{ ...tdStyle('right', true), color: 'var(--grey-900)' }}>{fmt(Number(r.receipt.total))}</td>
              <td style={tdStyle('left', true)}>
                {r.receipt.efd_receipt_no || (efdFor === r.id
                  ? <EfdReceiptEntry sale={r.receipt} onUpdated={() => setEfdFor(null)} />
                  : <Button size="small" onClick={() => setEfdFor(r.id)}>Enter</Button>)}
              </td>
              <td style={tdStyle('left', true)}>
                {r.status === 'rejected' ? <Tag variant="negative">Not recorded</Tag> : <Tag variant="neutral">Waiting to send</Tag>}
              </td>
              <td style={{ ...tdStyle('right', true), whiteSpace: 'nowrap' }}>
                <Button size="small" onClick={() => onPrint(r.receipt)}>Print</Button>
              </td>
            </tr>
          ))}
          {sales.map((s) => (
            <tr key={s.id}>
              <td style={tdStyle('left', true)}>#{s.number}</td>
              <td style={tdStyle('left', true)}>{new Date(s.completed_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</td>
              <td style={tdStyle('left', true)}><PaidBy sale={s} /></td>
              <td style={{ ...tdStyle('right', true), color: 'var(--grey-900)' }}>{fmt(Number(s.total))}</td>
              <td style={tdStyle('left', true)}>
                {s.efd_receipt_no || (s.status === 'completed' && (efdFor === s.id
                  ? <EfdReceiptEntry sale={s} onUpdated={() => { setEfdFor(null); refetch() }} />
                  : <Button size="small" onClick={() => setEfdFor(s.id)}>Enter</Button>))}
              </td>
              <td style={tdStyle('left', true)}>
                {s.status === 'voided'
                  ? <><Tag variant="negative">Voided</Tag><div style={{ fontSize: 12, marginTop: 2 }}>{s.void_reason}</div></>
                  : <Tag variant="positive">Completed</Tag>}
              </td>
              <td style={{ ...tdStyle('right', true), whiteSpace: 'nowrap' }}>
                <Button size="small" onClick={() => onPrint(s)}>Print</Button>{' '}
                {s.status === 'completed' && <Button size="small" variant="destructive" onClick={() => setVoiding(s)}>Void</Button>}
              </td>
            </tr>
          ))}
          {sales.length === 0 && unsent.length === 0 && <tr><td colSpan={7} style={{ padding: 24, textAlign: 'center', color: 'var(--fg-subtle)', fontSize: 14 }}>No sales in this shift yet.</td></tr>}
        </tbody>
      </table>
      {voiding && <VoidDialog sale={voiding} isManager={isManager} onClose={() => setVoiding(null)} onVoided={() => { setVoiding(null); refetch() }} />}
    </div>
  )
}

function PaidBy({ sale }) {
  const credit = Number(sale.credit_amount)
  return (
    <>
      {credit > 0 ? (Number(sale.paid_amount) > 0 ? `${sale.payment_method_name} + credit` : 'On credit') : sale.payment_method_name}
      {credit > 0 && <div style={{ fontSize: 12 }}>{sale.customer_name}</div>}
      {sale.payment_reference && <div style={{ fontSize: 12 }}>{sale.payment_reference}</div>}
    </>
  )
}

function VoidDialog({ sale, isManager, onClose, onVoided }) {
  const [reason, setReason] = useState('')
  const [approverUsername, setApproverUsername] = useState('')
  const [approverPassword, setApproverPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit() {
    setBusy(true); setError('')
    try {
      await voidSale(sale.id, { reason, approverUsername, approverPassword })
      onVoided()
    } catch (err) {
      setError(apiErrorText(err, 'Could not void the sale.'))
    } finally { setBusy(false) }
  }

  return (
    <div style={{ padding: 16, borderTop: '1px solid var(--grey-300)', display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 480 }}>
      <div style={{ fontSize: 15, fontWeight: 500 }}>Void sale #{sale.number} ({fmt(Number(sale.total))})</div>
      <div style={{ fontSize: 13, color: 'var(--fg-muted)' }}>
        The items go back into stock and the sale is excluded from takings. Return the customer&apos;s money
        {sale.efd_receipt_no ? <> and cancel EFD receipt <b>{sale.efd_receipt_no}</b> on the EFD machine</> : null}.
        {Number(sale.credit_amount) > 0 && <> The {fmt(Number(sale.credit_amount))} on {sale.customer_name}&apos;s account is cleared.</>}
      </div>
      <Field label="Reason" required><Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Wrong item sold" /></Field>
      {!isManager && (
        <>
          <div style={{ fontSize: 13, color: 'var(--grey-700)' }}>A store manager must approve by entering their own login:</div>
          <Field label="Manager username"><Input value={approverUsername} onChange={(e) => setApproverUsername(e.target.value)} /></Field>
          <Field label="Manager password"><Input type="password" value={approverPassword} onChange={(e) => setApproverPassword(e.target.value)} /></Field>
        </>
      )}
      {error && <NoticeBox variant="error">{error}</NoticeBox>}
      <div style={{ display: 'flex', gap: 8 }}>
        <Button variant="destructive" onClick={submit} disabled={busy || !reason.trim()}>Void sale</Button>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
      </div>
    </div>
  )
}

/** Closing needs every sale of the shift recorded in the cloud first, or
 * the Z-report and the drawer count would leave them out. */
function CloseShift({ shift, unsent, onClosed }) {
  const [counted, setCounted] = useState('')
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit() {
    setBusy(true); setError('')
    try {
      onClosed(await closeShift(shift.id, parseAmount(counted), note))
    } catch (err) {
      setError(isTransient(err)
        ? 'No connection. Closing a shift needs the connection, so the Z-report includes every sale.'
        : apiErrorText(err, 'Could not close the shift.'))
    } finally { setBusy(false) }
  }

  return (
    <div style={{ maxWidth: 440 }}>
      <Card>
        <p style={{ fontSize: 14, color: 'var(--fg-muted)', margin: '0 0 16px' }}>
          Count all the cash in the drawer, including the opening float and cash repayments from credit customers. Mobile money and bank payments are not in the drawer.
          The system compares your count with what it expects and prints the end-of-shift (Z) report.
        </p>
        {unsent.length > 0 && (
          <NoticeBox variant="warning" title={`${unsent.length} sale${unsent.length === 1 ? ' has' : 's have'} not been sent yet`} style={{ marginBottom: 12 }}>
            The shift can be closed once every sale on this till has been recorded. Stay connected while they are sent, and deal with any that could not be recorded.
          </NoticeBox>
        )}
        <Field label="Cash counted in drawer" required><Input value={counted} onChange={(e) => setCounted(e.target.value)} placeholder="0" /></Field>
        <Field label="Note (optional)" style={{ marginTop: 12 }}><Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. explanation for any difference" /></Field>
        {error && <NoticeBox variant="error" style={{ marginTop: 12 }}>{error}</NoticeBox>}
        <Button variant="primary" onClick={submit} disabled={busy || counted.trim() === '' || unsent.length > 0} style={{ marginTop: 16, width: '100%', height: 43 }}>Close shift</Button>
      </Card>
    </div>
  )
}

function ZReport({ shift, entity, store, onDone }) {
  const z = shift.summary
  const variance = Number(z.variance)
  return (
    <div style={{ maxWidth: 520 }}>
      <PageHeader title="Shift closed" subtitle="Summary of the shift you just closed." />
      {variance !== 0 && (
        <NoticeBox variant="warning" title={variance < 0 ? `Drawer is short by ${fmt(-variance)}` : `Drawer is over by ${fmt(variance)}`} style={{ marginBottom: 16 }}>
          Expected {fmt(Number(z.expected_cash))}, counted {fmt(Number(z.counted_cash))}.
        </NoticeBox>
      )}
      <Card><ZReportBody shift={shift} entity={entity} store={store} /></Card>
      <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
        <Button onClick={() => window.print()}><Icon name="download" size={16} /> Print Z-report</Button>
        <Button variant="primary" onClick={onDone}>Done</Button>
      </div>
      <PrintArea kind="receipt"><ZReportBody shift={shift} entity={entity} store={store} /></PrintArea>
    </div>
  )
}

function ZReportBody({ shift, entity, store }) {
  const z = shift.summary
  const row = (label, value, bold) => (
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, padding: '3px 0', fontWeight: bold ? 600 : 400 }}><span>{label}</span><span>{value}</span></div>
  )
  return (
    <div>
      <div style={{ textAlign: 'center', marginBottom: 8 }}>
        <div style={{ fontWeight: 600 }}>{entity?.name}</div>
        <div style={{ fontSize: 12 }}>{store?.name}</div>
        <div style={{ fontWeight: 600, marginTop: 6 }}>END OF SHIFT (Z) REPORT</div>
      </div>
      {row('Cashier', shift.cashier_name)}
      {row('Opened', new Date(shift.opened_at).toLocaleString())}
      {row('Closed', shift.closed_at ? new Date(shift.closed_at).toLocaleString() : '—')}
      <hr />
      {row('Sales', z.sales_count)}
      {z.by_payment_method.map((m) => <Fragment key={m.payment_method}>{row(`  ${m.payment_method} (${m.count})`, fmt(Number(m.total)))}</Fragment>)}
      {row('Gross sales', fmt(Number(z.gross_total)), true)}
      {row('VAT included', fmt(Number(z.vat_total)))}
      {Number(z.discount_total) > 0 && row('Discounts given', fmt(Number(z.discount_total)))}
      {row(`Voided sales (${z.void_count})`, fmt(Number(z.void_total)))}
      {z.credit_repayments.length > 0 && (
        <>
          <hr />
          {row('Credit repayments', '', true)}
          {z.credit_repayments.map((m) => <Fragment key={m.payment_method}>{row(`  ${m.payment_method} (${m.count})`, fmt(Number(m.total)))}</Fragment>)}
        </>
      )}
      <hr />
      {row('Opening float', fmt(Number(z.opening_float)))}
      {row('Cash sales', fmt(Number(z.cash_sales)))}
      {Number(z.cash_repayments) > 0 && row('Cash repayments', fmt(Number(z.cash_repayments)))}
      {row('Expected cash', fmt(Number(z.expected_cash)), true)}
      {row('Counted cash', z.counted_cash === null ? '—' : fmt(Number(z.counted_cash)))}
      {row('Difference', z.variance === null ? '—' : fmt(Number(z.variance)), true)}
      {shift.closing_note && <div style={{ fontSize: 12, marginTop: 6 }}>Note: {shift.closing_note}</div>}
    </div>
  )
}

function Receipt({ sale, entity, store }) {
  const line = (left, right, bold) => (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontWeight: bold ? 600 : 400 }}><span>{left}</span><span style={{ whiteSpace: 'nowrap' }}>{right}</span></div>
  )
  const total = Number(sale.total)
  const vat = Number(sale.vat_total)
  // FEFO can split one item over several batches; the customer sees one line per product and unit.
  const items = Object.values(sale.lines.reduce((acc, l) => {
    const key = `${l.product}:${l.sell_uom ?? ''}`
    acc[key] ??= { key, name: l.product_name, unit: l.unit_name, qty: 0, amount: 0, unitPrice: Number(l.unit_price) }
    acc[key].qty += Number(l.sell_qty)
    acc[key].amount += Number(l.amount) + Number(l.discount ?? 0)
    return acc
  }, {}))
  return (
    <div>
      <div style={{ textAlign: 'center' }}>
        {entity?.logo && <img src={entity.logo} alt="" style={{ maxWidth: '40mm', maxHeight: '18mm', marginBottom: 4 }} />}
        <div style={{ fontWeight: 600, fontSize: 14 }}>{entity?.name}</div>
        {store && <div>{store.name}{store.address ? `, ${store.address}` : ''}</div>}
        {(store?.tin || entity?.tin) && <div>TIN: {store?.tin || entity?.tin}</div>}
      </div>
      <hr />
      {line(sale.number ? `Receipt #${sale.number}` : `Receipt ${offlineNo(sale)} (offline)`, new Date(sale.completed_at).toLocaleString())}
      {line('Served by', sale.cashier_name)}
      {sale.status === 'voided' && <div style={{ fontWeight: 600, textAlign: 'center' }}>*** VOIDED ***</div>}
      <hr />
      {items.map((it) => (
        <div key={it.key} style={{ marginBottom: 2 }}>
          <div>{it.name}</div>
          {line(`  ${Math.round(it.qty * 100) / 100} ${it.unit} x ${Math.round(it.unitPrice).toLocaleString('en-US')}`, Math.round(it.amount).toLocaleString('en-US'))}
        </div>
      ))}
      <hr />
      {Number(sale.discount_total) > 0 && line('Discount', `− ${fmt(Number(sale.discount_total))}`)}
      {line('TOTAL', fmt(total), true)}
      {line('VAT included (18%)', fmt(vat))}
      {Number(sale.credit_amount) > 0 && (
        <>
          {line('On account', fmt(Number(sale.credit_amount)))}
          {line('Paid now', fmt(Number(sale.paid_amount)))}
        </>
      )}
      {(!Number(sale.credit_amount) || Number(sale.paid_amount) > 0) && line('Paid by', sale.payment_method_name)}
      {sale.amount_tendered !== null && sale.payment_reference === '' && line('Tendered', fmt(Number(sale.amount_tendered)))}
      {sale.change_due !== null && sale.payment_reference === '' && line('Change', fmt(Number(sale.change_due)))}
      {sale.payment_reference && line('Reference', sale.payment_reference)}
      {sale.customer_name && line('Customer', sale.customer_phone ? `${sale.customer_name} (${sale.customer_phone})` : sale.customer_name)}
      <hr />
      <div style={{ textAlign: 'center', fontSize: 11 }}>
        {sale.efd_receipt_no ? `EFD receipt no. ${sale.efd_receipt_no}` : 'Fiscal (EFD) receipt issued separately.'}
        <div>Thank you for shopping with us. Karibu tena!</div>
      </div>
    </div>
  )
}

function thStyle(align, width) {
  return { width, textAlign: align, fontWeight: 600, fontSize: 11, lineHeight: '16px', textTransform: 'uppercase', letterSpacing: 1.2, color: 'var(--fg-subtle)', padding: align === 'center' ? '12px 8px' : '12px 16px', borderBottom: '1px solid var(--grey-300)' }
}
function tdStyle(align, wide) {
  return { padding: wide ? '14px 16px' : '14px 8px', borderBottom: '1px solid var(--grey-300)', textAlign: align || 'center', fontSize: 14, color: 'var(--fg-subtle)' }
}
const stepBtnStyle = { width: 24, height: 24, borderRadius: 'var(--radius-sm)', border: '1px solid var(--grey-500)', background: 'var(--white)', cursor: 'pointer', fontSize: 14, lineHeight: 1 }
const removeBtnStyle = { width: 24, height: 24, borderRadius: 'var(--radius-sm)', border: 0, background: 'transparent', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', fill: 'var(--status-error)', color: 'var(--status-error)' }
const summaryRowStyle = { display: 'flex', justifyContent: 'space-between', fontSize: 14, color: 'var(--grey-700)', padding: '4px 0' }
