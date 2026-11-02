import { Fragment, useEffect, useState } from 'react'
import { Button, Card, Chip, Field, Icon, Input, NoticeBox, Select, Tag } from '../components/ds/index.js'
import PrintArea from '../components/PrintArea.jsx'
import { useApi } from '../hooks/useApi.js'
import { searchProducts } from '../api/catalog.js'
import { listAllBatches } from '../api/inventory.js'
import { listAllStores } from '../api/core.js'
import { listPaymentMethods } from '../api/payments.js'
import {
  listEnquiries, createEnquiry, rejectEnquiry, cancelEnquiry, fulfillEnquiry,
  listTransfers, sendTransfer, confirmReceipt, resolveTransfer, cancelTransfer, payTransfer,
} from '../api/enquiry.js'
import { fmt } from '../appData.js'
import { apiErrorText } from '../lib/apiError.js'
import { dateLocale, t, tOptions, useT } from '../i18n/index.js'

const RESOLUTIONS = [
  { value: 'return_to_sender', label: 'It never left: put it back in stock at the sending store' },
  { value: 'received_late', label: 'It turned up: add it to the receiving store' },
  { value: 'write_off', label: 'Lost on the way: write it off' },
]
const STATUS_TAG = { dispatched: undefined, received: 'positive', discrepancy: 'negative', cancelled: 'neutral' }
const qtyText = (n) => Number(n).toLocaleString('en-US')
const todayIso = () => new Date().toISOString().slice(0, 10)

/** Unexpired stock of each product at `store`: {productId: qty}. */
async function availableAt(store, productIds) {
  const out = {}
  await Promise.all(productIds.map(async (product) => {
    const batches = await listAllBatches({ store, product })
    out[product] = batches.filter((b) => !b.expiry_date || b.expiry_date >= todayIso()).reduce((s, b) => s + Number(b.qty_on_hand), 0)
  }))
  return out
}

export default function Enquiries({ storeId, entity, roles }) {
  useT()
  const { data: stores } = useApi(() => listAllStores({ is_active: true }), [])
  // An entity admin viewing "All stores" picks which store they act for.
  const [pickedStore, setActingStore] = useState(null)
  const store = storeId || pickedStore || (roles.includes('entity_admin') ? stores?.[0]?.id : null)
  const [tab, setTab] = useState('requests')
  const [printing, setPrinting] = useState(null)

  const { data: openPage, refetch: refetchOpen } = useApi(() => listEnquiries({ status: 'open' }), [])
  const { data: transfersPage, refetch: refetchTransfers } = useApi(() => listTransfers(), [])
  const refresh = () => { refetchOpen(); refetchTransfers() }
  const storeName = (id) => stores?.find((s) => s.id === id)?.name ?? ''
  const isHub = !!entity?.main_store
  const isMain = isHub && entity.main_store === store

  const requests = (openPage?.results ?? []).filter((e) => e.requesting_store === store || e.mode === 'broadcast' || e.target_store === store)
  const transfers = transfersPage?.results ?? []
  const incoming = transfers.filter((tx) => tx.to_store === store && tx.status === 'dispatched').length

  function print(tx) {
    setPrinting(tx)
    setTimeout(() => window.print(), 50)
  }

  if (!store) return <NoticeBox variant="warning" title={t('No store selected')}>{t('Select a store to work with enquiries and transfers.')}</NoticeBox>
  return (
    <div>
      <h1 className="page-title">{t('Enquiries & transfers')}</h1>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, margin: '4px 0 24px', fontSize: 14, color: 'var(--muted)', flexWrap: 'wrap' }}>
        {storeId ? <span>{t('Working as')} {storeName(store)}</span> : (
          <>
            <span>{t('Working as')}</span>
            <Select value={store} onChange={(e) => setActingStore(e.target.value)} options={(stores ?? []).map((s) => ({ value: s.id, label: s.name }))} style={{ width: 240 }} />
          </>
        )}
        <span>· {isHub ? t('Hub mode: branches ask {store}, and pay for what it sends at cost.', { store: storeName(entity.main_store) }) : t('Peer mode: any store can answer a request.')}</span>
      </div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        <Chip selected={tab === 'requests'} onClick={() => setTab('requests')}>{t('Requests ({n})', { n: requests.length })}</Chip>
        <Chip selected={tab === 'ask'} onClick={() => setTab('ask')}>{t('Ask for stock')}</Chip>
        <Chip selected={tab === 'send'} onClick={() => setTab('send')}>{t('Send stock')}</Chip>
        <Chip selected={tab === 'transfers'} onClick={() => setTab('transfers')}>{t('Transfers')}{incoming ? ` (${t('{n} arriving', { n: incoming })})` : ''}</Chip>
      </div>

      {tab === 'requests' && <Requests store={store} requests={requests} onChanged={() => { refresh(); }} onSent={() => { refresh(); setTab('transfers') }} />}
      {tab === 'ask' && <AskForStock store={store} isHub={isHub} isMain={isMain} mainName={storeName(entity?.main_store)} onPosted={() => { refetchOpen(); setTab('requests') }} />}
      {tab === 'send' && <SendStock store={store} stores={(stores ?? []).filter((s) => s.id !== store)} onSent={() => { refetchTransfers(); setTab('transfers') }} />}
      {tab === 'transfers' && <Transfers store={store} transfers={transfers} onChanged={refetchTransfers} onPrint={print} />}

      {printing && (
        <PrintArea kind="report">
          <DeliveryNote transfer={printing} entity={entity} />
        </PrintArea>
      )}
    </div>
  )
}

