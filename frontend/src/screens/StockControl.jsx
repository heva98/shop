import { useEffect, useMemo, useState } from 'react'
import { Button, Card, Field, Input, NoticeBox, Select, Tag } from '../components/ds/index.js'
import PrintArea from '../components/PrintArea.jsx'
import { useApi } from '../hooks/useApi.js'
import { searchProducts } from '../api/catalog.js'
import {
  addFoundStock, createAdjustment, getStockCount, listAdjustments, listAllBatches, listStockCounts,
  saveStockCount, startStockCount, stockCountAction, writeOffExpired,
} from '../api/inventory.js'
import { fmt } from '../appData.js'
import { apiErrorText } from '../lib/apiError.js'

const STATUS_TAG = {
  draft: <Tag>Counting</Tag>, submitted: <Tag variant="neutral">Awaiting approval</Tag>,
  approved: <Tag variant="positive">Approved</Tag>, cancelled: <Tag variant="negative">Cancelled</Tag>,
}
const n = (v) => (v === null || v === undefined ? '—' : Number(v).toLocaleString('en-US'))
const signed = (v) => (Number(v) > 0 ? `+${n(v)}` : n(v))

/** Stock take: a blind count (counters don't see the system's figures),
 * then a manager reviews the differences and approves the corrections. */
export function StockTake({ storeId, storeName, isManager }) {
  const { data: counts, refetch: refetchList } = useApi(() => listStockCounts({ store: storeId }), [storeId])
  const [openId, setOpenId] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const active = (counts?.results ?? []).find((c) => c.status === 'draft' || c.status === 'submitted')
  const shownId = openId ?? active?.id ?? null

  async function start() {
    setBusy(true); setError('')
    try {
      const count = await startStockCount({ store: storeId })
      setOpenId(count.id)
      refetchList()
    } catch (err) {
      setError(apiErrorText(err, 'Could not start the count.'))
    } finally { setBusy(false) }
  }

  if (shownId) {
    return <CountSheet id={shownId} storeName={storeName} isManager={isManager} onClose={() => { setOpenId(null); refetchList() }} onChanged={refetchList} />
  }
  return (
    <div style={{ maxWidth: 900 }}>
      <Card style={{ marginBottom: 16 }}>
        <p style={{ fontSize: 14, color: 'var(--grey-700)', margin: '0 0 12px' }}>
          Count every batch on the shelf and enter what you find. The system&apos;s figures stay hidden until the count is submitted,
          then a manager reviews the differences and approves the corrections. Count while the till is closed.
        </p>
        {error && <NoticeBox variant="error" style={{ marginBottom: 12 }}>{error}</NoticeBox>}
        <Button variant="primary" onClick={start} disabled={busy}>Start stock count</Button>
      </Card>
      <SimpleTable
        headers={['Started', 'Status', 'Batches', 'Counted by', 'Approved by', '']}
        rows={(counts?.results ?? []).map((c) => [
          new Date(c.created_at).toLocaleString(), STATUS_TAG[c.status], c.line_count, c.submitted_by_name || c.created_by_name,
          c.approved_by_name || '—', <Button key="open" size="small" onClick={() => setOpenId(c.id)}>Open</Button>,
        ])}
        empty={counts ? 'No stock counts yet.' : 'Loading…'}
      />
    </div>
  )
}

