import { useMemo, useState } from 'react'
import { Card, ChartCanvas, Chip, EmptyState, NoticeBox, PageHeader, StatCard } from '../components/ds/index.js'
import { chartColors, moneyTick } from '../components/ds/chartTheme.js'
import DataVisualizer from './analytics/DataVisualizer.jsx'
import { useApi } from '../hooks/useApi.js'
import { getSalesReport, getSalesTrend, getStockReport } from '../api/reports.js'
import { fmt } from '../appData.js'
import { t, useLanguage, useT } from '../i18n/index.js'

const isoDay = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

/** `openVizId`: a saved visualization to open (a dashboard widget's link). */
export default function Analytics({ storeId, storeName, openVizId }) {
  useT()
  const [tab, setTab] = useState('visualizer')
  // A widget's link always lands on the visualizer, even from Overview.
  const [lastVizId, setLastVizId] = useState(openVizId)
  if (openVizId !== lastVizId) {
    setLastVizId(openVizId)
    if (openVizId) setTab('visualizer')
  }
  return (
    <div>
      <PageHeader title={t('Analytics')} subtitle={storeId ? t('Explore sales, profit, purchases and stock for {store}.', { store: storeName }) : t('Explore sales, profit, purchases and stock for all stores in your entity.')} />
      <div className="ds-chip-row">
        <Chip selected={tab === 'visualizer'} onClick={() => setTab('visualizer')}>{t('Data visualizer')}</Chip>
        <Chip selected={tab === 'overview'} onClick={() => setTab('overview')}>{t('Overview')}</Chip>
      </div>
      {/* Kept mounted, so switching tabs doesn't lose the table being built. */}
      <div hidden={tab !== 'visualizer'}><DataVisualizer storeId={storeId} openVizId={openVizId} /></div>
      {tab === 'overview' && <Overview storeId={storeId} />}
    </div>
  )
}

function Overview({ storeId }) {
  const lang = useLanguage()
  const store = storeId || undefined
  const now = new Date()
  const monthStart = isoDay(new Date(now.getFullYear(), now.getMonth(), 1))
  const { data: trend, error: trendError } = useApi(() => getSalesTrend({ store, days: 30 }), [storeId])
  const { data: month } = useApi(() => getSalesReport({ store, start: monthStart, end: isoDay(now) }), [storeId])
  const { data: stock } = useApi(() => getStockReport({ store }), [storeId])

  const trendTotal = (trend ?? []).reduce((s, d) => s + Number(d.total), 0)
  const topProducts = useMemo(() => (month?.by_product ?? []).slice(0, 10), [month])

  const trendConfig = useMemo(() => ({
    type: 'line',
    data: {
      labels: (trend ?? []).map((d) => d.date.slice(5)),
      datasets: [{
        label: t('Sales'), data: (trend ?? []).map((d) => Number(d.total)),
        borderColor: chartColors[0], backgroundColor: 'rgba(11,94,215,.14)', pointBackgroundColor: chartColors[0], fill: true,
      }],
    },
    options: {
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => fmt(c.parsed.y) } } },
      scales: {
        x: { grid: { display: false }, ticks: { maxTicksLimit: 8 } },
        y: { beginAtZero: true, suggestedMax: 1000, border: { display: false }, ticks: { callback: moneyTick, precision: 0, maxTicksLimit: 6 } },
      },
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [trend, lang])

  const productConfig = useMemo(() => ({
    type: 'bar',
    data: {
      labels: topProducts.map((p) => p.product),
      datasets: [{ label: t('Sales value'), data: topProducts.map((p) => Number(p.value)), backgroundColor: chartColors[0], borderRadius: 6, borderSkipped: 'start' }],
    },
    options: {
      indexAxis: 'y',
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => fmt(c.parsed.x) } } },
      scales: {
        x: { beginAtZero: true, border: { display: false }, ticks: { callback: moneyTick, maxTicksLimit: 5 } },
        y: { grid: { display: false }, ticks: { callback(v) { const l = this.getLabelForValue(v); return l.length > 22 ? `${l.slice(0, 21)}…` : l } } },
      },
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [topProducts, lang])

  return (
    <div>
      {trendError && <NoticeBox variant="error" style={{ marginBottom: 20 }}>{t('Could not load analytics.')}</NoticeBox>}

      {stock && (
        <div className="ds-stat-grid" style={{ marginBottom: 20 }}>
          <StatCard label={t('Stock at cost')} unit="TZS" value={money(stock.summary.cost_value)} caption={t('Unexpired stock on hand today')} icon="stock" />
          <StatCard label={t('Stock at selling price')} unit="TZS" value={money(stock.summary.retail_value)} caption={t('What it would sell for')} icon="wallet" />
          <StatCard label={t('Products low on stock')} value={stock.summary.low_count} caption={t('At or below reorder level')} icon="stock" tone="orange" />
          <StatCard label={t('Products out of stock')} value={stock.summary.out_count} caption={t('No unexpired stock left')} icon="package-x" tone="orange" />
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(320px,1fr))', gap: 20 }}>
        <Card title={t('Sales — last 30 days')} meta={t('{total} total · {avg} per day on average', { total: fmt(trendTotal), avg: fmt(trendTotal / 30) })}>
          <ChartCanvas config={trendConfig} height={280} label={t('Daily sales over the last 30 days')} />
        </Card>

        <Card title={t('Top products this month')} meta={t('By sales value · {amount} this month', { amount: month ? fmt(Number(month.summary.gross_total)) : '…' })}>
          {month && topProducts.length === 0
            ? <EmptyState icon="analytics" title={t('No sales yet this month')} hint={t('Products appear here once they are sold.')} />
            : <ChartCanvas config={productConfig} height={Math.max(240, topProducts.length * 34)} label={t('Top products by sales value this month')} />}
        </Card>
      </div>
    </div>
  )
}

const money = (v) => (Math.round(Number(v)) || 0).toLocaleString('en-US')
