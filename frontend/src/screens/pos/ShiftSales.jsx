import { useEffect, useState } from 'react'
import { Button, Field, Input, NoticeBox, Tag } from '../../components/ds/index.js'
import { useApi } from '../../hooks/useApi.js'
import { isTransient } from '../../api/client.js'
import { listAllSales, voidSale } from '../../api/pos.js'
import { discard, retryRejected, subscribe } from '../../offline/outbox.js'
import { fmt } from '../../appData.js'
import { apiErrorText } from '../../lib/apiError.js'
import { dateLocale, t, useT } from '../../i18n/index.js'
import { EfdReceiptEntry } from './CompletedSale.jsx'
import { offlineNo, tdStyle, thStyle } from './format.js'
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

  if (loading && !data && !unsent.length) return <NoticeBox variant="info">{t('Loading…')}</NoticeBox>
  return (
    <div className="ds-table-card">
      {error && (
        <NoticeBox variant="warning" style={{ margin: 16 }}>
          {isTransient(error) ? t('Offline: only the sales still saved on this till are shown.') : apiErrorText(error, t('Could not load the shift’s sales.'))}
        </NoticeBox>
      )}
      <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 720 }}>
        <thead>
          <tr>
            <th style={thStyle('left')}>{t('No.')}</th><th style={thStyle('left')}>{t('Time')}</th><th style={thStyle('left')}>{t('Paid by')}</th>
            <th style={thStyle('right')}>{t('Total')}</th><th style={thStyle('left')}>{t('EFD receipt')}</th><th style={thStyle('left')}>{t('Status')}</th><th style={thStyle('right')} />
          </tr>
        </thead>
        <tbody>
          {[...unsent].reverse().map((r) => (
            <tr key={r.id}>
              <td style={tdStyle('left', true)}>{offlineNo(r.receipt)}</td>
              <td style={tdStyle('left', true)}>{new Date(r.createdAt).toLocaleTimeString(dateLocale(), { hour: '2-digit', minute: '2-digit' })}</td>
              <td style={tdStyle('left', true)}><PaidBy sale={r.receipt} /></td>
              <td style={{ ...tdStyle('right', true), color: 'var(--grey-900)' }}>{fmt(Number(r.receipt.total))}</td>
              <td style={tdStyle('left', true)}>
                {r.receipt.efd_receipt_no || (efdFor === r.id
                  ? <EfdReceiptEntry sale={r.receipt} onUpdated={() => setEfdFor(null)} />
                  : <Button size="small" onClick={() => setEfdFor(r.id)}>{t('Enter')}</Button>)}
              </td>
              <td style={tdStyle('left', true)}>
                {r.status === 'rejected' ? <Tag variant="negative">{t('Not recorded')}</Tag> : <Tag variant="neutral">{t('Waiting to send')}</Tag>}
              </td>
              <td style={{ ...tdStyle('right', true), whiteSpace: 'nowrap' }}>
                <Button size="small" onClick={() => onPrint(r.receipt)}>{t('Print')}</Button>
              </td>
            </tr>
          ))}
          {sales.map((s) => (
            <tr key={s.id}>
              <td style={tdStyle('left', true)}>#{s.number}</td>
              <td style={tdStyle('left', true)}>{new Date(s.completed_at).toLocaleTimeString(dateLocale(), { hour: '2-digit', minute: '2-digit' })}</td>
              <td style={tdStyle('left', true)}><PaidBy sale={s} /></td>
              <td style={{ ...tdStyle('right', true), color: 'var(--grey-900)' }}>{fmt(Number(s.total))}</td>
              <td style={tdStyle('left', true)}>
                {s.efd_receipt_no || (s.status === 'completed' && (efdFor === s.id
                  ? <EfdReceiptEntry sale={s} onUpdated={() => { setEfdFor(null); refetch() }} />
                  : <Button size="small" onClick={() => setEfdFor(s.id)}>{t('Enter')}</Button>))}
              </td>
              <td style={tdStyle('left', true)}>
                {s.status === 'voided'
                  ? <><Tag variant="negative">{t('Voided')}</Tag><div style={{ fontSize: 12, marginTop: 2 }}>{s.void_reason}</div></>
                  : <Tag variant="positive">{t('Completed')}</Tag>}
              </td>
              <td style={{ ...tdStyle('right', true), whiteSpace: 'nowrap' }}>
                <Button size="small" onClick={() => onPrint(s)}>{t('Print')}</Button>{' '}
                {s.status === 'completed' && <Button size="small" variant="destructive" onClick={() => setVoiding(s)}>{t('Void')}</Button>}
              </td>
            </tr>
          ))}
          {sales.length === 0 && unsent.length === 0 && <tr><td colSpan={7} style={{ padding: 24, textAlign: 'center', color: 'var(--fg-subtle)', fontSize: 14 }}>{t('No sales in this shift yet.')}</td></tr>}
        </tbody>
      </table>
      {voiding && <VoidDialog sale={voiding} isManager={isManager} onClose={() => setVoiding(null)} onVoided={() => { setVoiding(null); refetch() }} />}
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
    <div style={{ padding: 16, borderTop: '1px solid var(--grey-300)', display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 480 }}>
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
