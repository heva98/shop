import { Fragment } from 'react'
import { Button, Card, Icon, NoticeBox, PageHeader } from '../../components/ds/index.js'
import PrintArea from '../../components/PrintArea.jsx'
import { fmt } from '../../appData.js'
import { dateLocale, t, useT } from '../../i18n/index.js'
import { offlineNo } from './format.js'

export function ZReport({ shift, entity, store, onDone }) {
  useT()
  const z = shift.summary
  const variance = Number(z.variance)
  return (
    <div style={{ maxWidth: 520 }}>
      <PageHeader title={t('Shift closed')} subtitle={t('Summary of the shift you just closed.')} />
      {variance !== 0 && (
        <NoticeBox variant="warning" title={variance < 0 ? t('Drawer is short by {amount}', { amount: fmt(-variance) }) : t('Drawer is over by {amount}', { amount: fmt(variance) })} style={{ marginBottom: 16 }}>
          {t('Expected {expected}, counted {counted}.', { expected: fmt(Number(z.expected_cash)), counted: fmt(Number(z.counted_cash)) })}
        </NoticeBox>
      )}
      <Card><ZReportBody shift={shift} entity={entity} store={store} /></Card>
      <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
        <Button onClick={() => window.print()}><Icon name="download" size={16} /> {t('Print Z-report')}</Button>
        <Button variant="primary" onClick={onDone}>{t('Done')}</Button>
      </div>
      <PrintArea kind="receipt"><ZReportBody shift={shift} entity={entity} store={store} /></PrintArea>
    </div>
  )
}

function ZReportBody({ shift, entity, store }) {
  useT()
  const z = shift.summary
  const row = (label, value, bold) => (
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, padding: '3px 0', fontWeight: bold ? 600 : 400 }}><span>{t(label)}</span><span>{value}</span></div>
  )
  return (
    <div>
      <div style={{ textAlign: 'center', marginBottom: 8 }}>
        <div style={{ fontWeight: 600 }}>{entity?.name}</div>
        <div style={{ fontSize: 12 }}>{store?.name}</div>
        <div style={{ fontWeight: 600, marginTop: 6 }}>{t('END OF SHIFT (Z) REPORT')}</div>
      </div>
      {row('Cashier', shift.cashier_name)}
      {row('Opened', new Date(shift.opened_at).toLocaleString(dateLocale()))}
      {row('Closed', shift.closed_at ? new Date(shift.closed_at).toLocaleString(dateLocale()) : '—')}
      <hr />
      {row('Sales', z.sales_count)}
      {z.by_payment_method.map((m) => <Fragment key={m.payment_method}>{row(`  ${t(m.payment_method)} (${m.count})`, fmt(Number(m.total)))}</Fragment>)}
      {row('Gross sales', fmt(Number(z.gross_total)), true)}
      {row('VAT included', fmt(Number(z.vat_total)))}
      {Number(z.discount_total) > 0 && row('Discounts given', fmt(Number(z.discount_total)))}
      {row(t('Voided sales ({n})', { n: z.void_count }), fmt(Number(z.void_total)))}
      {z.credit_repayments.length > 0 && (
        <>
          <hr />
          {row('Credit repayments', '', true)}
          {z.credit_repayments.map((m) => <Fragment key={m.payment_method}>{row(`  ${t(m.payment_method)} (${m.count})`, fmt(Number(m.total)))}</Fragment>)}
        </>
      )}
      <hr />
      {row('Opening float', fmt(Number(z.opening_float)))}
      {row('Cash sales', fmt(Number(z.cash_sales)))}
      {Number(z.cash_repayments) > 0 && row('Cash repayments', fmt(Number(z.cash_repayments)))}
      {row('Expected cash', fmt(Number(z.expected_cash)), true)}
      {row('Counted cash', z.counted_cash === null ? '—' : fmt(Number(z.counted_cash)))}
      {row('Difference', z.variance === null ? '—' : fmt(Number(z.variance)), true)}
      {shift.closing_note && <div style={{ fontSize: 12, marginTop: 6 }}>{t('Note')}: {shift.closing_note}</div>}
    </div>
  )
}

export function Receipt({ sale, entity, store }) {
  useT()
  const line = (left, right, bold) => (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontWeight: bold ? 600 : 400 }}><span>{t(left)}</span><span style={{ whiteSpace: 'nowrap' }}>{right}</span></div>
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
      {line(sale.number ? t('Receipt #{n}', { n: sale.number }) : t('Receipt {n} (offline)', { n: offlineNo(sale) }), new Date(sale.completed_at).toLocaleString(dateLocale()))}
      {line('Served by', sale.cashier_name)}
      {sale.status === 'voided' && <div style={{ fontWeight: 600, textAlign: 'center' }}>*** {t('VOIDED')} ***</div>}
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
      {(!Number(sale.credit_amount) || Number(sale.paid_amount) > 0) && line('Paid by', t(sale.payment_method_name))}
      {sale.amount_tendered !== null && sale.payment_reference === '' && line('Tendered', fmt(Number(sale.amount_tendered)))}
      {sale.change_due !== null && sale.payment_reference === '' && line('Change due', fmt(Number(sale.change_due)))}
      {sale.payment_reference && line('Reference', sale.payment_reference)}
      {sale.customer_name && line('Customer', sale.customer_phone ? `${sale.customer_name} (${sale.customer_phone})` : sale.customer_name)}
      {sale.patient_name && line('Patient', sale.patient_name)}
      {sale.prescriber_name && line('Prescriber', sale.prescription_ref ? `${sale.prescriber_name} (Rx ${sale.prescription_ref})` : sale.prescriber_name)}
      <hr />
      <div style={{ textAlign: 'center', fontSize: 11 }}>
        {sale.efd_receipt_no ? `${t('EFD receipt no.')} ${sale.efd_receipt_no}` : t('Fiscal (EFD) receipt issued separately.')}
        <div>{t('Thank you for shopping with us. Karibu tena!')}</div>
      </div>
    </div>
  )
}