function Requests({ store, requests, onChanged, onSent }) {
  useT()
  const [fulfilling, setFulfilling] = useState(null) // {enquiry, lines: [{product, name, unit, requested, available, qty}]}
  const [error, setError] = useState('')

  async function openFulfill(enquiry) {
    setError('')
    const available = await availableAt(store, enquiry.lines.map((l) => l.product))
    setFulfilling({
      enquiry, note: '',
      lines: enquiry.lines.map((l) => {
        const have = available[l.product] ?? 0
        return { product: l.product, name: l.product_name, unit: l.unit, requested: Number(l.qty_requested), available: have, qty: String(Math.min(Number(l.qty_requested), have)) }
      }),
    })
  }
  async function send() {
    const lines = fulfilling.lines.filter((l) => Number(l.qty) > 0).map((l) => ({ product: l.product, qty: l.qty }))
    if (!lines.length) { setError(t('You have none of this in stock to send.')); return }
    try {
      await fulfillEnquiry(fulfilling.enquiry.id, { fromStore: store, lines, note: fulfilling.note })
      setFulfilling(null)
      onSent()
    } catch (err) {
      setError(apiErrorText(err, t('Could not send the stock.')))
    }
  }
  async function act(fn, id) {
    setError('')
    try { await fn(id); onChanged() } catch (err) { setError(apiErrorText(err, t('Could not update the enquiry.'))) }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 760 }}>
      {error && !fulfilling && <NoticeBox variant="error">{error}</NoticeBox>}
      {requests.map((eq) => {
        const mine = eq.requesting_store === store
        const canReject = eq.mode === 'hub' && eq.target_store === store
        return (
          <Card key={eq.id}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
              <div>
                <div style={{ fontSize: 14, color: 'var(--grey-900)', marginBottom: 4 }}>
                  {eq.lines.map((l) => `${l.product_name} · ${qtyText(l.qty_requested)} ${l.unit}`).join(', ')}
                </div>
                <div style={{ fontSize: 12, color: 'var(--fg-subtle)' }}>
                  {mine ? t('Asked by your store') : t('From {store}', { store: eq.requesting_store_name })}{eq.created_by_name && ` (${eq.created_by_name})`}
                  {' · '}{new Date(eq.created_at).toLocaleString(dateLocale())}
                  {eq.mode === 'hub' && !mine && ` · ${t('to the main store')}`}
                </div>
                {eq.note && <div style={{ fontSize: 13, color: 'var(--grey-700)', marginTop: 4 }}>“{eq.note}”</div>}
              </div>
              <Tag variant={eq.mode === 'hub' ? 'neutral' : undefined}>{eq.mode === 'hub' ? t('To main store') : t('Any store')}</Tag>
            </div>
            <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
              {!mine && (eq.mode === 'broadcast' || canReject) && <Button variant="primary" size="small" onClick={() => openFulfill(eq)}>{t('Send stock')}</Button>}
              {canReject && <Button size="small" onClick={() => act(rejectEnquiry, eq.id)}>{t('Turn down')}</Button>}
              {mine && <Button size="small" onClick={() => act(cancelEnquiry, eq.id)}>{t('Withdraw')}</Button>}
            </div>
            {fulfilling?.enquiry.id === eq.id && (
              <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid var(--grey-300)' }}>
                {error && <NoticeBox variant="error" style={{ marginBottom: 12 }}>{error}</NoticeBox>}
                <p style={{ fontSize: 13, color: 'var(--fg-subtle)', margin: '0 0 8px' }}>{t('Batches are picked earliest expiry first. Expired stock is never sent.')}</p>
                {fulfilling.lines.map((l, i) => (
                  <div key={l.product} style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8, fontSize: 13 }}>
                    <span style={{ flex: '1 1 auto' }}>{l.name} <span style={{ color: 'var(--fg-subtle)' }}>({t('asked {qty} {unit}', { qty: qtyText(l.requested), unit: l.unit })})</span></span>
                    <span style={{ color: l.available ? 'var(--fg-subtle)' : 'var(--red-700)' }}>{l.available ? t('{qty} in stock', { qty: qtyText(l.available) }) : t('None in stock')}</span>
                    <Input value={l.qty} style={{ width: 90 }} disabled={!l.available}
                      onChange={(e) => setFulfilling((f) => ({ ...f, lines: f.lines.map((x, j) => (j === i ? { ...x, qty: e.target.value } : x)) }))} />
                  </div>
                ))}
                <Field label={t('Note for the receiving store')}><Input value={fulfilling.note} onChange={(e) => setFulfilling((f) => ({ ...f, note: e.target.value }))} placeholder={t('e.g. Sent with the boda boda, 2 boxes')} /></Field>
                <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                  <Button variant="primary" size="small" onClick={send}>{t('Send now')}</Button>
                  <Button size="small" onClick={() => setFulfilling(null)}>{t('Cancel')}</Button>
                </div>
              </div>
            )}
          </Card>
        )
      })}
      {requests.length === 0 && <NoticeBox variant="info">{t('There are no open requests right now.')}</NoticeBox>}
    </div>
  )
}

