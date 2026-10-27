import { useEffect, useState } from 'react'
import { Button, Card, Chip, Field, Input, NoticeBox, PageHeader, Select, Tag } from '../components/ds/index.js'
import { useApi } from '../hooks/useApi.js'
import { searchProducts, listAllUnitsOfMeasure } from '../api/catalog.js'
import {
  listAllSuppliers, listInvoices, getInvoice, createInvoice, updateInvoice, receiveInvoice, addInvoiceLine, payInvoice,
} from '../api/receiving.js'
import { fmt } from '../appData.js'
import { apiErrorText } from '../lib/apiError.js'

const rawInputStyle = { height: 32, border: '1px solid var(--grey-500)', borderRadius: 'var(--radius-sm)', padding: '0 8px', fontFamily: 'var(--font-family)' }

/** Stock is held in the product's own unit; when the invoice is in a
 * bigger pack, show what the line will add to stock ("= 48 Bottle"). */
function stockQtyHint(line, uoms) {
  if (!line.productUomId || !line.uomId || line.uomId === line.productUomId || !line.orderQty) return ''
  const from = (uoms ?? []).find((u) => u.id === line.uomId)
  const to = (uoms ?? []).find((u) => u.id === line.productUomId)
  if (!from || !to) return ''
  const qty = Number(line.orderQty) * Number(from.unit_value) / Number(to.unit_value)
  return Number.isFinite(qty) ? `= ${Math.round(qty * 100) / 100} ${to.name}` : ''
}

function emptyLine() {
  return { tempId: 'l' + Date.now() + Math.random(), productId: '', productName: '', tracksExpiry: false, uomId: '', orderQty: '', packPrice: '', batchNo: '', expiry: '' }
}

