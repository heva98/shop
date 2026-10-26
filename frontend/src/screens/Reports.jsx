import { useState } from 'react'
import { Button, Card, Chip, Field, Icon, Input, NoticeBox, PageHeader } from '../components/ds/index.js'
import PrintArea from '../components/PrintArea.jsx'
import { downloadCsv } from '../lib/exportCsv.js'
import {
  getExpiryReport, getLossesReport, getPurchasesReport, getSalesReport, getShiftsReport, getStockReport,
  getTransfersReport,
} from '../api/reports.js'
import { listAllCustomers } from '../api/credit.js'
import { fmt } from '../appData.js'
import { client } from '../api/client.js'

const ALL = ['cashier', 'storekeeper', 'store_manager', 'entity_admin']
const MANAGEMENT = ['storekeeper', 'store_manager', 'entity_admin']
const MANAGERS = ['store_manager', 'entity_admin']
const money = (v) => (v === null || v === undefined ? '—' : fmt(Number(v)))
const dateTime = (v) => (v ? new Date(v).toLocaleString() : '—')
const num = (v) => Number(v).toLocaleString('en-US')

const REPORTS = [
  {
    id: 'sales', title: 'Sales', roles: ALL, usesDates: true, fetch: getSalesReport,
    description: 'Every sale in the period with payment method, discount, credit, EFD receipt and VAT, plus totals by payment method and by product.',
    summary: (d) => [
      ['Sales', d.summary.sales_count], ['Gross sales', money(d.summary.gross_total)], ['VAT included', money(d.summary.vat_total)],
      ['Discounts given', money(d.summary.discount_total)], ['Sold on credit', money(d.summary.credit_total)],
      ['Voided', `${d.summary.void_count} (${money(d.summary.void_total)})`], ['Missing EFD no.', d.summary.missing_efd_count],
      ...d.summary.by_payment_method.map((m) => [m.payment_method, `${money(m.total)} (${m.count})`]),
    ],
    tables: (d) => [
      {
        title: 'Sales', rows: d.sales, columns: [
          { label: 'No.', value: (r) => r.number }, { label: 'Date', value: (r) => dateTime(r.completed_at) },
          { label: 'Store', value: (r) => r.store }, { label: 'Cashier', value: (r) => r.cashier },
          { label: 'Paid by', value: (r) => (Number(r.credit) ? (Number(r.credit) < Number(r.total) ? `${r.payment_method} + credit` : 'On credit') : r.payment_method) },
          { label: 'Customer', value: (r) => r.customer_name },
          { label: 'Reference', value: (r) => r.payment_reference },
          { label: 'EFD no.', value: (r) => r.efd_receipt_no }, { label: 'Status', value: (r) => (r.status === 'voided' ? `Voided: ${r.void_reason}` : 'Completed') },
          { label: 'VAT', value: (r) => r.vat, align: 'right', money: true },
          { label: 'Discount', value: (r) => (Number(r.discount) ? r.discount : null), align: 'right', money: true },
          { label: 'On credit', value: (r) => (Number(r.credit) ? r.credit : null), align: 'right', money: true },
          { label: 'Total', value: (r) => r.total, align: 'right', money: true },
        ],
      },
      {
        title: 'By product', rows: d.by_product, columns: [
          { label: 'Product', value: (r) => r.product }, { label: 'Qty sold', value: (r) => r.qty, align: 'right' },
          { label: 'Stock unit', value: (r) => r.unit },
          { label: 'Value', value: (r) => r.value, align: 'right', money: true },
        ],
      },
    ],
  },
  {
    id: 'shifts', title: 'Shifts & cash reconciliation (Z reports)', roles: ALL, usesDates: true, fetch: getShiftsReport,
    description: 'Each shift: takings by payment method, expected vs counted cash, and the difference.',
    summary: (d) => [
      ['Shifts', d.shifts.length],
      ['Total difference', money(d.shifts.reduce((s, r) => s + Number(r.variance ?? 0), 0))],
    ],
    tables: (d) => [{
      title: 'Shifts', rows: d.shifts, columns: [
        { label: 'Store', value: (r) => r.store }, { label: 'Cashier', value: (r) => r.cashier },
        { label: 'Opened', value: (r) => dateTime(r.opened_at) }, { label: 'Closed', value: (r) => (r.closed_at ? dateTime(r.closed_at) : 'Still open') },
        { label: 'Sales', value: (r) => r.sales_count, align: 'right' }, { label: 'Gross', value: (r) => r.gross_total, align: 'right', money: true },
        { label: 'Expected cash', value: (r) => r.expected_cash, align: 'right', money: true },
        { label: 'Counted cash', value: (r) => r.counted_cash, align: 'right', money: true },
        { label: 'Difference', value: (r) => r.variance, align: 'right', money: true },
        { label: 'Note', value: (r) => r.closing_note },
      ],
    }],
  },
  {
    id: 'stock', title: 'Stock on hand & valuation', roles: MANAGEMENT, fetch: getStockReport,
    description: 'Current unexpired stock per product against its reorder level, valued at cost and at selling price.',
    summary: (d) => [
      ['Products', d.summary.product_count], ['Low', d.summary.low_count], ['Out of stock', d.summary.out_count],
      ['Value at cost', money(d.summary.cost_value)], ['Value at selling price', money(d.summary.retail_value)],
    ],
    tables: (d) => [{
      title: 'Stock', rows: d.rows, columns: [
        { label: 'Store', value: (r) => r.store }, { label: 'Product', value: (r) => r.product },
        { label: 'Usable qty', value: (r) => r.usable_qty, align: 'right' }, { label: 'Expired qty', value: (r) => r.expired_qty, align: 'right' },
        { label: 'Reorder level', value: (r) => r.reorder_level, align: 'right' },
        { label: 'Status', value: (r) => ({ ok: 'OK', low: 'Low', out: 'Out' }[r.status]) },
        { label: 'Cost value', value: (r) => r.cost_value, align: 'right', money: true },
        { label: 'Retail value', value: (r) => r.retail_value, align: 'right', money: true },
      ],
    }],
  },
  {
    id: 'expiry', title: 'Batch expiry', roles: MANAGEMENT, usesDays: true, fetch: getExpiryReport,
    description: 'Batches with stock that have expired or expire within the chosen number of days.',
    summary: (d) => [['Expired batches', d.summary.expired_count], ['Expiring batches', d.summary.expiring_count], ['Value at cost', money(d.summary.cost_value)]],
    tables: (d) => [{
      title: 'Batches', rows: d.rows, columns: [
        { label: 'Store', value: (r) => r.store }, { label: 'Product', value: (r) => r.product }, { label: 'Batch', value: (r) => r.batch_no },
        { label: 'Expiry', value: (r) => r.expiry_date },
        { label: 'Days left', value: (r) => (r.days_left < 0 ? `Expired ${-r.days_left}d ago` : r.days_left), align: 'right' },
        { label: 'Qty', value: (r) => r.qty, align: 'right' }, { label: 'Cost value', value: (r) => r.cost_value, align: 'right', money: true },
      ],
    }],
  },
  {
    id: 'purchases', title: 'Purchases', roles: MANAGEMENT, usesDates: true, fetch: getPurchasesReport,
    description: 'Received supplier invoices in the period, with totals per supplier.',
    summary: (d) => [
      ['Invoices', d.summary.invoice_count], ['Total', money(d.summary.total)],
      ...d.summary.by_supplier.map((s) => [s.supplier, `${money(s.total)} (${s.count})`]),
    ],
    tables: (d) => [{
      title: 'Invoices', rows: d.rows, columns: [
        { label: 'Received', value: (r) => r.received_date }, { label: 'Store', value: (r) => r.store },
        { label: 'Supplier', value: (r) => r.supplier }, { label: 'Invoice no.', value: (r) => r.invoice_number },
        { label: 'Total', value: (r) => r.total, align: 'right', money: true },
      ],
    }],
  },
  {
    id: 'losses', title: 'Losses & adjustments', roles: MANAGEMENT, usesDates: true, fetch: getLossesReport,
    description: 'Stock written off (expired, damaged, lost, stolen...) and stock-count corrections, valued at cost.',
    summary: (d) => [
      ['Entries', d.summary.entries], ['Total value', money(d.summary.value)],
      ...d.summary.by_reason.map((r) => [r.reason, `${money(r.value)} (${r.count})`]),
    ],
    tables: (d) => [{
      title: 'Adjustments', rows: d.rows, columns: [
        { label: 'Date', value: (r) => dateTime(r.date) }, { label: 'Store', value: (r) => r.store },
        { label: 'Product', value: (r) => r.product }, { label: 'Batch', value: (r) => r.batch_no },
        { label: 'Reason', value: (r) => r.reason }, { label: 'Qty', value: (r) => r.qty, align: 'right' },
        { label: 'Unit', value: (r) => r.unit }, { label: 'Value at cost', value: (r) => r.value, align: 'right', money: true },
        { label: 'By', value: (r) => r.by }, { label: 'Note', value: (r) => r.note },
      ],
    }],
  },
  {
    id: 'payables', title: 'Supplier balances', roles: MANAGERS, fetch: (p) => client.get('/api/reports/payables/', p),
    description: 'What is still owed to each supplier, and how overdue it is. Record payments on the invoice under Receiving.',
    summary: (d) => [
      ['Owed', money(d.summary.owed)], ['Overdue', money(d.summary.overdue)], ['Unpaid invoices', d.summary.invoice_count],
    ],
    tables: (d) => [
      {
        title: 'By supplier', rows: d.by_supplier, columns: [
          { label: 'Supplier', value: (r) => r.supplier }, { label: 'Owed', value: (r) => r.balance, align: 'right', money: true },
          { label: 'Not yet due', value: (r) => r.not_due, align: 'right', money: true },
          { label: '1–30 days late', value: (r) => r.overdue_1_30, align: 'right', money: true },
          { label: '31–60 days late', value: (r) => r.overdue_31_60, align: 'right', money: true },
          { label: '61+ days late', value: (r) => r.overdue_61_plus, align: 'right', money: true },
        ],
      },
      {
        title: 'Unpaid invoices', rows: d.rows, columns: [
          { label: 'Supplier', value: (r) => r.supplier }, { label: 'Invoice', value: (r) => r.invoice_number },
          { label: 'Store', value: (r) => r.store }, { label: 'Received', value: (r) => r.received_date },
          { label: 'Due', value: (r) => r.due_date }, { label: 'Days late', value: (r) => r.days_overdue, align: 'right' },
          { label: 'Total', value: (r) => r.total, align: 'right', money: true },
          { label: 'Paid', value: (r) => r.paid, align: 'right', money: true },
          { label: 'Owed', value: (r) => r.balance, align: 'right', money: true },
        ],
      },
    ],
  },
  {
    id: 'margin', title: 'Gross margin', roles: MANAGERS, usesDates: true, fetch: (p) => client.get('/api/reports/margin/', p),
    description: 'Sales without VAT, less what the units sold cost (each batch at its own purchase cost). Products received with no cost show their full sales as margin — check the count below.',
    summary: (d) => [
      ['Sales (ex VAT)', money(d.summary.sales_ex_vat)], ['Cost of goods', money(d.summary.cost)],
      ['Gross margin', money(d.summary.margin)], ['Margin %', d.summary.margin_pct === null ? '—' : `${d.summary.margin_pct}%`],
      ['Products with unknown cost', d.summary.products_without_cost],
    ],
    tables: (d) => [{
      title: 'By product', rows: d.rows, columns: [
        { label: 'Product', value: (r) => r.product }, { label: 'Qty sold', value: (r) => r.qty, align: 'right' },
        { label: 'Unit', value: (r) => r.unit },
        { label: 'Sales (ex VAT)', value: (r) => r.sales_ex_vat, align: 'right', money: true },
        { label: 'Cost', value: (r) => r.cost, align: 'right', money: true },
        { label: 'Margin', value: (r) => r.margin, align: 'right', money: true },
        { label: 'Margin %', value: (r) => (r.margin_pct === null ? '—' : `${r.margin_pct}%`), align: 'right' },
        { label: 'Cost unknown for', value: (r) => (Number(r.cost_unknown_qty) ? `${Number(r.cost_unknown_qty)} ${r.unit}` : ''), align: 'right' },
      ],
    }],
  },
  {
    id: 'movers', title: 'Fast & slow movers', roles: MANAGEMENT, usesDays: true, daysLabel: 'Sales over the last (days)',
    fetch: (p) => client.get('/api/reports/movers/', p),
    description: 'What sells and what sits. Days of cover = how long current stock lasts at the recent rate of sale. Dead stock has stock but no sales in the period — consider returning or transferring it before it expires.',
    summary: (d) => [['Fast movers', d.summary.fast], ['Slow (over 180 days of cover)', d.summary.slow], ['Dead stock', d.summary.dead]],
    tables: (d) => [{
      title: 'Products', rows: d.rows, columns: [
        { label: 'Product', value: (r) => r.product }, { label: 'Unit', value: (r) => r.unit },
        { label: 'Sold', value: (r) => r.sold, align: 'right' }, { label: 'Per day', value: (r) => r.per_day, align: 'right' },
        { label: 'In stock', value: (r) => r.on_hand, align: 'right' },
        { label: 'Days of cover', value: (r) => (r.days_of_cover === null ? '—' : r.days_of_cover), align: 'right' },
        { label: 'Class', value: (r) => ({ fast: 'Fast', normal: 'Normal', slow: 'Slow', dead: 'Dead stock' }[r.class]) },
      ],
    }],
  },
  {
    id: 'transfers', title: 'Transfers between stores', roles: MANAGERS, usesDates: true, feature: 'transfer', fetch: getTransfersReport,
    description: 'Stock sent between stores in the period, valued at cost. In transit, short deliveries and branch balances are as of today, whatever the period.',
    summary: (d) => [
      ['Transfers', d.summary.count], ['Value at cost', money(d.summary.value)], ['In transit now', d.summary.in_transit],
      ['Short deliveries to resolve', d.summary.short_deliveries], ['Branches owe the main store', money(d.summary.branches_owe)],
    ],
    tables: (d) => [
      {
        title: 'Transfers', rows: d.rows, columns: [
          { label: 'No.', value: (r) => r.number }, { label: 'Sent', value: (r) => dateTime(r.date) },
          { label: 'From', value: (r) => r.from_store }, { label: 'To', value: (r) => r.to_store },
          { label: 'Items', value: (r) => r.items }, { label: 'Status', value: (r) => r.status },
          { label: 'Value at cost', value: (r) => r.value, align: 'right', money: true },
          { label: 'Owed', value: (r) => (r.mode === 'hub' ? r.balance : null), align: 'right', money: true },
        ],
      },
      {
        title: 'Owed by branch', rows: d.owed_by_branch, columns: [
          { label: 'Branch', value: (r) => r.store }, { label: 'Unpaid transfers', value: (r) => r.count, align: 'right' },
          { label: 'Owed', value: (r) => r.balance, align: 'right', money: true },
        ],
      },
    ],
  },
  {
    id: 'credit', title: 'Customer credit (madeni)', roles: MANAGERS, feature: 'customer_credit',
    fetch: () => listAllCustomers({ owing: 'true' }),
    description: 'Every customer who owes money now, with their credit limit. Take repayments and print statements under Customers.',
    summary: (d) => [
      ['Owed by customers', money(d.reduce((sum, c) => sum + Number(c.owing), 0))], ['Customers owing', d.length],
      ['Over their limit', d.filter((c) => c.credit_limit !== null && Number(c.owing) > Number(c.credit_limit)).length],
    ],
    tables: (d) => [{
      title: 'Customers owing', rows: [...d].sort((a, b) => Number(b.owing) - Number(a.owing)), columns: [
        { label: 'Customer', value: (r) => r.name }, { label: 'Phone', value: (r) => r.phone },
        { label: 'Bought on credit', value: (r) => r.credit_total, align: 'right', money: true },
        { label: 'Paid back', value: (r) => r.paid_total, align: 'right', money: true },
        { label: 'Owes', value: (r) => r.owing, align: 'right', money: true },
        { label: 'Credit limit', value: (r) => (r.credit_limit === null ? 'No limit' : money(r.credit_limit)) },
      ],
    }],
  },
]

