import { useState } from 'react'
import { Button, Icon, Input, NoticeBox } from '../../components/ds/index.js'
import { recordFiscalReceipt } from '../../api/pos.js'
import { setUnsentEfdNumber } from '../../offline/outbox.js'
import { fmt } from '../../appData.js'
import { t, useT } from '../../i18n/index.js'
import { useAsyncAction } from '../../hooks/useAsyncAction.js'

export function CompletedSale({ sale, onUpdated, onPrint, onNewSale }) {
  useT()
  return (
    <>
      <NoticeBox variant="valid" title={sale.offline ? t('Sale saved on this till') : t('Sale #{n} complete', { n: sale.number })}>
        {Number(sale.credit_amount) > 0
          ? <>{t('{amount} on {name}’s account', { amount: fmt(Number(sale.credit_amount)), name: sale.customer_name })}{Number(sale.paid_amount) > 0 && <>, {t('{amount} paid by {method}', { amount: fmt(Number(sale.paid_amount)), method: t(sale.payment_method_name) })}</>}.</>
          : <>{t('{amount} paid by {method}', { amount: fmt(Number(sale.total)), method: t(sale.payment_method_name) })}.</>}
        {sale.change_due !== null && Number(sale.change_due) > 0 && <> {t('Give change:')} <b>{fmt(Number(sale.change_due))}</b>.</>}
        {sale.offline && <div style={{ marginTop: 4 }}>{t('No connection right now: it is sent, and gets its receipt number, as soon as the connection returns.')}</div>}
      </NoticeBox>
      <EfdReceiptEntry sale={sale} onUpdated={onUpdated} />
      <Button onClick={onPrint}><Icon name="download" size={16} /> {t('Print receipt')}</Button>
      <Button variant="primary" onClick={onNewSale} style={{ width: '100%', height: 43 }}>{t('New sale')}</Button>
    </>
  )
}

/** The till can't talk to the store's EFD machine (see
 * fiscal.drivers.manual_efd): the cashier rings the sale up on it and
 * types the printed receipt number in here. For a sale not yet sent, the
 * number is kept with it and sent along. */
export function EfdReceiptEntry({ sale, onUpdated }) {
  useT()
  const [number, setNumber] = useState('')
  const { busy, error, run } = useAsyncAction()
  if (sale.efd_receipt_no) {
    return <div style={{ fontSize: 13, color: 'var(--grey-700)' }}>{t('EFD receipt no.')} <b>{sale.efd_receipt_no}</b></div>
  }
  function save() {
    return run(async () => {
      if (sale.offline && await setUnsentEfdNumber(sale.id, number.trim())) {
        onUpdated({ ...sale, efd_receipt_no: number.trim() })
        return
      }
      onUpdated(await recordFiscalReceipt(sale.id, number.trim()))
    }, t('Could not save the EFD receipt number.'))
  }
  return (
    <div style={{ padding: 12, background: 'var(--grey-100)', borderRadius: 'var(--radius-sm)', display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ fontSize: 13, color: 'var(--grey-900)' }}>
        {t('Issue this sale on the EFD machine ({amount}), then enter the receipt number it prints.', { amount: fmt(Number(sale.total)) })}
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <Input value={number} onChange={(e) => setNumber(e.target.value)} placeholder={t('EFD receipt no.')} />
        <Button onClick={save} disabled={busy || !number.trim()}>{t('Save')}</Button>
      </div>
      {error && <div style={{ fontSize: 12, color: 'var(--status-error)' }}>{error}</div>}
    </div>
  )
}
