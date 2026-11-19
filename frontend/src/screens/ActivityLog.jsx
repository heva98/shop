import { useEffect, useRef, useState } from 'react'
import { Button, DataTable, EmptyState, Field, Input, Select } from '../components/ds/index.js'
import { client } from '../api/client.js'
import { dateLocale, useT } from '../i18n/index.js'

const ACTIONS = [
  ['', 'All activity'],
  ['login', 'Signed in'], ['login_failed', 'Failed sign-in'], ['login_locked', 'Sign-in locked out'],
  ['sale_voided', 'Sale voided'], ['shift_closed', 'Shift closed'],
  ['offline_sale_price', 'Offline sale at an old price'], ['offline_sale_no_stock', 'Offline sale without recorded stock'],
  ['offline_sale_limit', 'Offline sale over a limit'],
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
const ACTION_LABEL = Object.fromEntries(ACTIONS)
const ALERT_ACTIONS = new Set(['login_failed', 'login_locked', 'sale_voided', 'offline_sale_no_stock', 'offline_sale_limit', 'stock_written_off', 'user_disabled', 'password_reset', 'transfer_resolved', 'transfer_cancelled'])

/** Who did what, and when. Nothing here can be edited or deleted. */
export default function ActivityLog() {
  const t = useT()
  const [filters, setFilters] = useState({ action: '', search: '', start: '', end: '' })
  const [events, setEvents] = useState([])
  const [next, setNext] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  const latest = useRef(0) // a slower, older response must not overwrite a newer one
  async function load(url) {
    const request = ++latest.current
    setLoading(true); setError(null)
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
      if (request === latest.current) setError(err)
    } finally { if (request === latest.current) setLoading(false) }
  }
  // Reload whenever a filter changes; the text search waits for a pause in typing.
  useEffect(() => {
    const timer = setTimeout(() => load(null), 300)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters])

  const set = (field) => (e) => setFilters((f) => ({ ...f, [field]: e.target.value }))
  const columns = [
    { key: 'created_at', header: t('When'), cell: (e) => <span style={{ whiteSpace: 'nowrap' }}>{new Date(e.created_at).toLocaleString(dateLocale())}</span> },
    { key: 'username', header: t('Who'), primary: true },
    {
      key: 'action', header: t('What'),
      cell: (e) => (
        <span style={{ whiteSpace: 'nowrap', color: ALERT_ACTIONS.has(e.action) ? 'var(--danger)' : undefined }}>
          {ACTION_LABEL[e.action] ? t(ACTION_LABEL[e.action]) : e.action_label}
        </span>
      ),
    },
    { key: 'summary', header: t('Details') },
    { key: 'store_name', header: t('Store') },
  ]
  return (
    <div>
      <p style={{ fontSize: 14, color: 'var(--fg-muted)', margin: '0 0 16px', maxWidth: 640 }}>
        {t('Every sign-in, price change, cancelled sale, stock loss, stock count, staff change and import, with who did it and when. Entries can’t be edited or deleted.')}
      </p>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end', marginBottom: 12 }}>
        <Field label={t('Activity')}><Select value={filters.action} onChange={set('action')} options={ACTIONS.map(([value, label]) => ({ value, label: t(label) }))} style={{ width: 220 }} /></Field>
        <Field label={t('User or text')}><Input value={filters.search} onChange={set('search')} placeholder={t('e.g. juma or Sugar')} style={{ width: 200 }} /></Field>
        <Field label={t('From')}><Input type="date" value={filters.start} onChange={set('start')} style={{ width: 160 }} /></Field>
        <Field label={t('To')}><Input type="date" value={filters.end} onChange={set('end')} style={{ width: 160 }} /></Field>
      </div>
      <DataTable
        caption={t('Activity log')}
        columns={columns}
        rows={events}
        loading={loading}
        error={error}
        errorTitle={t('Could not load the activity log.')}
        onRetry={() => load(error && events.length ? next : null)}
        manualSort
        density="compact"
        minWidth={640}
        empty={<EmptyState icon="search" title={t('Nothing matches.')} />}
        footer={next && (
          <Button loading={loading && events.length > 0} onClick={() => load(next)}>{t('Load more')}</Button>
        )}
      />
    </div>
  )
}
