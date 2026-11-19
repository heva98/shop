import { useEffect, useState } from 'react'
import { Button, DataTable, Field, Input, NoticeBox, Tag } from '../../components/ds/index.js'
import { useApi } from '../../hooks/useApi.js'
import { isTransient } from '../../api/client.js'
import { listAllSales, voidSale } from '../../api/pos.js'
import { discard, retryRejected, subscribe } from '../../offline/outbox.js'
import { fmt } from '../../appData.js'
import { apiErrorText } from '../../lib/apiError.js'
import { dateLocale, t, useT } from '../../i18n/index.js'
import { EfdReceiptEntry } from './CompletedSale.jsx'
import { offlineNo } from './format.js'
import { useAsyncAction } from '../../hooks/useAsyncAction.js'

/** Sales on this till the cloud refused when they were sent (e.g. its
 * stock figures show too little left), and sales another cashier left
 * waiting. A refused sale stays here until someone fixes the cause and
 * retries it, or discards it. */
export function UnsentSales({ records, userId }) {
  useT()
  const [busyId, setBusyId] = useState(null)
  const rejected = records.filter((r) => r.status === 'rejected')
  const othersWaiting = records.filter((r) => r.status === 'pending' && r.userId !== userId).length
  if (!rejected.length && !othersWaiting) return null

  async function retry(record) {
    setBusyId(record.id)
    try { await retryRejected(record, userId) } finally { setBusyId(null) }
  }
  function remove(record) {
    if (!window.confirm(t('Discard this {amount} sale? It will not count in takings or come off stock. Only do this if the sale was reversed: money returned and goods back on the shelf.', { amount: fmt(Number(record.receipt.total)) }))) return
    discard(record)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 16 }}>
      {rejected.length > 0 && (
        <NoticeBox variant="error" title={t(rejected.length === 1 ? '{n} sale made on this till could not be recorded' : '{n} sales made on this till could not be recorded', { n: rejected.length })}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 4 }}>
            {rejected.map((r) => (
              <div key={r.id} style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
                <span style={{ flex: '1 1 240px' }}>
                  {new Date(r.createdAt).toLocaleTimeString(dateLocale(), { hour: '2-digit', minute: '2-digit' })} · {fmt(Number(r.receipt.total))}: {r.error}
                </span>
                {r.userId === userId
                  ? <Button size="small" onClick={() => retry(r)} disabled={busyId === r.id}>{t('Try again')}</Button>
                  : <span style={{ fontSize: 12 }}>{t('Rung up by another cashier: they can retry it here.')}</span>}
                <Button size="small" variant="destructive" onClick={() => remove(r)} disabled={busyId === r.id}>{t('Discard')}</Button>
              </div>
            ))}
            <div style={{ fontSize: 12 }}>{t('Fix the cause first, for example by receiving the stock that was sold, then try again.')}</div>
          </div>
        </NoticeBox>
      )}
      {othersWaiting > 0 && (
        <NoticeBox variant="info">
          {t(othersWaiting === 1 ? '{n} sale by another cashier is saved on this till. It is sent when that cashier next signs in here.' : '{n} sales by another cashier are saved on this till. They are sent when that cashier next signs in here.', { n: othersWaiting })}
        </NoticeBox>
      )}
    </div>
  )
}