const todayIso = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
const monthStartIso = () => todayIso().slice(0, 8) + '01'

export default function Reports({ role, storeId, storeName, entity, features }) {
  const available = REPORTS.filter((r) => r.roles.includes(role) && (!r.feature || features?.[r.feature] !== false))
  const [reportId, setReportId] = useState(available[0]?.id)
  const [start, setStart] = useState(monthStartIso())
  const [end, setEnd] = useState(todayIso())
  const [days, setDays] = useState('90')
  const [state, setState] = useState({ data: null, loading: false, error: '' })
  const report = available.find((r) => r.id === reportId)

  async function run() {
    setState({ data: null, loading: true, error: '' })
    try {
      const params = { store: storeId || undefined }
      if (report.usesDates) Object.assign(params, { start, end })
      if (report.usesDays) params.days = days
      setState({ data: await report.fetch(params), loading: false, error: '' })
    } catch (err) {
      setState({ data: null, loading: false, error: err.body?.detail || 'Could not load the report.' })
    }
  }

  function select(id) {
    setReportId(id)
    setState({ data: null, loading: false, error: '' })
  }

  const data = state.data
  const scope = storeId ? storeName : 'All stores'
  const period = report?.usesDates ? `${start} to ${end}`
    : report?.usesDays ? (report.id === 'movers' ? `Last ${days} days` : `Next ${days} days`)
      : `As at ${todayIso()}`

  return (
    <div>
      <PageHeader title="Reports" subtitle={`Run, print and download reports for ${scope}.`} />
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
        {available.map((r) => <Chip key={r.id} selected={r.id === reportId} onClick={() => select(r.id)}>{r.title}</Chip>)}
      </div>
      {report && (
        <Card style={{ marginBottom: 16, maxWidth: 900 }}>
          <p style={{ fontSize: 13, color: 'var(--fg-subtle)', margin: '0 0 12px' }}>{report.description} Scope: {scope}.</p>
          <div style={{ display: 'flex', gap: 16, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            {report.usesDates && (
              <>
                <Field label="Start date"><Input type="date" value={start} onChange={(e) => setStart(e.target.value)} style={{ width: 170 }} /></Field>
                <Field label="End date"><Input type="date" value={end} onChange={(e) => setEnd(e.target.value)} style={{ width: 170 }} /></Field>
              </>
            )}
            {report.usesDays && <Field label={report.daysLabel || 'Expiring within (days)'}><Input value={days} onChange={(e) => setDays(e.target.value)} style={{ width: 120 }} /></Field>}
            <Button variant="primary" onClick={run} disabled={state.loading}>{state.loading ? 'Loading…' : 'Run report'}</Button>
            {data && (
              <>
                {report.tables(data).map((t) => (
                  <Button key={t.title} onClick={() => downloadCsv(`${report.id}-${t.title.toLowerCase().replace(/\s+/g, '-')}-${todayIso()}.csv`, t.columns, t.rows)}>
                    <Icon name="download" size={16} /> {report.tables(data).length > 1 ? `${t.title} (Excel/CSV)` : 'Excel (CSV)'}
                  </Button>
                ))}
                <Button onClick={() => window.print()}><Icon name="download" size={16} /> Print / PDF</Button>
              </>
            )}
          </div>
        </Card>
      )}

      {state.error && <NoticeBox variant="error" style={{ maxWidth: 900 }}>{state.error}</NoticeBox>}
      {data && <ReportBody report={report} data={data} />}
      {data && (
        <PrintArea kind="report">
          <h2 style={{ margin: '0 0 4px' }}>{entity?.name} — {report.title}</h2>
          <div style={{ marginBottom: 12 }}>{scope} · {period} · printed {new Date().toLocaleString()}</div>
          <ReportBody report={report} data={data} plain />
        </PrintArea>
      )}
    </div>
  )
}

function ReportBody({ report, data, plain }) {
  const box = plain ? {} : { background: 'var(--white)', borderRadius: 'var(--radius-lg)', boxShadow: 'var(--shadow-card)', overflowX: 'auto' }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
        {report.summary(data).map(([label, value]) => (
          <div key={label}>
            <div style={{ fontSize: 12, color: plain ? '#444' : 'var(--fg-subtle)' }}>{label}</div>
            <div style={{ fontSize: plain ? 13 : 24, lineHeight: plain ? undefined : '32px', fontWeight: plain ? 600 : 700, color: plain ? undefined : 'var(--navy-800)' }}>{value}</div>
          </div>
        ))}
      </div>
      {report.tables(data).map((t) => (
        <div key={t.title}>
          {report.tables(data).length > 1 && <h3 style={{ fontSize: 14, fontWeight: 500, margin: '0 0 8px' }}>{t.title}</h3>}
          <div style={box}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>{t.columns.map((c) => <th key={c.label} style={th(c.align)}>{c.label}</th>)}</tr>
              </thead>
              <tbody>
                {t.rows.map((r, i) => (
                  <tr key={i}>
                    {t.columns.map((c) => {
                      const v = c.value(r)
                      return <td key={c.label} style={c.money ? { ...td(c.align), whiteSpace: 'nowrap' } : td(c.align)}>{c.money ? money(v) : (typeof v === 'number' || /^-?\d+\.\d+$/.test(v ?? '') ? num(v) : v)}</td>
                    })}
                  </tr>
                ))}
                {t.rows.length === 0 && <tr><td colSpan={t.columns.length} style={{ ...td(), textAlign: 'center' }}>Nothing in this period.</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </div>
  )
}

function th(align) {
  return { textAlign: align || 'left', fontWeight: 600, fontSize: 11, lineHeight: '16px', textTransform: 'uppercase', letterSpacing: 1.2, color: 'var(--fg-subtle)', padding: '12px 16px', borderBottom: '1px solid var(--grey-300)', whiteSpace: 'nowrap' }
}
function td(align) {
  return { padding: '14px 16px', borderBottom: '1px solid var(--grey-300)', textAlign: align || 'left', fontSize: 13, color: 'var(--grey-800, var(--grey-900))' }
}