function CountSheet({ id, storeName, isManager, onClose, onChanged }) {
  const { data: count, refetch } = useApi(() => getStockCount(id), [id])
  const [entries, setEntries] = useState({}) // line id -> typed value
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [filter, setFilter] = useState('')
  const [found, setFound] = useState(null)

  useEffect(() => {
    if (!count) return
    setEntries(Object.fromEntries(count.lines.map((l) => [l.id, l.counted_qty === null ? '' : String(Number(l.counted_qty))])))
  }, [count])

  const dirty = count?.lines.some((l) => (entries[l.id] ?? '') !== (l.counted_qty === null ? '' : String(Number(l.counted_qty))))
  const counting = count?.status === 'draft'
  const reviewing = count && count.status !== 'draft'

  async function act(fn, fallback) {
    setBusy(true); setError('')
    try {
      await fn()
      refetch()
      onChanged()
    } catch (err) {
      setError(apiErrorText(err, fallback))
    } finally { setBusy(false) }
  }
  const save = () => saveStockCount(id, count.lines.map((l) => ({
    id: l.id, counted_qty: entries[l.id] === '' || entries[l.id] === undefined ? null : entries[l.id].replace(/[,\s]/g, ''),
  })))

  const totals = useMemo(() => {
    if (!reviewing) return null
    const differing = count.lines.filter((l) => Number(l.difference) !== 0)
    return {
      differing: differing.length,
      value: count.lines.reduce((s, l) => s + Number(l.difference ?? 0) * Number(l.unit_cost ?? 0), 0),
    }
  }, [count, reviewing])

  if (!count) return <NoticeBox variant="info">Loading…</NoticeBox>
  const q = filter.trim().toLowerCase()
  const lines = count.lines.filter((l) => !q || l.product_name.toLowerCase().includes(q) || l.batch_no.toLowerCase().includes(q))
  const remaining = count.lines.filter((l) => (entries[l.id] ?? '') === '').length

  return (
    <div style={{ maxWidth: 1000 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
        <Button onClick={onClose}>← All counts</Button>
        <span style={{ fontSize: 15, fontWeight: 500 }}>Stock count · {new Date(count.created_at).toLocaleDateString()}</span>
        {STATUS_TAG[count.status]}
        <span style={{ flex: 1 }} />
        <Button onClick={() => window.print()}>Print count sheet</Button>
      </div>
      {error && <NoticeBox variant="error" style={{ marginBottom: 12 }}>{error}</NoticeBox>}

      {counting && (
        <Card style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <span style={{ fontSize: 13, color: 'var(--grey-700)' }}>{remaining === 0 ? 'Every batch is counted.' : `${remaining} of ${count.lines.length} batches still to count.`}</span>
            <span style={{ flex: 1 }} />
            <Button onClick={() => setFound({ product: null, query: '', suggestions: [], batch_no: '', expiry_date: '', counted_qty: '' })}>+ Stock not on the list</Button>
            <Button onClick={() => act(save, 'Could not save.')} disabled={busy || !dirty}>Save progress</Button>
            <Button variant="primary" disabled={busy || remaining > 0} onClick={() => act(async () => { if (dirty) await save(); await stockCountAction(id, 'submit') }, 'Could not submit.')}>Submit for approval</Button>
            <Button variant="destructive" disabled={busy} onClick={() => act(() => stockCountAction(id, 'cancel'), 'Could not cancel.')}>Cancel count</Button>
          </div>
          {found && <FoundStockForm found={found} setFound={setFound} onAdd={(data) => act(async () => { if (dirty) await save(); await addFoundStock(id, data); setFound(null) }, 'Could not add the batch.')} />}
        </Card>
      )}

      {reviewing && (
        <Card style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', alignItems: 'center' }}>
            <div><div style={label}>Batches that differ</div><div style={big}>{totals.differing}</div></div>
            <div><div style={label}>Value of differences (at cost)</div><div style={{ ...big, color: totals.value < 0 ? 'var(--status-error)' : undefined }}>{fmt(totals.value)}</div></div>
            <span style={{ flex: 1 }} />
            {count.status === 'submitted' && isManager && (
              <>
                <Button variant="primary" disabled={busy} onClick={() => act(() => stockCountAction(id, 'approve'), 'Could not approve.')}>Approve and correct stock</Button>
                <Button disabled={busy} onClick={() => act(() => stockCountAction(id, 'reopen'), 'Could not reopen.')}>Send back for recount</Button>
              </>
            )}
            {count.status === 'submitted' && !isManager && <span style={{ fontSize: 13, color: 'var(--grey-700)' }}>Waiting for a store manager to approve.</span>}
          </div>
        </Card>
      )}

      <div style={{ marginBottom: 8, maxWidth: 360 }}><Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter by product or batch" prefixIcon="search" /></div>
      <SimpleTable
        headers={reviewing
          ? ['Product', 'Batch', 'Expiry', 'Expected', 'Counted', 'Difference', 'Value']
          : ['Product', 'Batch', 'Expiry', 'Counted']}
        rows={lines.map((l) => {
          const head = [<span key="p">{l.product_name} <span style={{ color: 'var(--fg-subtle)', fontSize: 12 }}>({l.unit_name}){!l.batch && ' · new'}</span></span>, l.batch_no, l.expiry_date]
          if (!reviewing) {
            return [...head, counting
              ? <Input key="c" value={entries[l.id] ?? ''} onChange={(e) => setEntries({ ...entries, [l.id]: e.target.value })} style={{ width: 100 }} />
              : n(l.counted_qty)]
          }
          const diff = Number(l.difference)
          return [...head, n(l.expected_qty), n(l.counted_qty),
            <span key="d" style={{ color: diff < 0 ? 'var(--status-error)' : diff > 0 ? 'var(--green-700)' : undefined, fontWeight: diff ? 500 : 400 }}>{signed(l.difference)}</span>,
            diff ? fmt(diff * Number(l.unit_cost ?? 0)) : '—']
        })}
        empty="Nothing to count — this store has no stock yet."
      />

      <PrintArea kind="report">
        <h2 style={{ margin: '0 0 4px' }}>Stock count sheet — {storeName}</h2>
        <div style={{ marginBottom: 12 }}>Started {new Date(count.created_at).toLocaleString()} · Counted by: ____________________</div>
        <table>
          <thead><tr><th>Product</th><th>Unit</th><th>Batch</th><th>Expiry</th><th style={{ width: '25%' }}>Counted</th></tr></thead>
          <tbody>
            {count.lines.map((l) => (
              <tr key={l.id}><td>{l.product_name}</td><td>{l.unit_name}</td><td>{l.batch_no}</td><td>{l.expiry_date}</td><td>{counting ? '' : n(l.counted_qty)}</td></tr>
            ))}
          </tbody>
        </table>
      </PrintArea>
    </div>
  )
}

function FoundStockForm({ found, setFound, onAdd }) {
  useEffect(() => {
    const q = found.query.trim()
    if (!q || found.product) return undefined
    const timer = setTimeout(async () => {
      try {
        const res = await searchProducts(q)
        setFound((f) => ({ ...f, suggestions: res.results.slice(0, 6) }))
      } catch { /* ignore */ }
    }, 250)
    return () => clearTimeout(timer)
  }, [found.query, found.product, setFound])

  return (
    <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap', marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--grey-300)' }}>
      <Field label="Product">
        {found.product
          ? <div style={{ display: 'flex', gap: 8, alignItems: 'center', height: 36 }}>{found.product.name}<Button size="small" onClick={() => setFound({ ...found, product: null })}>Change</Button></div>
          : (
            <div style={{ position: 'relative', width: 240 }}>
              <Input value={found.query} onChange={(e) => setFound({ ...found, query: e.target.value })} placeholder="Search product" />
              {found.suggestions.length > 0 && (
                <div style={{ position: 'absolute', top: 40, left: 0, right: 0, zIndex: 10, background: 'var(--white)', boxShadow: 'var(--shadow-popover)', borderRadius: 'var(--radius-md)' }}>
                  {found.suggestions.map((p) => (
                    <div key={p.id} onClick={() => setFound({ ...found, product: p, suggestions: [] })} style={{ padding: '8px 12px', fontSize: 13, cursor: 'pointer', borderBottom: '1px solid var(--grey-300)' }}>{p.name}</div>
                  ))}
                </div>
              )}
            </div>
          )}
      </Field>
      <Field label="Batch no. (if any)"><Input value={found.batch_no} onChange={(e) => setFound({ ...found, batch_no: e.target.value })} style={{ width: 120 }} /></Field>
      <Field label="Expiry" required={!!found.product?.tracks_expiry}><Input type="date" value={found.expiry_date} onChange={(e) => setFound({ ...found, expiry_date: e.target.value })} style={{ width: 160 }} /></Field>
      <Field label="Counted"><Input value={found.counted_qty} onChange={(e) => setFound({ ...found, counted_qty: e.target.value })} style={{ width: 90 }} /></Field>
      <Button
        variant="primary"
        disabled={!found.product || (found.product.tracks_expiry && !found.expiry_date) || found.counted_qty === ''}
        onClick={() => onAdd({ product: found.product.id, batch_no: found.batch_no.trim(), expiry_date: found.expiry_date || null, counted_qty: found.counted_qty })}
      >Add</Button>
      <Button onClick={() => setFound(null)}>Cancel</Button>
    </div>
  )
}