export function ShiftSales({ shift, unsent, isManager, onPrint, onChanged }) {
  useT()
  const { data, loading, error, refetch: refetchSales } = useApi(() => listAllSales({ shift: shift.id }), [shift.id])
  const sales = (data ?? []).filter((s) => s.status !== 'open')
  const refetch = () => { refetchSales(); onChanged() }
  const [voiding, setVoiding] = useState(null)
  const [efdFor, setEfdFor] = useState(null)

  // A waiting sale that just got recorded moves from the till's list to the server's.
  useEffect(() => subscribe((e) => { if (e.synced) refetchSales() }), [refetchSales])

  // Sales still waiting on this till first (newest first), then the recorded ones.
  const rows = [
    ...[...unsent].reverse().map((r) => ({ kind: 'unsent', key: `u-${r.id}`, id: r.id, sale: r.receipt, record: r })),
    ...sales.map((s) => ({ kind: 'sale', key: `s-${s.id}`, id: s.id, sale: s })),
  ]
  const time = (iso) => new Date(iso).toLocaleTimeString(dateLocale(), { hour: '2-digit', minute: '2-digit' })

  const columns = [
    { key: 'number', header: t('No.'), primary: true, cell: (r) => (r.kind === 'unsent' ? offlineNo(r.sale) : `#${r.sale.number}`) },
    { key: 'time', header: t('Time'), cell: (r) => time(r.kind === 'unsent' ? r.record.createdAt : r.sale.completed_at) },
    { key: 'paid_by', header: t('Paid by'), cell: (r) => <PaidBy sale={r.sale} /> },
    { key: 'total', header: t('Total'), align: 'end', cell: (r) => <span style={{ color: 'var(--ink)' }}>{fmt(Number(r.sale.total))}</span> },
    {
      key: 'efd', header: t('EFD receipt'),
      cell: (r) => {
        if (r.sale.efd_receipt_no) return r.sale.efd_receipt_no
        if (r.kind === 'sale' && r.sale.status !== 'completed') return '—'
        if (efdFor === r.id) {
          return <EfdReceiptEntry sale={r.sale} onUpdated={() => { setEfdFor(null); if (r.kind === 'sale') refetch() }} />
        }
        return <Button size="small" onClick={() => setEfdFor(r.id)}>{t('Enter')}</Button>
      },
    },
    {
      key: 'status', header: t('Status'),
      cell: (r) => {
        if (r.kind === 'unsent') {
          return r.record.status === 'rejected' ? <Tag variant="negative">{t('Not recorded')}</Tag> : <Tag variant="neutral">{t('Waiting to send')}</Tag>
        }
        return r.sale.status === 'voided'
          ? <div><Tag variant="negative">{t('Voided')}</Tag><div className="ds-dt-sub" style={{ marginTop: 2 }}>{r.sale.void_reason}</div></div>
          : <Tag variant="positive">{t('Completed')}</Tag>
      },
    },
    {
      key: 'actions', header: t('Actions'), label: '', align: 'end',
      cell: (r) => (
        <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
          <Button size="small" onClick={() => onPrint(r.sale)}>{t('Print')}</Button>
          {r.kind === 'sale' && r.sale.status === 'completed' && (
            <Button size="small" variant="destructive" aria-expanded={voiding?.id === r.id} onClick={() => setVoiding(voiding?.id === r.id ? null : r.sale)}>{t('Void')}</Button>
          )}
        </div>
      ),
    },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {error && (
        <NoticeBox variant="warning">
          {isTransient(error) ? t('Offline: only the sales still saved on this till are shown.') : apiErrorText(error, t('Could not load the shift’s sales.'))}
        </NoticeBox>
      )}
      <DataTable
        caption={t('Sales in this shift')}
        columns={columns}
        rows={rows}
        rowKey="key"
        // Offline the server's list can't load, but the till's own sales still show.
        loading={loading && !data}
        minWidth={720}
        empty={t('No sales in this shift yet.')}
        renderDetail={(r) => (r.kind === 'sale' && voiding?.id === r.id
          ? <VoidDialog sale={voiding} isManager={isManager} onClose={() => setVoiding(null)} onVoided={() => { setVoiding(null); refetch() }} />
          : null)}
      />
    </div>
  )
}

function PaidBy({ sale }) {
  useT()
  const credit = Number(sale.credit_amount)
  return (
    <>
      {credit > 0 ? (Number(sale.paid_amount) > 0 ? `${t(sale.payment_method_name)} + ${t('credit')}` : t('On credit')) : t(sale.payment_method_name)}
      {credit > 0 && <div style={{ fontSize: 12 }}>{sale.customer_name}</div>}
      {sale.payment_reference && <div style={{ fontSize: 12 }}>{sale.payment_reference}</div>}
    </>
  )
}

function VoidDialog({ sale, isManager, onClose, onVoided }) {
  useT()
  const [reason, setReason] = useState('')
  const [approverUsername, setApproverUsername] = useState('')
  const [approverPassword, setApproverPassword] = useState('')
  const { busy, error, run } = useAsyncAction()

  function submit() {
    return run(async () => {
      await voidSale(sale.id, { reason, approverUsername, approverPassword })
      onVoided()
    }, t('Could not void the sale.'))
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 480 }}>
      <div style={{ fontSize: 15, fontWeight: 500 }}>{t('Void sale #{n} ({amount})', { n: sale.number, amount: fmt(Number(sale.total)) })}</div>
      <div style={{ fontSize: 13, color: 'var(--fg-muted)' }}>
        {t('The items go back into stock and the sale is excluded from takings.')}{' '}
        {sale.efd_receipt_no
          ? t('Return the customer’s money and cancel EFD receipt {no} on the EFD machine.', { no: sale.efd_receipt_no })
          : t('Return the customer’s money.')}
        {Number(sale.credit_amount) > 0 && <> {t('The {amount} on {name}’s account is cleared.', { amount: fmt(Number(sale.credit_amount)), name: sale.customer_name })}</>}
      </div>
      <Field label={t('Reason')} required><Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder={t('e.g. Wrong item sold')} /></Field>
      {!isManager && (
        <>
          <div style={{ fontSize: 13, color: 'var(--grey-700)' }}>{t('A store manager must approve by entering their own login:')}</div>
          <Field label={t('Manager username')}><Input value={approverUsername} onChange={(e) => setApproverUsername(e.target.value)} /></Field>
          <Field label={t('Manager password')}><Input type="password" value={approverPassword} onChange={(e) => setApproverPassword(e.target.value)} /></Field>
        </>
      )}
      {error && <NoticeBox variant="error">{error}</NoticeBox>}
      <div style={{ display: 'flex', gap: 8 }}>
        <Button variant="destructive" onClick={submit} disabled={busy || !reason.trim()}>{t('Void sale')}</Button>
        <Button onClick={onClose} disabled={busy}>{t('Cancel')}</Button>
      </div>
    </div>
  )
}
