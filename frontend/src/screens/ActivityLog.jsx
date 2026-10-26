import { useEffect, useRef, useState } from 'react'
import { Button, Field, Input, NoticeBox, Select } from '../components/ds/index.js'
import { client } from '../api/client.js'
import { apiErrorText } from '../lib/apiError.js'

const ACTIONS = [
  ['', 'All activity'],
  ['login', 'Signed in'], ['login_failed', 'Failed sign-in'], ['login_locked', 'Sign-in locked out'],
  ['sale_voided', 'Sale voided'], ['shift_closed', 'Shift closed'],
  ['price_set', 'Price set'], ['price_removed', 'Price removed'],
  ['product_created', 'Product added'], ['product_updated', 'Product changed'],
  ['stock_written_off', 'Stock written off'], ['stock_count_approved', 'Stock count approved'],
  ['invoice_received', 'Supplier invoice received'], ['supplier_payment', 'Supplier payment recorded'],
  ['user_created', 'User created'], ['user_updated', 'User changed'], ['user_disabled', 'User disabled'],
  ['user_enabled', 'User enabled'], ['password_reset', 'Password reset by admin'], ['password_changed', 'Password changed'],
  ['role_granted', 'Role granted'], ['role_removed', 'Role removed'],
  ['payment_method_changed', 'Payment method switched on/off'], ['settings_changed', 'Settings changed'],
  ['data_imported', 'Data imported'],
  ['transfer_sent', 'Stock sent to another store'], ['transfer_received', 'Stock received from another store'],
  ['transfer_resolved', 'Short delivery resolved'], ['transfer_cancelled', 'Transfer cancelled'],
  ['transfer_paid', 'Branch payment recorded'],
  ['customer_changed', 'Customer added or changed'], ['credit_payment', 'Customer credit payment received'],
  ['credit_payment_voided', 'Customer credit payment voided'], ['discount_given', 'Discount over the cashier limit'],
  ['promotion_changed', 'Promotion added or changed'],
]
const ALERT_ACTIONS = new Set(['login_failed', 'login_locked', 'sale_voided', 'stock_written_off', 'user_disabled', 'password_reset', 'transfer_resolved', 'transfer_cancelled'])

/** Who did what, and when. Nothing here can be edited or deleted. */
export default function ActivityLog() {
  const [filters, setFilters] = useState({ action: '', search: '', start: '', end: '' })
  const [events, setEvents] = useState([])
  const [next, setNext] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const latest = useRef(0) // a slower, older response must not overwrite a newer one
  async function load(url) {
    const request = ++latest.current
    setLoading(true); setError('')
    try {
      const page = url
        ? await client.get(url.replace(/^https?:\/\/[^/]+/, ''))
        : await client.get('/api/audit/events/', {
          action: filters.action || undefined, search: filters.search.trim() || undefined,
          start: filters.start || undefined, end: filters.end || undefined,
        })
      if (request !== latest.current) return
      setEvents((prev) => (url ? [...prev, ...page.results] : page.results))
      setNext(page.next)
    } catch (err) {
      setError(apiErrorText(err, 'Could not load the activity log.'))
    } finally { setLoading(false) }
  }
  // Reload whenever a filter changes; the text search waits for a pause in typing.
  useEffect(() => {
    const timer = setTimeout(() => load(null), 300)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters])

  const set = (field) => (e) => setFilters((f) => ({ ...f, [field]: e.target.value }))
  return (
    <div>
      <p style={{ fontSize: 14, color: 'var(--fg-muted)', margin: '0 0 16px', maxWidth: 640 }}>
        Every sign-in, price change, void, write-off, stock count approval, staff change and import, with who did it and when.
        Entries can&apos;t be edited or deleted.
      </p>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end', marginBottom: 12 }}>
        <Field label="Activity"><Select value={filters.action} onChange={set('action')} options={ACTIONS.map(([value, label]) => ({ value, label }))} style={{ width: 220 }} /></Field>
        <Field label="User or text"><Input value={filters.search} onChange={set('search')} placeholder="e.g. juma or Sugar" style={{ width: 200 }} /></Field>
        <Field label="From"><Input type="date" value={filters.start} onChange={set('start')} style={{ width: 160 }} /></Field>
        <Field label="To"><Input type="date" value={filters.end} onChange={set('end')} style={{ width: 160 }} /></Field>
      </div>
      {error && <NoticeBox variant="error" style={{ marginBottom: 12 }}>{error}</NoticeBox>}
      <div className="ds-table-card">
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 640 }}>
          <thead>
            <tr>{['When', 'Who', 'What', 'Details', 'Store'].map((h) => <th key={h} style={th}>{h}</th>)}</tr>
          </thead>
          <tbody>
            {events.map((e) => (
              <tr key={e.id}>
                <td style={{ ...td, whiteSpace: 'nowrap' }}>{new Date(e.created_at).toLocaleString()}</td>
                <td style={td}>{e.username || '—'}</td>
                <td style={{ ...td, whiteSpace: 'nowrap', color: ALERT_ACTIONS.has(e.action) ? 'var(--status-error)' : undefined }}>{e.action_label}</td>
                <td style={td}>{e.summary}</td>
                <td style={td}>{e.store_name || '—'}</td>
              </tr>
            ))}
            {!loading && events.length === 0 && <tr><td colSpan={5} style={{ ...td, textAlign: 'center', color: 'var(--fg-subtle)' }}>Nothing matches.</td></tr>}
          </tbody>
        </table>
      </div>
      {next && <Button onClick={() => load(next)} disabled={loading} style={{ marginTop: 12 }}>{loading ? 'Loading…' : 'Load more'}</Button>}
    </div>
  )
}

const th = { textAlign: 'left', fontWeight: 600, fontSize: 11, lineHeight: '16px', textTransform: 'uppercase', letterSpacing: 1.2, color: 'var(--fg-subtle)', padding: '12px 16px', borderBottom: '1px solid var(--grey-300)' }
const td = { padding: '14px 16px', borderBottom: '1px solid var(--grey-300)', fontSize: 13, color: 'var(--grey-700)', verticalAlign: 'top' }