const REASONS = [
  { value: 'expired', label: 'Expired' }, { value: 'damaged', label: 'Damaged / broken' }, { value: 'lost', label: 'Lost' },
  { value: 'stolen', label: 'Stolen' }, { value: 'cold_chain_failure', label: 'Cold chain failure' },
  { value: 'consumption', label: 'Internal use' }, { value: 'dispose', label: 'Disposed (other)' },
  { value: 'wrong_entry', label: 'Correcting a wrong entry' },
]

/** Writing stock off with a reason. Managers only; everyone with access
 * to Stock can see the history. */
export function WriteOffs({ storeId, isManager }) {
  const { data: batches, refetch: refetchBatches } = useApi(() => listAllBatches({ store: storeId }), [storeId])
  const { data: history, refetch: refetchHistory } = useApi(() => listAdjustments({ store: storeId }), [storeId])
  const [filter, setFilter] = useState('')
  const [form, setForm] = useState(null) // {batch, qty, reason, note, add}
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const today = new Date().toISOString().slice(0, 10)
  const withStock = (batches ?? []).filter((b) => Number(b.qty_on_hand) > 0)
  const expired = withStock.filter((b) => b.expiry_date && b.expiry_date < today)
  const q = filter.trim().toLowerCase()
  const visible = withStock.filter((b) => !q || b.product_name.toLowerCase().includes(q) || b.batch_no.toLowerCase().includes(q))

  async function act(fn, fallback) {
    setBusy(true); setError('')
    try {
      await fn()
      setForm(null)
      refetchBatches(); refetchHistory()
    } catch (err) {
      setError(apiErrorText(err, fallback))
    } finally { setBusy(false) }
  }
  function submit() {
    const qty = Number(String(form.qty).replace(/[,\s]/g, ''))
    if (!(qty > 0)) { setError('Enter a quantity above zero.'); return }
    const delta = form.reason === 'wrong_entry' && form.add ? qty : -qty
    act(() => createAdjustment({ batch: form.batch.id, qty_delta: delta, reason: form.reason, note: form.note }), 'Could not record the write-off.')
  }

  return (
    <div style={{ maxWidth: 1000 }}>
      {!isManager && <NoticeBox variant="info" style={{ marginBottom: 12 }}>Only a store manager can write stock off. Report damaged or missing stock to your manager.</NoticeBox>}
      {error && <NoticeBox variant="error" style={{ marginBottom: 12 }}>{error}</NoticeBox>}
      {isManager && expired.length > 0 && (
        <NoticeBox variant="warning" title={`${expired.length} expired batch${expired.length === 1 ? '' : 'es'} still in stock`} style={{ marginBottom: 12 }}>
          Remove them from the shelf for return or disposal, then write them off.
          <div style={{ marginTop: 8 }}>
            <Button size="small" disabled={busy} onClick={() => act(() => writeOffExpired(storeId), 'Could not write off expired stock.')}>Write off all expired stock</Button>
          </div>
        </NoticeBox>
      )}

      {isManager && form && (
        <Card style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 14, fontWeight: 500, marginBottom: 8 }}>
            {form.batch.product_name} · batch {form.batch.batch_no} · {n(form.batch.qty_on_hand)} {form.batch.unit_name} in stock
          </div>
          <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <Field label="Reason"><Select value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} options={REASONS} style={{ width: 200 }} /></Field>
            {form.reason === 'wrong_entry' && (
              <Field label="Direction">
                <Select value={form.add ? 'add' : 'remove'} onChange={(e) => setForm({ ...form, add: e.target.value === 'add' })} options={[{ value: 'remove', label: 'Remove stock' }, { value: 'add', label: 'Add stock back' }]} style={{ width: 160 }} />
              </Field>
            )}
            <Field label={`Quantity (${form.batch.unit_name})`}><Input value={form.qty} onChange={(e) => setForm({ ...form, qty: e.target.value })} style={{ width: 100 }} /></Field>
            <Field label="Note"><Input value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} placeholder="What happened" style={{ width: 240 }} /></Field>
            <Button variant="primary" onClick={submit} disabled={busy}>Record</Button>
            <Button onClick={() => setForm(null)} disabled={busy}>Cancel</Button>
          </div>
        </Card>
      )}

      {isManager && (
        <>
          <div style={{ marginBottom: 8, maxWidth: 360 }}><Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Find a batch to write off" prefixIcon="search" /></div>
          <SimpleTable
            headers={['Product', 'Batch', 'Expiry', 'In stock', '']}
            rows={visible.map((b) => [
              b.product_name, b.batch_no,
              b.expiry_date && b.expiry_date < today ? <span key="e" style={{ color: 'var(--status-error)' }}>{b.expiry_date} (expired)</span> : (b.expiry_date || 'No expiry'),
              `${n(b.qty_on_hand)} ${b.unit_name}`,
              <Button key="w" size="small" onClick={() => setForm({ batch: b, qty: '', reason: b.expiry_date && b.expiry_date < today ? 'expired' : 'damaged', note: '', add: false })}>Write off</Button>,
            ])}
            empty={batches ? 'No stock in this store.' : 'Loading…'}
          />
        </>
      )}

      <h3 style={{ fontSize: 15, fontWeight: 500, margin: '24px 0 8px' }}>History</h3>
      <SimpleTable
        headers={['Date', 'Product', 'Batch', 'Reason', 'Qty', 'Value at cost', 'By', 'Note']}
        rows={(history?.results ?? []).map((a) => [
          new Date(a.created_at).toLocaleString(), a.product_name, a.batch_no, a.reason_label, signed(a.qty_delta),
          fmt(Number(a.value_at_cost)), a.created_by_name, a.note || '—',
        ])}
        empty={history ? 'Nothing written off yet.' : 'Loading…'}
      />
    </div>
  )
}

