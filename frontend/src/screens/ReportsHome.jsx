import { useMemo, useState } from 'react'
import { Card, Chip, NoticeBox, StatCard } from '../components/ds/index.js'
import ChartCanvas from '../components/ds/ChartCanvas.jsx'
import { chartColors, moneyTick } from '../components/ds/chartTheme.js'
import { useApi } from '../hooks/useApi.js'
import { getSummary } from '../api/reports.js'
import { fmt } from '../appData.js'
import { dateLocale, t, useLanguage, useT } from '../i18n/index.js'

const PERIODS = [
  { key: 'today', label: 'Today', previous: 'yesterday' },
  { key: 'week', label: 'This week', previous: 'the same days last week' },
  { key: 'month', label: 'This month', previous: 'the same days last month' },
  { key: 'last_month', label: 'Last month', previous: 'the month before' },
]
const amount = (v) => (Math.round(Number(v)) || 0).toLocaleString('en-US')
const qty = (v) => Number(v).toLocaleString('en-US', { maximumFractionDigits: 2 })

/** Reports home: the questions an owner asks first — how much did I sell,
 * what did I earn, what sells, what is running out, who owes whom — for a
 * period picked with one tap. `onOpen(reportId, {start, end})` opens the
 * detailed report behind a card. */
export default function ReportsHome({ storeId, scope, features, onOpen }) {
  useT()
  const lang = useLanguage()
  const [period, setPeriod] = useState('today')
  const { data: d, loading, error } = useApi(() => getSummary({ period, store: storeId || undefined }), [period, storeId])
  const meta = PERIODS.find((p) => p.key === period)
  const range = d ? { start: d.start, end: d.end } : undefined
  const takesCredit = features?.customer_credit !== false

  const chart = useMemo(() => (d?.by_day?.length ? {
    type: 'bar',
    data: {
      labels: d.by_day.map((r) => new Date(`${r.date}T00:00:00`).toLocaleDateString(dateLocale(), { day: 'numeric', month: 'short' })),
      datasets: [{ label: t('Sales'), data: d.by_day.map((r) => Number(r.total)), backgroundColor: chartColors[0], hoverBackgroundColor: '#0A4FB5' }],
    },
    options: {
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => fmt(c.parsed.y) } } },
      scales: {
        x: { grid: { display: false }, ticks: { maxTicksLimit: 10 } },
        y: { beginAtZero: true, suggestedMax: 1000, border: { display: false }, ticks: { callback: moneyTick, precision: 0, maxTicksLimit: 5 } },
      },
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
  } : null), [d, lang])

  let change = null
  if (d && Number(d.sales.previous_total) > 0) {
    const pct = Math.round(((Number(d.sales.total) - Number(d.sales.previous_total)) / Number(d.sales.previous_total)) * 100)
    change = t(pct >= 0 ? '{n}% more than {when}' : '{n}% less than {when}', { n: Math.abs(pct), when: t(meta.previous) })
  }

  return (
    <div>
      <div className="ds-chip-row" role="group" aria-label={t('Period')}>
        {PERIODS.map((p) => <Chip key={p.key} selected={p.key === period} onClick={() => setPeriod(p.key)}>{t(p.label)}</Chip>)}
      </div>
      {error && <NoticeBox variant="error">{t('Could not load the report.')}</NoticeBox>}
      {loading && !d && <NoticeBox variant="info">{t('Loading…')}</NoticeBox>}
      {d && (
        <>
          <p className="rh-scope">{scope} · {d.start === d.end ? d.start : t('{start} to {end}', { start: d.start, end: d.end })}</p>
          <div className="ds-stat-grid rh-stats">
            <StatCard
              label={t('Money from sales')} unit="TZS" value={amount(d.sales.total)} icon="wallet" onClick={() => onOpen('sales', range)}
              caption={[t(d.sales.count === 1 ? '{n} sale' : '{n} sales', { n: d.sales.count }), change].filter(Boolean).join(' · ')}
            />
            <StatCard
              label={t('Profit')} unit="TZS" value={amount(d.profit.margin)} icon="analytics" onClick={() => onOpen('margin', range)}
              caption={d.profit.margin_pct === null ? t('No sales yet') : t('{pct}% of sales, after the cost of the goods', { pct: d.profit.margin_pct })}
            />
            {takesCredit && (
              <StatCard
                label={t('Customers owe you')} unit="TZS" value={amount(d.customers_owe.total)} icon="customers" onClick={() => onOpen('credit')}
                caption={t(d.customers_owe.count === 1 ? '{n} customer' : '{n} customers', { n: d.customers_owe.count })}
              />
            )}
            <StatCard
              label={t('You owe suppliers')} unit="TZS" value={amount(d.you_owe.total)} icon="receiving" onClick={() => onOpen('payables')}
              tone={Number(d.you_owe.overdue) > 0 ? 'orange' : undefined}
              caption={Number(d.you_owe.overdue) > 0 ? t('{amount} is past its due date', { amount: fmt(d.you_owe.overdue) }) : t('Nothing overdue')}
            />
          </div>

          {d.profit.products_without_cost > 0 && (
            <NoticeBox variant="warning" style={{ marginBottom: 16 }}>
              {t(d.profit.products_without_cost === 1
                ? '{n} product was sold with no buying price, so the profit shows higher than it really is. Enter the buying price when you add or receive stock.'
                : '{n} products were sold with no buying price, so the profit shows higher than it really is. Enter the buying price when you add or receive stock.',
              { n: d.profit.products_without_cost })}
            </NoticeBox>
          )}

          {chart && (
            <Card title={t('Sales per day')} meta={t(meta.label)} style={{ marginBottom: 16 }}>
              <ChartCanvas config={chart} height={220} label={t('Sales per day, {period}', { period: t(meta.label) })} />
            </Card>
          )}

          <div className="rh-grid">
            <ListCard
              title={t('Best sellers')} meta={t('By money taken')} onMore={() => onOpen('sales', range)}
              empty={t('No sales in this period.')}
              rows={d.best_sellers.map((r) => [r.product, `${qty(r.qty)} ${r.unit}`, fmt(r.value)])}
            />
            <ListCard
              title={t('Running low')} meta={t(d.running_low.count === 1 ? '{n} product to restock' : '{n} products to restock', { n: d.running_low.count })}
              onMore={() => onOpen('stock')} empty={t('Nothing is running low.')}
              rows={d.running_low.rows.map((r) => [r.product, r.status === 'out' ? t('Out of stock') : t('{qty} {unit} left', { qty: qty(r.qty), unit: r.unit }), ''])}
            />
            <ListCard
              title={t('Not selling')} meta={t('In stock, no sale in {n} days', { n: d.not_selling.days })}
              onMore={() => onOpen('movers', { days: d.not_selling.days })} empty={t('Everything in stock has sold recently.')}
              rows={d.not_selling.rows.map((r) => [r.product, t('{qty} {unit} on the shelf', { qty: qty(r.qty), unit: r.unit }), ''])}
              hint={d.not_selling.count > 0 ? t('Consider a discount, or stop buying it, before it expires or ties up your money.') : null}
            />
            <ListCard
              title={t('How the money came in')} meta={t(meta.label)} onMore={() => onOpen('sales', range)}
              empty={t('No sales in this period.')}
              rows={d.payments.map((p) => [t(p.name), '', fmt(p.total)])}
            />
          </div>
        </>
      )}
    </div>
  )
}

function ListCard({ title, meta, rows, empty, hint, onMore }) {
  useT()
  return (
    <Card
      title={title} meta={meta}
      action={<button type="button" className="login-link rh-more" onClick={onMore}>{t('See details')}</button>}
    >
      {rows.length === 0
        ? <p className="rh-empty">{empty}</p>
        : (
          <ul className="rh-list">
            {rows.map(([name, detail, value], i) => (
              <li key={`${name}-${i}`}>
                <span className="rh-name">{name}{detail && <span className="rh-detail">{detail}</span>}</span>
                {value && <span className="rh-value">{value}</span>}
              </li>
            ))}
          </ul>
        )}
      {hint && <p className="rh-hint">{hint}</p>}
    </Card>
  )
}
