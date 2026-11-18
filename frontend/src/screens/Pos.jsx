import { useMemo, useState } from 'react'
import { Button, Card, Checkbox, Field, Icon, Input, NoticeBox, PageHeader, Radio, Select, Tag } from '../components/ds/index.js'
import PrintArea from '../components/PrintArea.jsx'
import { useOutbox, useTill } from '../hooks/useOutbox.js'
import { isTransient } from '../api/client.js'
import { openShift } from '../api/pos.js'
import { placeSale, unsyncedStock } from '../offline/outbox.js'
import { findByBarcode, searchTill, sellOptions } from '../offline/till.js'
import { fmt } from '../appData.js'
import QuickAddProduct from '../components/QuickAddProduct.jsx'
import { apiErrorText } from '../lib/apiError.js'
import { dateLocale, t, useT } from '../i18n/index.js'
import CloseShift from './pos/CloseShift.jsx'
import { CompletedSale } from './pos/CompletedSale.jsx'
import { parseAmount, removeBtnStyle, stepBtnStyle, summaryRowStyle, tdStyle, thStyle } from './pos/format.js'
import { Receipt, ZReport } from './pos/Printouts.jsx'
import { ShiftSales, UnsentSales } from './pos/ShiftSales.jsx'
import { useAsyncAction } from '../hooks/useAsyncAction.js'

const MANAGER_ROLES = ['store_manager', 'entity_admin']
const NO_RX = { patient_name: '', prescriber_name: '', prescription_ref: '' }