function SimpleTable({ headers, rows, empty }) {
  return (
    <div className="ds-table-card">
      <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 560 }}>
        <thead><tr>{headers.map((h, i) => <th key={i} style={th}>{h}</th>)}</tr></thead>
        <tbody>
          {rows.map((cells, i) => <tr key={i}>{cells.map((c, j) => <td key={j} style={td}>{c}</td>)}</tr>)}
          {rows.length === 0 && <tr><td colSpan={headers.length} style={{ ...td, textAlign: 'center', color: 'var(--fg-subtle)' }}>{empty}</td></tr>}
        </tbody>
      </table>
    </div>
  )
}

const th = { textAlign: 'left', fontWeight: 600, fontSize: 11, lineHeight: '16px', textTransform: 'uppercase', letterSpacing: 1.2, color: 'var(--fg-subtle)', padding: '12px 16px', borderBottom: '1px solid var(--grey-300)', whiteSpace: 'nowrap' }
const td = { padding: '14px 16px', borderBottom: '1px solid var(--grey-300)', fontSize: 14, color: 'var(--grey-700)', verticalAlign: 'middle' }
const label = { fontSize: 12, color: 'var(--fg-subtle)' }
const big = { fontSize: 24, lineHeight: '32px', fontWeight: 700, color: 'var(--navy-800)' }