/** Product picker + quantity lines, shared by "Ask for stock" and "Send stock". */
function useLines() {
  const [lines, setLines] = useState([])
  const [query, setQuery] = useState('')
  const [suggestions, setSuggestions] = useState([])
  useEffect(() => {
    const q = query.trim()
    if (!q) return
    let cancelled = false
    const timer = setTimeout(async () => {
      try {
        const res = await searchProducts(q)
        if (!cancelled) setSuggestions(res.results.slice(0, 6))
      } catch { if (!cancelled) setSuggestions([]) }
    }, 250)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [query])
  return {
    lines, query, suggestions: query.trim() ? suggestions : [], setQuery,
    add: (p, extra = {}) => {
      setLines((prev) => (prev.some((l) => l.product === p.id) ? prev : [...prev, { product: p.id, name: p.name, unit: p.uom_name || '', qty: '', ...extra }]))
      setQuery(''); setSuggestions([])
    },
    setQty: (product, qty) => setLines((prev) => prev.map((l) => (l.product === product ? { ...l, qty } : l))),
    remove: (product) => setLines((prev) => prev.filter((l) => l.product !== product)),
    clear: () => setLines([]),
  }
}

function ProductPicker({ picker, onPick }) {
  useT()
  return (
    <div style={{ position: 'relative' }}>
      <Field label={t('Add a product')}><Input value={picker.query} onChange={(e) => picker.setQuery(e.target.value)} placeholder={t('Search by name')} prefixIcon="search" /></Field>
      {picker.suggestions.length > 0 && (
        <div style={{ position: 'absolute', top: 62, left: 0, right: 0, background: 'var(--white)', boxShadow: 'var(--shadow-popover)', borderRadius: 'var(--radius-md)', zIndex: 10 }}>
          {picker.suggestions.map((p) => (
            <div key={p.id} onClick={() => onPick(p)} style={{ padding: '8px 12px', fontSize: 13, cursor: 'pointer', borderBottom: '1px solid var(--grey-300)' }}>
              {p.name}{p.size && <span style={{ color: 'var(--fg-subtle)' }}> · {p.size}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function LinesTable({ picker, showAvailable }) {
  useT()
  if (!picker.lines.length) return null
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', margin: '12px 0' }}>
      <tbody>
        {picker.lines.map((l) => (
          <tr key={l.product}>
            <td style={{ ...cell, width: '100%' }}>{l.name}</td>
            {showAvailable && <td style={{ ...cell, whiteSpace: 'nowrap', color: l.available ? 'var(--fg-subtle)' : 'var(--red-700)' }}>{l.available === undefined ? '…' : t('{qty} in stock', { qty: qtyText(l.available) })}</td>}
            <td style={cell}><Input value={l.qty} onChange={(e) => picker.setQty(l.product, e.target.value)} placeholder={t('Qty')} style={{ width: 90 }} /></td>
            <td style={{ ...cell, whiteSpace: 'nowrap', color: 'var(--fg-subtle)' }}>{l.unit}</td>
            <td style={cell}><Button size="small" onClick={() => picker.remove(l.product)}>{t('Remove')}</Button></td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function AskForStock({ store, isHub, isMain, mainName, onPosted }) {
  useT()
  const picker = useLines()
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const ready = picker.lines.length > 0 && picker.lines.every((l) => Number(l.qty) > 0)

  async function post() {
    setBusy(true); setError('')
    try {
      await createEnquiry({ requesting_store: store, note, lines: picker.lines.map((l) => ({ product: l.product, qty_requested: l.qty })) })
      picker.clear(); setNote('')
      onPosted()
    } catch (err) {
      setError(apiErrorText(err, t('Could not post the request.')))
    } finally { setBusy(false) }
  }
  return (
    <Card style={{ maxWidth: 640 }}>
      <NoticeBox variant="info" style={{ marginBottom: 16 }}>
        {isHub && !isMain ? t('Your request goes to {store}, the main store.', { store: mainName }) : t('Your request goes to every other store; any of them can send it.')}
      </NoticeBox>
      {error && <NoticeBox variant="error" style={{ marginBottom: 12 }}>{error}</NoticeBox>}
      <ProductPicker picker={picker} onPick={(p) => picker.add(p)} />
      <LinesTable picker={picker} />
      <Field label={t('Note')}><Input value={note} onChange={(e) => setNote(e.target.value)} placeholder={t('e.g. Needed before the weekend')} /></Field>
      <Button variant="primary" onClick={post} disabled={busy || !ready} style={{ marginTop: 16 }}>{t('Post request')}</Button>
    </Card>
  )
}

function SendStock({ store, stores, onSent }) {
  useT()
  const picker = useLines()
  const [to, setTo] = useState('')
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const ready = to && picker.lines.length > 0 && picker.lines.every((l) => Number(l.qty) > 0 && Number(l.qty) <= (l.available ?? Infinity))

  // Unexpired stock at this store, shown next to each quantity.
  const [availability, setAvailability] = useState({})
  async function pick(p) {
    picker.add(p)
    const available = await availableAt(store, [p.id])
    setAvailability((a) => ({ ...a, [p.id]: available[p.id] ?? 0 }))
  }
  const linesWithStock = { ...picker, lines: picker.lines.map((l) => ({ ...l, available: availability[l.product] })) }

  async function send() {
    setBusy(true); setError('')
    try {
      await sendTransfer({ fromStore: store, toStore: to, note, lines: picker.lines.map((l) => ({ product: l.product, qty: l.qty })) })
      picker.clear(); setNote(''); setTo('')
      onSent()
    } catch (err) {
      setError(apiErrorText(err, t('Could not send the stock.')))
    } finally { setBusy(false) }
  }
  return (
    <Card style={{ maxWidth: 720 }}>
      <p style={{ fontSize: 13, color: 'var(--fg-subtle)', margin: '0 0 12px' }}>
        {t('Send stock without waiting for a request, e.g. the main store restocking a branch. It leaves your stock now and arrives when the other store confirms what it received. Batches are picked earliest expiry first.')}
      </p>
      {error && <NoticeBox variant="error" style={{ marginBottom: 12 }}>{error}</NoticeBox>}
      <Field label={t('Send to')} required>
        <Select value={to} onChange={(e) => setTo(e.target.value)} options={[{ value: '', label: t('Choose a store…') }, ...stores.map((s) => ({ value: s.id, label: s.name }))]} style={{ maxWidth: 320 }} />
      </Field>
      <div style={{ height: 12 }} />
      <ProductPicker picker={picker} onPick={pick} />
      <LinesTable picker={linesWithStock} showAvailable />
      <Field label={t('Note for the receiving store')}><Input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      <Button variant="primary" onClick={send} disabled={busy || !ready} style={{ marginTop: 16 }}>{busy ? t('Sending…') : t('Send now')}</Button>
    </Card>
  )
}

function Transfers({ store, transfers, onChanged, onPrint }) {
  useT()
  const [filter, setFilter] = useState('open')
  const [open, setOpen] = useState(null) // {id, kind: 'receive'|'resolve'|'cancel'|'pay', ...}
  const [error, setError] = useState('')
  const { data: methods } = useApi(() => listPaymentMethods(), [])
  const activeMethods = (methods?.results ?? []).filter((m) => m.is_active)

  const shown = transfers.filter((tx) => (filter === 'open' ? ['dispatched', 'discrepancy'].includes(tx.status) || Number(tx.balance) > 0 : true))
  async function run(fn) {
    setError('')
    try { await fn(); setOpen(null); onChanged() } catch (err) { setError(apiErrorText(err, t('Could not save.'))) }
  }

  return (
    <>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <Chip selected={filter === 'open'} onClick={() => setFilter('open')}>{t('Needs attention')}</Chip>
        <Chip selected={filter === 'all'} onClick={() => setFilter('all')}>{t('All transfers')}</Chip>
      </div>
      {error && <NoticeBox variant="error" style={{ marginBottom: 12 }}>{error}</NoticeBox>}
      <div className="ds-table-card">
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 760 }}>
          <thead>
            <tr>{['No.', 'Sent', 'From → to', 'Items', 'Status', 'Owed', ''].map((h) => <th key={h} style={th(h === 'Owed' ? 'right' : undefined)}>{h && t(h)}</th>)}</tr>
          </thead>
          <tbody>
            {shown.map((tx) => {
              const incoming = tx.to_store === store
              const outgoing = tx.from_store === store
              return (
                <Fragment key={tx.id}>
                  <tr>
                    <td style={td()}>#{tx.number}</td>
                    <td style={td()}>{new Date(tx.dispatched_at).toLocaleDateString(dateLocale())}<div style={sub}>{tx.dispatched_by_name}</div></td>
                    <td style={td()}>{tx.from_store_name} → {tx.to_store_name}</td>
                    <td style={td()}>
                      {tx.lines.map((l) => (
                        <div key={l.id}>
                          {l.product_name} ×{qtyText(l.qty)} {l.unit}
                          {l.received_qty !== null && Number(l.received_qty) !== Number(l.qty) && <span style={{ color: 'var(--red-700)' }}> ({t('got {qty}', { qty: qtyText(l.received_qty) })})</span>}
                          {(l.batch_no || l.expiry_date) && <span style={sub}> · {[l.batch_no && `${t('batch')} ${l.batch_no}`, l.expiry_date && `${t('exp')} ${l.expiry_date}`].filter(Boolean).join(', ')}</span>}
                        </div>
                      ))}
                      {tx.note && <div style={sub}>“{tx.note}”</div>}
                    </td>
                    <td style={td()}>
                      <Tag variant={STATUS_TAG[tx.status]}>{t(tx.status_label)}</Tag>
                      {tx.discrepancy_note && <div style={{ ...sub, whiteSpace: 'pre-line', maxWidth: 240 }}>{tx.discrepancy_note}</div>}
                      {tx.received_by_name && <div style={sub}>{t('Received by {name}', { name: tx.received_by_name })}</div>}
                    </td>
                    <td style={td('right')}>
                      {tx.mode === 'hub' && tx.amount !== null && (tx.paid_at
                        ? <span style={sub}>{t('Paid')} {fmt(Number(tx.amount))}<br />{t(tx.payment_method_name)}</span>
                        : Number(tx.balance) > 0 ? fmt(Number(tx.balance))
                          : tx.status === 'cancelled' ? '' : <span style={sub}>{fmt(Number(tx.amount))}<br />{t('on receipt')}</span>)}
                    </td>
                    <td style={{ ...td('right'), whiteSpace: 'nowrap' }}>
                      <div style={{ display: 'flex', gap: 4, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
                        {incoming && tx.status === 'dispatched' && (
                          <Button size="small" variant="primary" onClick={() => setOpen({ id: tx.id, kind: 'receive', note: '', qty: Object.fromEntries(tx.lines.map((l) => [l.id, String(Number(l.qty))])) })}>{t('Confirm receipt')}</Button>
                        )}
                        {tx.status === 'discrepancy' && <Button size="small" onClick={() => setOpen({ id: tx.id, kind: 'resolve', resolution: RESOLUTIONS[0].value, note: '' })}>{t('Resolve')}</Button>}
                        {outgoing && tx.status === 'dispatched' && <Button size="small" onClick={() => setOpen({ id: tx.id, kind: 'cancel', reason: '' })}>{t('Cancel')}</Button>}
                        {outgoing && Number(tx.balance) > 0 && <Button size="small" onClick={() => setOpen({ id: tx.id, kind: 'pay', method: activeMethods[0]?.id ?? '', reference: '' })}>{t('Record payment')}</Button>}
                        <Button size="small" onClick={() => onPrint(tx)}><Icon name="download" size={16} /> {t('Delivery note')}</Button>
                      </div>
                    </td>
                  </tr>
                  {open?.id === tx.id && (
                    <tr>
                      <td colSpan={7} style={{ padding: 16, borderBottom: '1px solid var(--grey-300)', background: 'var(--grey-050)' }}>
                        {open.kind === 'receive' && (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 560 }}>
                            <div style={{ fontSize: 13, color: 'var(--grey-700)' }}>{t('Count what arrived. If anything is missing or broken, enter what you actually got and say why.')}</div>
                            {tx.lines.map((l) => (
                              <div key={l.id} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                                <span style={{ flex: '1 1 auto', fontSize: 13 }}>{l.product_name}, {t('batch')} {l.batch_no} ({t('sent {qty} {unit}', { qty: qtyText(l.qty), unit: l.unit })})</span>
                                <Input value={open.qty[l.id]} style={{ width: 100 }} onChange={(e) => setOpen((o) => ({ ...o, qty: { ...o.qty, [l.id]: e.target.value } }))} />
                              </div>
                            ))}
                            {tx.lines.some((l) => Number(open.qty[l.id]) < Number(l.qty)) && (
                              <Field label={t('What is missing?')} required><Input value={open.note} onChange={(e) => setOpen((o) => ({ ...o, note: e.target.value }))} placeholder={t('e.g. 2 strips missing from the box')} /></Field>
                            )}
                            <div style={{ display: 'flex', gap: 8 }}>
                              <Button variant="primary" onClick={() => run(() => confirmReceipt(tx.id, { receivedQtyByLine: open.qty, note: open.note }))}>{t('Confirm')}</Button>
                              <Button onClick={() => setOpen(null)}>{t('Cancel')}</Button>
                            </div>
                          </div>
                        )}
                        {open.kind === 'resolve' && (
                          <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
                            <Field label={t('What happened to the missing stock?')} required>
                              <Select value={open.resolution} onChange={(e) => setOpen((o) => ({ ...o, resolution: e.target.value }))} options={tOptions(RESOLUTIONS)} style={{ width: 420 }} />
                            </Field>
                            <Field label={t('Note')}><Input value={open.note} onChange={(e) => setOpen((o) => ({ ...o, note: e.target.value }))} style={{ width: 240 }} /></Field>
                            <Button variant="primary" onClick={() => run(() => resolveTransfer(tx.id, { resolution: open.resolution, note: open.note }))}>{t('Resolve')}</Button>
                            <Button onClick={() => setOpen(null)}>{t('Cancel')}</Button>
                          </div>
                        )}
                        {open.kind === 'cancel' && (
                          <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
                            <Field label={t('Why cancel? The stock goes back into your shelves.')} required><Input value={open.reason} onChange={(e) => setOpen((o) => ({ ...o, reason: e.target.value }))} style={{ width: 360 }} /></Field>
                            <Button variant="destructive" onClick={() => run(() => cancelTransfer(tx.id, open.reason))} disabled={!open.reason.trim()}>{t('Cancel transfer')}</Button>
                            <Button onClick={() => setOpen(null)}>{t('Keep it')}</Button>
                          </div>
                        )}
                        {open.kind === 'pay' && (
                          <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
                            <div style={{ fontSize: 13, color: 'var(--grey-700)', alignSelf: 'center' }}>{t('{store} paid {amount}', { store: tx.to_store_name, amount: fmt(Number(tx.balance)) })}</div>
                            <Field label={t('Paid by')}><Select value={open.method} onChange={(e) => setOpen((o) => ({ ...o, method: e.target.value }))} options={activeMethods.map((m) => ({ value: m.id, label: t(m.name) }))} style={{ width: 200 }} /></Field>
                            <Field label={t('Reference')}><Input value={open.reference} onChange={(e) => setOpen((o) => ({ ...o, reference: e.target.value }))} style={{ width: 200 }} /></Field>
                            <Button variant="primary" onClick={() => run(() => payTransfer(tx.id, { paymentMethod: open.method, reference: open.reference }))}>{t('Save payment')}</Button>
                            <Button onClick={() => setOpen(null)}>{t('Cancel')}</Button>
                          </div>
                        )}
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
            {shown.length === 0 && (
              <tr><td colSpan={7} style={{ padding: '32px 16px', textAlign: 'center', fontSize: 14, color: 'var(--fg-subtle)' }}>{filter === 'open' ? t('Nothing waiting. Switch to All transfers for the history.') : t('No transfers yet.')}</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  )
}

/** Printed and sent with the goods; the receiver signs it. */
function DeliveryNote({ transfer: tx, entity }) {
  useT()
  const cellStyle = { border: '1px solid #999', padding: '4px 6px', fontSize: 12, textAlign: 'left' }
  return (
    <div>
      <h2 style={{ margin: '0 0 4px' }}>{entity?.name} — {t('Stock transfer')} #{tx.number}</h2>
      <div style={{ marginBottom: 12 }}>
        {t('From')} <b>{tx.from_store_name}</b> {t('to')} <b>{tx.to_store_name}</b> · {t('sent {date} by {name}', { date: new Date(tx.dispatched_at).toLocaleString(dateLocale()), name: tx.dispatched_by_name })}
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: 16 }}>
        <thead><tr>{['Product', 'Batch', 'Expiry', 'Quantity', 'Unit', 'Received'].map((h) => <th key={h} style={cellStyle}>{t(h)}</th>)}</tr></thead>
        <tbody>
          {tx.lines.map((l) => (
            <tr key={l.id}>
              <td style={cellStyle}>{l.product_name}</td><td style={cellStyle}>{l.batch_no || '—'}</td><td style={cellStyle}>{l.expiry_date || '—'}</td>
              <td style={cellStyle}>{qtyText(l.qty)}</td><td style={cellStyle}>{l.unit}</td><td style={cellStyle}>{l.received_qty !== null ? qtyText(l.received_qty) : ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {tx.note && <p>{t('Note')}: {tx.note}</p>}
      {tx.mode === 'hub' && tx.amount !== null && <p>{t('Value at cost')}: {fmt(Number(tx.amount))}</p>}
      <div style={{ display: 'flex', gap: 48, marginTop: 32 }}>
        <div>{t('Sent by')}: ____________________</div>
        <div>{t('Received by')}: ____________________ {t('Date')}: __________</div>
      </div>
    </div>
  )
}

const cell = { padding: '6px 8px', borderBottom: '1px solid var(--grey-300)', fontSize: 13 }
const sub = { fontSize: 12, color: 'var(--fg-subtle)' }
function th(align) {
  return { textAlign: align || 'left', fontWeight: 600, fontSize: 11, lineHeight: '16px', textTransform: 'uppercase', letterSpacing: 1.2, color: 'var(--fg-subtle)', padding: '12px 12px', borderBottom: '1px solid var(--grey-300)' }
}
function td(align) {
  return { padding: '10px 12px', borderBottom: '1px solid var(--grey-300)', textAlign: align || 'left', fontSize: 13, verticalAlign: 'top' }
}