// crypto.randomUUID needs a secure context; getRandomValues doesn't.
function newId() {
  if (crypto.randomUUID) return crypto.randomUUID()
  const b = crypto.getRandomValues(new Uint8Array(16))
  b[6] = (b[6] & 0x0f) | 0x40
  b[8] = (b[8] & 0x3f) | 0x80
  const h = [...b].map((x) => x.toString(16).padStart(2, '0')).join('')
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`
}

export default function Pos({ storeId, userId, roles, entity, features, goTo, canGo = () => false }) {
  useT()
  const till = useTill(userId, storeId)
  const outbox = useOutbox()
  const [zReport, setZReport] = useState(null)
  const snapshot = till.snapshot?.store === storeId ? till.snapshot : null
  const store = snapshot?.store_details

  if (!storeId) return <NoticeBox variant="warning" title={t('No store selected')}>{t('Select a store to start a sale.')}</NoticeBox>
  if (zReport) return <ZReport shift={zReport} entity={entity} store={store} onDone={() => setZReport(null)} />
  if (till.loading && !snapshot) return <NoticeBox variant="info">{t('Loading…')}</NoticeBox>
  if (!snapshot) {
    return till.offline
      ? (
        <NoticeBox variant="warning" title={t('This till isn\'t ready to sell offline yet')}>
          {t('It needs to connect once to save a copy of the catalog, prices and stock. Open the point of sale while online; after that it keeps selling when the connection drops.')}
        </NoticeBox>
      )
      : <NoticeBox variant="error" title={t('Could not load the till')}>{apiErrorText(till.error, t('Try again in a moment.'))}</NoticeBox>
  }
  if (!snapshot.shift) return <OpenShift storeId={storeId} offline={till.offline} onOpened={till.refresh} />
  return (
    <Till
      key={snapshot.shift.id} snapshot={snapshot} outbox={outbox} offline={till.offline} refresh={till.refresh}
      userId={userId} storeId={storeId} store={store} entity={entity} roles={roles} features={features} goTo={goTo} canGo={canGo}
      onShiftClosed={(closed) => { setZReport(closed); till.refresh() }}
    />
  )
}

function OpenShift({ storeId, offline, onOpened }) {
  useT()
  const [openingFloat, setOpeningFloat] = useState('')
  const { busy, error, run } = useAsyncAction()

  function submit() {
    return run(async () => {
      await openShift(storeId, parseAmount(openingFloat))
      await onOpened()
    }, (err) => isTransient(err)
      ? t('No connection. Opening a shift needs the connection; once it is open, the till keeps selling offline.')
      : apiErrorText(err, t('Could not open the shift.')))
  }

  return (
    <div style={{ maxWidth: 420 }}>
      <PageHeader title={t('Open shift')} subtitle={t('Count the cash in the drawer to start trading.')} />
      <Card>
        <p style={{ fontSize: 14, color: 'var(--fg-muted)', margin: '0 0 16px' }}>
          {t('Count the cash in the drawer before your first sale. It is checked against the drawer when you close the shift.')}
        </p>
        {offline && <NoticeBox variant="warning" style={{ marginBottom: 12 }}>{t('You are offline. Opening a shift needs the connection.')}</NoticeBox>}
        <Field label={t('Cash in the drawer now')}>
          <Input value={openingFloat} onChange={(e) => setOpeningFloat(e.target.value)} placeholder="0" />
        </Field>
        {error && <NoticeBox variant="error" style={{ marginTop: 12 }}>{error}</NoticeBox>}
        <Button variant="primary" onClick={submit} disabled={busy} style={{ marginTop: 16, width: '100%', height: 43 }}>{t('Open shift')}</Button>
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

// Scanners type six or more digits; people type names.
const isBarcode = (text) => /^\d{6,}$/.test(text)

/** Why the till couldn't ring something up, and what to do about it:
 * the fix itself for an owner, else who can fix it. */
function CannotSell({ stuck, isOwner, offline, goTo, canGo, onFix, onDismiss }) {
  useT()
  const { option, missing } = stuck
  let title, text
  let action = null
  if (missing) {
    title = isBarcode(missing) ? t('No product has the barcode {code}', { code: missing }) : t('No product matches “{q}”', { q: missing })
    text = isOwner ? t('Add it now with its price and stock, and it goes straight into the cart.') : t('Ask the shop owner to add it.')
    if (isOwner) action = { label: t('Add it now'), onClick: () => onFix({ initial: isBarcode(missing) ? { barcode: missing } : { name: missing } }) }
  } else {
    const product = { id: option.productId, name: option.name, uom_name: option.unitName, tracks_expiry: option.tracksExpiry, has_price: option.unitPrice !== null }
    if (option.unitPrice === null) {
      title = t('{name} has no selling price yet', { name: option.name })
      text = isOwner ? t('Set its price, and its stock if you have not yet.') : t('Only the shop owner can set prices. Ask them to set it.')
    } else {
      title = t('{name} is out of stock', { name: option.name })
      text = isOwner ? t('Enter the stock you have, or record a delivery under Receive stock.')
        : canGo('receiving') ? t('Record the delivery under Receive stock to add it.') : t('Ask the storekeeper or owner to add stock.')
    }
    if (isOwner) action = { label: t('Set price and stock'), onClick: () => onFix({ product }) }
    else if (option.unitPrice !== null && canGo('receiving')) action = { label: t('Open Receive stock'), onClick: () => goTo('receiving') }
  }
  return (
    <NoticeBox
      variant="warning" title={title}
      action={(
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {action && <Button variant="primary" onClick={action.onClick} disabled={offline && isOwner}>{action.label}</Button>}
          <Button onClick={onDismiss}>{t('Dismiss')}</Button>
        </div>
      )}
    >
      {text}
      {offline && isOwner && <div style={{ marginTop: 4 }}>{t('Adding or changing products needs the connection.')}</div>}
    </NoticeBox>
  )
}

function Till({ snapshot, outbox, offline, refresh, userId, storeId, store, entity, roles, features, goTo, canGo, onShiftClosed }) {
  useT()
  const shift = snapshot.shift
  const isManager = MANAGER_ROLES.some((r) => roles.includes(r))
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
  // Why the last scan or pick couldn't go in the cart: { option } (no price
  // or no stock) or { missing: text } (nothing matches); and the quick-add
  // form opened from it: { product?, initial? }.
  const [stuck, setStuck] = useState(null)
  const [rx, setRx] = useState(NO_RX)
  const [fixing, setFixing] = useState(null)
  const isOwner = roles.includes('entity_admin')

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
      addToCart(sellOptions(snapshot, byBarcode, unsynced)[0])
      setQuery('')
      return
    }
    if (suggestions.length === 1) addToCart(suggestions[0])
    else if (suggestions.length === 0) {
      // A scanner's code clears the box for the next scan; a typed name stays.
      setStuck({ missing: q })
      if (isBarcode(q)) setQuery('')
    }
  }

  /** The quick-add form saved: fetch the till's copy again and ring the
   * product up if it can now be sold. */
  async function fixed(result) {
    const fresh = await refresh()
    const product = fresh?.products.find((p) => p.id === String(result.product.id))
    if (!product) return
    setStuck(null)
    addToCart(sellOptions(fresh, [product], unsynced)[0])
  }

  /** Stock units of a product already in the cart, across all the units it's sold in. */
  const stockInCart = (lines, productId) => lines.filter((l) => l.productId === productId).reduce((sum, l) => sum + l.qty * l.perUnit, 0)

  function addToCart(s) {
    if (s.unitPrice === null || s.qtyAvailable <= 0) { setStuck({ option: s }); setQuery(''); return }
    if (s.controlled && features?.controlled_substances_register === false) {
      setErrorMessage(t('{name} is a controlled drug, and this branch is not set up to sell them. An owner can switch on the controlled drugs register under Settings > Features.', { name: s.name }))
      setQuery('')
      return
    }
    setErrorMessage('')
    setStuck(null)
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
    setCustomerId(''); setOnCredit(false); setCreditInput(''); setDiscountInput(''); setRx(NO_RX)
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
  // Pharmacies: for prescription-only and controlled medicine the till asks
  // for the patient and prescriber (optional).
  const needsRx = cart.some((l) => l.prescriptionOnly || l.controlled)
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
      setErrorMessage(apiErrorText(err, t('Could not record the sale.')))
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
          <h1 className="page-title">{t('Point of sale')}</h1>
          <div className="page-subtitle">
            {t('Shift opened {time} by {name}', { time: new Date(shift.opened_at).toLocaleTimeString(dateLocale(), { hour: '2-digit', minute: '2-digit' }), name: shift.cashier_name })}
            {' · '}{t(salesCount === 1 ? '{n} sale' : '{n} sales', { n: salesCount })} · {fmt(shiftTotal)}
            {unsent.length > 0 && ` · ${t('{n} not yet sent', { n: unsent.length })}`}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <Button onClick={() => setPanel(panel === 'sales' ? null : 'sales')}>{panel === 'sales' ? t('Back to till') : t('Shift sales')}</Button>
          <Button onClick={() => setPanel(panel === 'close' ? null : 'close')}>{panel === 'close' ? t('Back to till') : t('Close shift')}</Button>
        </div>
      </div>

      {offline && (
        <NoticeBox variant="warning" title={t('Offline: keep selling')} style={{ marginBottom: 16 }}>
          {t('Sales are saved on this till and sent as soon as the connection returns. Stock and prices are as of {time}.', { time: new Date(snapshot.generated_at).toLocaleTimeString(dateLocale(), { hour: '2-digit', minute: '2-digit' }) })}
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
                <Input value={query} onChange={(e) => { setQuery(e.target.value); setStuck(null) }} placeholder={t('Scan a barcode, or search by name, brand or size')} prefixIcon="search" disabled={!!completed || busy} />
              </div>
              {suggestions.length === 0 && query.trim().length >= 2 && !stuck && (
                <div className="pos-nomatch">{t('Nothing matches “{q}”. Press Enter for what to do.', { q: query.trim() })}</div>
              )}
              {suggestions.length > 0 && (
                <div style={{ position: 'absolute', top: 44, left: 0, right: 0, background: 'var(--white)', borderRadius: 'var(--radius-md)', boxShadow: 'var(--shadow-popover)', zIndex: 10, overflow: 'hidden' }}>
                  {suggestions.map((s) => {
                    const blocked = s.unitPrice === null || s.qtyAvailable <= 0
                    return (
                      <div
                        key={s.key}
                        onClick={() => addToCart(s)}
                        style={{ display: 'flex', justifyContent: 'space-between', gap: 12, padding: '10px 16px', cursor: 'pointer', fontSize: 14, borderBottom: '1px solid var(--grey-300)', opacity: blocked ? 0.6 : 1 }}
                      >
                        <div>
                          <div style={{ color: 'var(--grey-900)', display: 'flex', gap: 8, alignItems: 'center' }}>
                            {s.name}
                            <span style={{ fontSize: 12, color: 'var(--fg-subtle)' }}>{t('per {unit}', { unit: s.unitName })}</span>
                            {s.promotion && <Tag variant="positive">{t('Offer')}</Tag>}
                            {s.controlled ? <Tag variant="negative">{t('Controlled')}</Tag> : s.prescriptionOnly && <Tag variant="warning">{t('Prescription')}</Tag>}
                            {s.genericName && <span style={{ fontSize: 12, color: 'var(--fg-subtle)' }}>{s.genericName}</span>}
                          </div>
                          <div style={{ fontSize: 12, color: 'var(--fg-subtle)' }}>
                            {s.qtyAvailable > 0 ? t('{qty} {unit} in stock', { qty: s.qtyAvailable, unit: s.unitName }) : t('Out of stock')}
                            {s.unitPrice === null && ` · ${t('no selling price set')}`}
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
            {snapshot.products.length === 0 && !stuck && (
              <NoticeBox
                variant="info" title={t('There are no products to sell yet')}
                action={isOwner && <Button variant="primary" onClick={() => setFixing({})} disabled={offline}>{t('Add a product')}</Button>}
              >
                {isOwner ? t('Add what you sell with its price and how many you have, then come back here.') : t('Ask the shop owner to add the products you sell.')}
              </NoticeBox>
            )}
            {stuck && <CannotSell stuck={stuck} isOwner={isOwner} offline={offline} goTo={goTo} canGo={canGo} onFix={setFixing} onDismiss={() => setStuck(null)} />}
            {fixing && <QuickAddProduct product={fixing.product} initial={fixing.initial} storeId={storeId} onClose={() => setFixing(null)} onSaved={fixed} />}
            <div style={{ background: 'var(--white)', borderRadius: 'var(--radius-lg)', boxShadow: 'var(--shadow-card)' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr>
                    <th style={thStyle('center', 32)}>#</th>
                    <th style={thStyle('left')}>{t('Product')}</th>
                    <th style={thStyle('center')}>{t('Qty')}</th>
                    <th style={thStyle('right')}>{t('Line total')}</th>
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
                          {fmt(line.unitPrice)} {t('per {unit}', { unit: line.unitName })}{line.vatClass === 'standard' ? ` ${t('(incl. 18% VAT)')}` : ''}{line.promotion ? ` · ${line.promotion}` : ''}
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
                        <button onClick={() => setQty(line.key, 0)} disabled={busy} title={t('Remove')} style={removeBtnStyle}>
                          <Icon name="cross" size={16} />
                        </button>
                      </td>
                    </tr>
                  ))}
                  {cart.length === 0 && (
                    <tr><td colSpan={5} style={{ padding: '32px 16px', textAlign: 'center', fontSize: 14, color: 'var(--fg-subtle)' }}>
                      {completed ? t('Sale complete. Start a new sale when ready.') : t('Cart is empty. Search for a product to add it.')}
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
                    {discount > 0 && <div style={summaryRowStyle}><span>{t('Before discount')}</span><span>{fmt(gross)}</span></div>}
                    {discount > 0 && <div style={summaryRowStyle}><span>{t('Discount')}</span><span>− {fmt(discount)}</span></div>}
                    <div style={summaryRowStyle}><span>{t('Subtotal (excl. VAT)')}</span><span>{fmt(total - vat)}</span></div>
                    <div style={summaryRowStyle}><span>{t('VAT (18%, included)')}</span><span>{fmt(vat)}</span></div>
                    <div style={{ ...summaryRowStyle, fontSize: 17, fontWeight: 500, color: 'var(--grey-900)', padding: '8px 0', borderTop: '1px solid var(--grey-300)', marginTop: 4 }}>
                      <span>{t('Total')}</span><span>{fmt(total)}</span>
                    </div>
                    {creditAmount > 0 && (
                      <>
                        <div style={summaryRowStyle}><span>{t('On {name}’s account', { name: customer.name })}</span><span>{fmt(creditAmount)}</span></div>
                        <div style={{ ...summaryRowStyle, fontSize: 17, fontWeight: 500, color: 'var(--grey-900)' }}><span>{t('To pay now')}</span><span>{fmt(payable)}</span></div>
                      </>
                    )}
                  </div>

                  {needsRx && (
                    <div className="rx-box">
                      <div className="rx-title"><Icon name="pharmacy" size={16} /> {t('Prescription')}</div>
                      <p className="rx-hint">{t('This sale has medicine that needs a prescription. Note who it is for, if you wish (optional):')}</p>
                      <Field label={t('Patient name')}>
                        <Input value={rx.patient_name} onChange={(e) => setRx((r) => ({ ...r, patient_name: e.target.value }))} disabled={busy} />
                      </Field>
                      <Field label={t('Prescriber (doctor or clinic)')}>
                        <Input value={rx.prescriber_name} onChange={(e) => setRx((r) => ({ ...r, prescriber_name: e.target.value }))} disabled={busy} />
                      </Field>
                      <Field label={t('Prescription number')}>
                        <Input value={rx.prescription_ref} onChange={(e) => setRx((r) => ({ ...r, prescription_ref: e.target.value }))} disabled={busy} />
                      </Field>
                    </div>
                  )}
                  <Field label={t('Discount on the sale (TZS)')}>
                    <Input value={discountInput} onChange={(e) => setDiscountInput(e.target.value)} placeholder="0" disabled={busy || cart.length === 0} />
                  </Field>
                  {needsApproval && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: 12, background: 'var(--grey-100)', borderRadius: 'var(--radius-sm)' }}>
                      <div style={{ fontSize: 13, color: 'var(--grey-900)' }}>
                        {t('This discount is more than the {n}% a cashier may give. A manager approves it by entering their own login.', { n: discountLimit })}
                      </div>
                      {offline
                        ? <NoticeBox variant="warning">{t('Approving a discount needs the connection.')}</NoticeBox>
                        : (
                          <>
                            <Field label={t('Manager username')}><Input value={approver.username} onChange={(e) => setApprover({ ...approver, username: e.target.value })} /></Field>
                            <Field label={t('Manager password')}><Input type="password" value={approver.password} onChange={(e) => setApprover({ ...approver, password: e.target.value })} /></Field>
                          </>
                        )}
                    </div>
                  )}

                  {customers.length > 0 && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: customer ? 12 : 0, background: customer ? 'var(--grey-100)' : undefined, borderRadius: 'var(--radius-sm)' }}>
                      <Field label={t('Customer')}>
                        <Select
                          value={customerId}
                          onChange={(e) => { setCustomerId(e.target.value); if (!e.target.value) setOnCredit(false) }}
                          options={[{ value: '', label: t('Walk-in customer') }, ...customers.map((c) => ({ value: c.id, label: c.phone ? `${c.name} · ${c.phone}` : c.name }))]}
                        />
                      </Field>
                      {customer && (
                        <>
                          <div style={{ fontSize: 12, color: 'var(--fg-subtle)' }}>
                            {t('Owes')} {fmt(owing)}{customer.credit_limit !== null ? ` · ${t('credit limit {amount}', { amount: fmt(Number(customer.credit_limit)) })}` : ` · ${t('no credit limit')}`}
                          </div>
                          <Checkbox checked={onCredit} onChange={() => setOnCredit((v) => !v)} label={t('Put on the customer’s account (credit)')} />
                          {onCredit && (
                            <Field label={t('Amount on credit (blank = all of it)')}>
                              <Input value={creditInput} onChange={(e) => setCreditInput(e.target.value)} placeholder={String(Math.round(total))} disabled={busy} />
                            </Field>
                          )}
                          {overLimit && (
                            <NoticeBox variant="warning">
                              {t('{name} would owe {amount}, over their limit of {limit}. Take at most {max} on credit.', { name: customer.name, amount: fmt(owing + creditAmount), limit: fmt(Number(customer.credit_limit)), max: fmt(Math.max(Number(customer.credit_limit) - owing, 0)) })}
                            </NoticeBox>
                          )}
                        </>
                      )}
                    </div>
                  )}

                  {payable === 0 && cart.length > 0
                    ? <NoticeBox variant="info">{t('Nothing to pay now: the whole sale goes on {name}’s account.', { name: customer?.name })}</NoticeBox>
                    : (
                      <>
                  <div>
                    <div style={{ fontSize: 14, color: 'var(--grey-700)', marginBottom: 8 }}>{t('Payment method')}</div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                      {activeMethods.map((m) => (
                        <Radio key={m.id} checked={method?.id === m.id} onChange={() => setPaymentMethodId(m.id)} label={t(m.name)} />
                      ))}
                    </div>
                  </div>

                  {isCash
                    ? (
                      <div>
                        <Field label={t('Amount tendered')}>
                          <Input value={tendered} onChange={(e) => setTendered(e.target.value)} placeholder="0" disabled={busy} />
                        </Field>
                        {tenderedNum > 0 && (
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 15, fontWeight: 500, color: change < 0 ? 'var(--status-error)' : 'var(--grey-900)', marginTop: 8 }}>
                            <span>{change < 0 ? t('Amount still due') : t('Change due')}</span><span>{fmt(Math.abs(change))}</span>
                          </div>
                        )}
                      </div>
                    )
                    : (
                      <Field label={t('{method} transaction reference', { method: method?.name ? t(method.name) : t('Payment') })} required>
                        <Input value={reference} onChange={(e) => setReference(e.target.value)} placeholder={t('e.g. QK7Y2ZT1')} disabled={busy} />
                      </Field>
                    )}
                      </>
                    )}

                  {errorMessage && <NoticeBox variant="error" title={t('Sale not completed')}>{errorMessage}</NoticeBox>}
                  <Button variant="primary" onClick={completeSale} disabled={!canComplete} style={{ width: '100%', height: 43 }}>
                    {busy ? t('Recording…') : t('Complete sale')}
                  </Button>
                  {cart.length > 0 && <Button onClick={newSale} disabled={busy}>{t('Clear cart')}</Button>}
                </>
              )}
          </div>
        </div>
      )}

      {printSale && <PrintArea kind="receipt"><Receipt sale={printSale} entity={entity} store={store} /></PrintArea>}
    </div>
  )
}