export default function Receiving({ storeId, role }) {
  const isManager = ['store_manager', 'entity_admin'].includes(role)
  const [openedInvoice, setOpenedInvoice] = useState(null)
  const [tab, setTab] = useState('new')
  const [invoiceId, setInvoiceId] = useState(null)
  const [invoiceStatus, setInvoiceStatus] = useState('draft')
  const [supplierId, setSupplierId] = useState('')
  const [invoiceNumber, setInvoiceNumber] = useState('')
  const [receivedDate, setReceivedDate] = useState(new Date().toISOString().slice(0, 10))
  const [savedLines, setSavedLines] = useState([])
  const [pendingLines, setPendingLines] = useState([emptyLine()])
  const [productQuery, setProductQuery] = useState({})
  const [productSuggestions, setProductSuggestions] = useState({})
  const [saving, setSaving] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')

  const [filters, setFilters] = useState({ supplier: '', status: '', receivedDateAfter: '', receivedDateBefore: '' })

  const { data: suppliers } = useApi(() => (storeId ? listAllSuppliers() : null), [storeId])
  const { data: uoms } = useApi(() => (storeId ? listAllUnitsOfMeasure() : null), [storeId])
  const { data: invoicesPage, loading: invoicesLoading, refetch: refetchInvoices } = useApi(
    () => (storeId && tab === 'list' ? listInvoices({
      store: storeId, supplier: filters.supplier || undefined, status: filters.status || undefined,
      received_date_after: filters.receivedDateAfter || undefined, received_date_before: filters.receivedDateBefore || undefined,
    }) : null),
    [storeId, tab, filters],
  )

  function resetForm() {
    setInvoiceId(null); setInvoiceStatus('draft')
    setSupplierId(''); setInvoiceNumber(''); setReceivedDate(new Date().toISOString().slice(0, 10))
    setSavedLines([]); setPendingLines([emptyLine()])
    setProductQuery({}); setProductSuggestions({}); setErrorMessage('')
  }

  async function openInvoice(id) {
    const inv = await getInvoice(id)
    setOpenedInvoice(inv)
    setInvoiceId(inv.id); setInvoiceStatus(inv.status)
    setSupplierId(inv.supplier); setInvoiceNumber(inv.invoice_number); setReceivedDate(inv.received_date)
    setSavedLines(inv.lines)
    setPendingLines(inv.status === 'draft' ? [emptyLine()] : [])
    setProductQuery({}); setProductSuggestions({}); setErrorMessage('')
    setTab('new')
  }

  useEffect(() => {
    const timers = Object.entries(productQuery).map(([tempId, q]) => {
      if (!q || q.trim().length === 0) {
        setProductSuggestions((prev) => ({ ...prev, [tempId]: [] }))
        return null
      }
      return setTimeout(async () => {
        try {
          const res = await searchProducts(q.trim())
          setProductSuggestions((prev) => ({ ...prev, [tempId]: res.results.slice(0, 5) }))
        } catch { setProductSuggestions((prev) => ({ ...prev, [tempId]: [] })) }
      }, 250)
    })
    return () => timers.forEach((t) => t && clearTimeout(t))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [productQuery])

  function updatePendingLine(tempId, patch) {
    setPendingLines((prev) => prev.map((l) => (l.tempId === tempId ? { ...l, ...patch } : l)))
  }
  function selectProductForLine(tempId, product) {
    updatePendingLine(tempId, { productId: product.id, productName: product.name, tracksExpiry: product.tracks_expiry, uomId: product.uom, productUomId: product.uom })
    setProductQuery((prev) => ({ ...prev, [tempId]: '' }))
    setProductSuggestions((prev) => ({ ...prev, [tempId]: [] }))
  }
  const addLineRow = () => setPendingLines((prev) => [...prev, emptyLine()])

  /** A barcode scanner types the code and presses Enter: an exact barcode
   * (or the only match) is chosen straight away, and a fresh line opens
   * for the next scan. */
  async function onProductKeyDown(e, tempId) {
    if (e.key !== 'Enter') return
    const q = (productQuery[tempId] ?? '').trim()
    if (!q) return
    e.preventDefault()
    try {
      const { results } = await searchProducts(q)
      const match = results.find((p) => p.barcode && p.barcode === q) ?? (results.length === 1 ? results[0] : null)
      if (match) {
        selectProductForLine(tempId, match)
        if (pendingLines[pendingLines.length - 1]?.tempId === tempId) addLineRow()
      }
    } catch { /* the suggestions list still works */ }
  }

  function lineToPayload(l) {
    return {
      product: l.productId, uom: l.uomId, order_qty: l.orderQty || 0, pack_price: l.packPrice || 0,
      batch_no: l.batchNo, expiry_date: l.expiry || null,
    }
  }

  async function persistPendingLines(targetInvoiceId) {
    const complete = pendingLines.filter((l) => l.productId && l.uomId && l.orderQty)
    for (const line of complete) {
      await addInvoiceLine({ invoice: targetInvoiceId, ...lineToPayload(line) })
    }
  }

  async function saveDraft() {
    if (!supplierId || !invoiceNumber.trim()) { setErrorMessage('Supplier and invoice number are required.'); return }
    setSaving(true); setErrorMessage('')
    try {
      let id = invoiceId
      if (id) {
        await updateInvoice(id, { supplier: supplierId, invoice_number: invoiceNumber, received_date: receivedDate })
        await persistPendingLines(id)
      } else {
        const complete = pendingLines.filter((l) => l.productId && l.uomId && l.orderQty)
        const inv = await createInvoice({
          store: storeId, supplier: supplierId, invoice_number: invoiceNumber, received_date: receivedDate,
          lines: complete.map(lineToPayload),
        })
        id = inv.id
      }
      await openInvoice(id)
      setTab('list')
      refetchInvoices()
    } catch (err) {
      setErrorMessage(err.body?.detail || firstFieldError(err.body) || 'Could not save the invoice.')
    } finally {
      setSaving(false)
    }
  }

  async function saveAndReceive() {
    if (!supplierId || !invoiceNumber.trim()) { setErrorMessage('Supplier and invoice number are required.'); return }
    setSaving(true); setErrorMessage('')
    try {
      let id = invoiceId
      if (id) {
        await updateInvoice(id, { supplier: supplierId, invoice_number: invoiceNumber, received_date: receivedDate })
        await persistPendingLines(id)
      } else {
        const complete = pendingLines.filter((l) => l.productId && l.uomId && l.orderQty)
        if (complete.length === 0) { setErrorMessage('Add at least one complete line.'); setSaving(false); return }
        const inv = await createInvoice({
          store: storeId, supplier: supplierId, invoice_number: invoiceNumber, received_date: receivedDate,
          lines: complete.map(lineToPayload),
        })
        id = inv.id
      }
      await receiveInvoice(id)
      resetForm()
      setTab('list')
      refetchInvoices()
    } catch (err) {
      setErrorMessage(err.body?.detail || firstFieldError(err.body) || 'Could not receive the invoice.')
    } finally {
      setSaving(false)
    }
  }

  const supplierOptions = (suppliers ?? []).map((s) => ({ label: s.name, value: s.id }))
  const uomOptions = (uoms ?? []).map((u) => ({ label: u.name, value: u.id }))
  const invoices = invoicesPage?.results ?? []
  const supplierNameById = Object.fromEntries((suppliers ?? []).map((s) => [s.id, s.name]))
  const isReadOnly = invoiceStatus === 'received'

  if (!storeId) return <NoticeBox variant="warning" title="No store selected">Select a store to manage receiving.</NoticeBox>

  return (
    <div>
      <PageHeader title="Receiving" subtitle="Record supplier invoices and add the stock they bring in." />
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <Chip selected={tab === 'new'} onClick={() => { resetForm(); setTab('new') }}>New invoice</Chip>
        <Chip selected={tab === 'list'} onClick={() => setTab('list')}>Invoice list</Chip>
      </div>

      {tab === 'new' && (
        <Card>
          {errorMessage && <div style={{ marginBottom: 16 }}><NoticeBox variant="error">{errorMessage}</NoticeBox></div>}
          {invoiceId && <div style={{ marginBottom: 16 }}><Tag variant={isReadOnly ? 'positive' : undefined}>{isReadOnly ? 'Received' : 'Draft — resumed'}</Tag></div>}

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 16, marginBottom: 20 }}>
            <Field label="Supplier" required>
              <Select value={supplierId} onChange={(e) => setSupplierId(e.target.value)} options={[{ label: 'Select supplier…', value: '' }, ...supplierOptions]} />
            </Field>
            <Field label="Invoice number" required>
              <Input value={invoiceNumber} onChange={(e) => setInvoiceNumber(e.target.value)} placeholder="e.g. INV-2026-0087" disabled={isReadOnly} />
            </Field>
            <Field label="Received date" required>
              <Input type="date" value={receivedDate} onChange={(e) => setReceivedDate(e.target.value)} disabled={isReadOnly} />
            </Field>
          </div>

          <table className="rcv-lines" style={{ width: '100%', borderCollapse: 'collapse', marginBottom: 12 }}>
            <thead>
              <tr>
                <th style={th('left')}>Product</th>
                <th style={th('left')}>UoM</th>
                <th style={th('right')}>Order qty</th>
                <th style={th('right')}>Pack price</th>
                <th style={th('left')}>Batch no.</th>
                <th style={th('left')}>Expiry</th>
              </tr>
            </thead>
            <tbody>
              {savedLines.map((l) => (
                <tr key={l.id}>
                  <td data-label="Product" style={td()}>{l.product_name ?? l.product}</td>
                  <td data-label="UoM" style={{ ...td(), color: 'var(--grey-700)' }}>{l.uom_name ?? ''}</td>
                  <td data-label="Order qty" style={{ ...td('right') }}>{l.order_qty}</td>
                  <td data-label="Pack price" style={{ ...td('right') }}>{l.pack_price}</td>
                  <td data-label="Batch no." style={td()}>{l.batch_no}</td>
                  <td data-label="Expiry" style={td()}>{l.expiry_date || '—'}</td>
                </tr>
              ))}
              {!isReadOnly && pendingLines.map((l) => (
                <tr key={l.tempId}>
                  <td data-label="Product" style={{ ...td(), position: 'relative' }}>
                    {l.productId ? l.productName : (
                      <>
                        <input
                          value={productQuery[l.tempId] ?? ''}
                          onChange={(e) => setProductQuery((prev) => ({ ...prev, [l.tempId]: e.target.value }))}
                          onKeyDown={(e) => onProductKeyDown(e, l.tempId)}
                          placeholder="Scan or search product…" style={{ ...rawInputStyle, width: 180 }}
                        />
                        {(productSuggestions[l.tempId]?.length ?? 0) > 0 && (
                          <div style={{ position: 'absolute', top: 34, left: 0, zIndex: 10, background: 'var(--white)', boxShadow: 'var(--shadow-popover)', borderRadius: 'var(--radius-md)', minWidth: 220 }}>
                            {productSuggestions[l.tempId].map((p) => (
                              <div key={p.id} onClick={() => selectProductForLine(l.tempId, p)} style={{ padding: '8px 12px', fontSize: 13, cursor: 'pointer', borderBottom: '1px solid var(--grey-300)' }}>{p.name}</div>
                            ))}
                          </div>
                        )}
                      </>
                    )}
                  </td>
                  <td data-label="UoM" style={td()}>
                    <Select value={l.uomId} onChange={(e) => updatePendingLine(l.tempId, { uomId: e.target.value })} options={[{ label: '—', value: '' }, ...uomOptions]} style={{ width: 130 }} />
                  </td>
                  <td data-label="Order qty" style={{ ...td('right') }}>
                    <input value={l.orderQty} onChange={(e) => updatePendingLine(l.tempId, { orderQty: e.target.value })} style={{ ...rawInputStyle, width: 64, textAlign: 'right' }} />
                    {stockQtyHint(l, uoms) && <div style={{ fontSize: 11, color: 'var(--fg-subtle)', marginTop: 2, whiteSpace: 'nowrap' }}>{stockQtyHint(l, uoms)}</div>}
                  </td>
                  <td data-label="Pack price" style={{ ...td('right') }}>
                    <input value={l.packPrice} onChange={(e) => updatePendingLine(l.tempId, { packPrice: e.target.value })} style={{ ...rawInputStyle, width: 80, textAlign: 'right' }} />
                  </td>
                  <td data-label="Batch no." style={td()}>
                    <input value={l.batchNo} onChange={(e) => updatePendingLine(l.tempId, { batchNo: e.target.value })} placeholder="Optional" style={{ ...rawInputStyle, width: 100 }} />
                  </td>
                  <td data-label="Expiry" style={td()}>
                    {!l.productId || l.tracksExpiry
                      ? <input type="date" value={l.expiry} onChange={(e) => updatePendingLine(l.tempId, { expiry: e.target.value })} style={{ ...rawInputStyle, width: 130 }} />
                      : <span style={{ fontSize: 12, color: 'var(--fg-subtle)' }}>Does not expire</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!isReadOnly && <Button onClick={addLineRow}>+ Add line</Button>}
          {isReadOnly && openedInvoice?.id === invoiceId && (
            <InvoicePayments invoice={openedInvoice} canPay={isManager} onPaid={setOpenedInvoice} />
          )}

          {!isReadOnly && (
            <div style={{ display: 'flex', gap: 12, marginTop: 20, paddingTop: 16, borderTop: '1px solid var(--grey-300)' }}>
              <Button onClick={saveDraft} disabled={saving}>Save as draft</Button>
              <Button variant="primary" onClick={saveAndReceive} disabled={saving}>Save and receive</Button>
            </div>
          )}
        </Card>
      )}

      {tab === 'list' && (
        <>
          <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <Field label="Supplier"><Select value={filters.supplier} onChange={(e) => setFilters((f) => ({ ...f, supplier: e.target.value }))} options={[{ label: 'All suppliers', value: '' }, ...supplierOptions]} style={{ width: 200 }} /></Field>
            <Field label="Status"><Select value={filters.status} onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))} options={[{ label: 'All', value: '' }, { label: 'Draft', value: 'draft' }, { label: 'Received', value: 'received' }]} style={{ width: 140 }} /></Field>
            <Field label="From"><Input type="date" value={filters.receivedDateAfter} onChange={(e) => setFilters((f) => ({ ...f, receivedDateAfter: e.target.value }))} /></Field>
            <Field label="To"><Input type="date" value={filters.receivedDateBefore} onChange={(e) => setFilters((f) => ({ ...f, receivedDateBefore: e.target.value }))} /></Field>
          </div>

          {invoicesLoading && <NoticeBox variant="info">Loading…</NoticeBox>}
          {!invoicesLoading && (
            <div className="ds-table-card">
              <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 560 }}>
                <thead>
                  <tr>
                    <th style={th('left')}>Invoice #</th>
                    <th style={th('left')}>Supplier</th>
                    <th style={th('left')}>Received date</th>
                    <th style={th('left')}>Status</th>
                    <th style={th('right')}>Total</th>
                    <th style={th('right')}>Still owed</th>
                    <th style={th('left')}>Due</th>
                    <th style={{ width: 100, borderBottom: '1px solid var(--grey-300)' }} />
                  </tr>
                </thead>
                <tbody>
                  {invoices.map((inv) => (
                    <tr key={inv.id}>
                      <td style={{ ...td(), fontFamily: 'var(--font-family-mono)' }}>{inv.invoice_number}</td>
                      <td style={td()}>{supplierNameById[inv.supplier] ?? inv.supplier}</td>
                      <td style={{ ...td(), color: 'var(--grey-700)' }}>{inv.received_date}</td>
                      <td style={td()}>
                        {inv.status === 'draft' && <Tag>Draft</Tag>}
                        {inv.status === 'received' && <Tag variant="positive">Received</Tag>}
                      </td>
                      <td style={{ ...td('right') }}>{fmt(Number(inv.total))}</td>
                      <td style={{ ...td('right') }}>
                        {inv.status !== 'received' ? '—' : Number(inv.balance) > 0 ? fmt(Number(inv.balance)) : <Tag variant="positive">Paid</Tag>}
                      </td>
                      <td style={{ ...td(), color: isOverdue(inv) ? 'var(--status-error)' : 'var(--grey-700)' }}>
                        {inv.status === 'received' ? inv.due_date ?? '—' : '—'}
                      </td>
                      <td style={{ ...td('right') }}>
                        <Button size="small" onClick={() => openInvoice(inv.id)}>{inv.status === 'draft' ? 'Resume' : 'View'}</Button>
                      </td>
                    </tr>
                  ))}
                  {invoices.length === 0 && (
                    <tr><td colSpan={8} style={{ padding: '32px 16px', textAlign: 'center', fontSize: 14, color: 'var(--fg-subtle)' }}>No invoices match this filter.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function firstFieldError(body) {
  if (!body || typeof body !== 'object') return null
  const firstKey = Object.keys(body)[0]
  const val = body[firstKey]
  return Array.isArray(val) ? `${firstKey}: ${val[0]}` : null
}

function th(align) {
  return { textAlign: align || 'left', fontWeight: 600, fontSize: 11, lineHeight: '16px', textTransform: 'uppercase', letterSpacing: 1.2, color: 'var(--fg-subtle)', padding: '12px 16px', borderBottom: '1px solid var(--grey-300)' }
}
function td(align) {
  return { padding: '14px 16px', borderBottom: '1px solid var(--grey-300)', textAlign: align || 'left', fontSize: 14 }
}

const today = () => new Date().toISOString().slice(0, 10)
const isOverdue = (inv) => inv.status === 'received' && Number(inv.balance) > 0 && inv.due_date && inv.due_date < today()

const PAY_METHODS = [
  { value: 'bank', label: 'Bank transfer' }, { value: 'mobile_money', label: 'Mobile money' },
  { value: 'cash', label: 'Cash' }, { value: 'cheque', label: 'Cheque' },
]

/** What has been paid against a received supplier invoice, and (for
 * managers) recording a payment. */
function InvoicePayments({ invoice, canPay, onPaid }) {
  const balance = Number(invoice.balance)
  const [form, setForm] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit() {
    setBusy(true); setError('')
    try {
      onPaid(await payInvoice(invoice.id, {
        amount: String(form.amount).replace(/[,\s]/g, ''), paid_on: form.paid_on, method: form.method, reference: form.reference,
      }))
      setForm(null)
    } catch (err) {
      setError(apiErrorText(err, 'Could not record the payment.'))
    } finally { setBusy(false) }
  }

  return (
    <div style={{ marginTop: 20, paddingTop: 16, borderTop: '1px solid var(--grey-300)' }}>
      <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', alignItems: 'baseline', marginBottom: 12 }}>
        <span style={{ fontSize: 14 }}>Invoice total <b>{fmt(Number(invoice.total))}</b></span>
        <span style={{ fontSize: 14 }}>Paid <b>{fmt(Number(invoice.amount_paid))}</b></span>
        <span style={{ fontSize: 14, color: balance > 0 ? 'var(--status-error)' : 'var(--green-700)' }}>
          {balance > 0 ? <>Still owed <b>{fmt(balance)}</b>{invoice.due_date && ` · due ${invoice.due_date}`}</> : 'Paid in full'}
        </span>
      </div>
      {invoice.payments.length > 0 && (
        <table style={{ borderCollapse: 'collapse', fontSize: 13, marginBottom: 12 }}>
          <tbody>
            {invoice.payments.map((p) => (
              <tr key={p.id}>
                <td style={{ padding: '4px 16px 4px 0' }}>{p.paid_on}</td>
                <td style={{ padding: '4px 16px 4px 0' }}>{fmt(Number(p.amount))}</td>
                <td style={{ padding: '4px 16px 4px 0' }}>{p.method_label}{p.reference && ` · ${p.reference}`}</td>
                <td style={{ padding: '4px 0', color: 'var(--fg-subtle)' }}>by {p.recorded_by_name}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {error && <NoticeBox variant="error" style={{ marginBottom: 12 }}>{error}</NoticeBox>}
      {canPay && balance > 0 && !form && (
        <Button onClick={() => setForm({ amount: String(balance), paid_on: today(), method: 'bank', reference: '' })}>Record a payment</Button>
      )}
      {canPay && form && (
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <Field label="Amount"><Input value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} style={{ width: 130 }} /></Field>
          <Field label="Paid on"><Input type="date" value={form.paid_on} onChange={(e) => setForm({ ...form, paid_on: e.target.value })} style={{ width: 160 }} /></Field>
          <Field label="Method"><Select value={form.method} onChange={(e) => setForm({ ...form, method: e.target.value })} options={PAY_METHODS} style={{ width: 150 }} /></Field>
          <Field label="Reference"><Input value={form.reference} onChange={(e) => setForm({ ...form, reference: e.target.value })} placeholder="Bank / M-Pesa ref" style={{ width: 160 }} /></Field>
          <Button variant="primary" onClick={submit} disabled={busy}>Save payment</Button>
          <Button onClick={() => setForm(null)} disabled={busy}>Cancel</Button>
        </div>
      )}
      {!canPay && balance > 0 && <div style={{ fontSize: 13, color: 'var(--fg-subtle)' }}>A store manager records payments to suppliers.</div>}
    </div>
  )
}
