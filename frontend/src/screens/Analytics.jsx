import { useMemo, useState } from 'react'
import { Card, ChartCanvas, Chip, EmptyState, NoticeBox, PageHeader, StatCard } from '../components/ds/index.js'
import { chartColors, moneyTick } from '../components/ds/chartTheme.js'
import DataVisualizer from './analytics/DataVisualizer.jsx'
import { useApi } from '../hooks/useApi.js'
import { getSalesReport, getSalesTrend, getStockReport } from '../api/reports.js'
import { fmt } from '../appData.js'

const isoDay = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

/** `openVizId`: a saved visualization to open (a dashboard widget's link). */
export default function Analytics({ storeId, storeName, openVizId }) {
  const [tab, setTab] = useState('visualizer')
  // A widget's link always lands on the visualizer, even from Overview.
  const [lastVizId, setLastVizId] = useState(openVizId)
  if (openVizId !== lastVizId) {
    setLastVizId(openVizId)
    if (openVizId) setTab('visualizer')
  }
  return (
    <div>
      <PageHeader title="Analytics" subtitle={`Explore sales, profit, purchases and stock for ${storeId ? storeName : 'all stores in your entity'}.`} />
      <div className="ds-chip-row">
        <Chip selected={tab === 'visualizer'} onClick={() => setTab('visualizer')}>Data visualizer</Chip>
        <Chip selected={tab === 'overview'} onClick={() => setTab('overview')}>Overview</Chip>
      </div>
      {/* Kept mounted, so switching tabs doesn't lose the table being built. */}
      <div hidden={tab !== 'visualizer'}><DataVisualizer storeId={storeId} openVizId={openVizId} /></div>
      {tab === 'overview' && <Overview storeId={storeId} />}
    </div>
  )
}

function Overview({ storeId }) {
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
        label: 'Sales', data: (trend ?? []).map((d) => Number(d.total)),
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
  }), [trend])

  const productConfig = useMemo(() => ({
    type: 'bar',
    data: {
      labels: topProducts.map((p) => p.product),
      datasets: [{ label: 'Sales value', data: topProducts.map((p) => Number(p.value)), backgroundColor: chartColors[0], borderRadius: 6, borderSkipped: 'start' }],
    },
    options: {
      indexAxis: 'y',
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => fmt(c.parsed.x) } } },
      scales: {
        x: { beginAtZero: true, border: { display: false }, ticks: { callback: moneyTick, maxTicksLimit: 5 } },
        y: { grid: { display: false }, ticks: { callback(v) { const l = this.getLabelForValue(v); return l.length > 22 ? `${l.slice(0, 21)}…` : l } } },
      },
    },
  }), [topProducts])

  return (
    <div>
      {trendError && <NoticeBox variant="error" style={{ marginBottom: 20 }}>Could not load analytics.</NoticeBox>}

      {stock && (
        <div className="ds-stat-grid" style={{ marginBottom: 20 }}>
          <StatCard label="Stock at cost" unit="TZS" value={money(stock.summary.cost_value)} caption="Unexpired stock on hand today" icon="stock" />
          <StatCard label="Stock at selling price" unit="TZS" value={money(stock.summary.retail_value)} caption="What it would sell for" icon="wallet" />
          <StatCard label="Products low on stock" value={stock.summary.low_count} caption="At or below reorder level" icon="stock" tone="orange" />
          <StatCard label="Products out of stock" value={stock.summary.out_count} caption="No unexpired stock left" icon="package-x" tone="orange" />
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(320px,1fr))', gap: 20 }}>
        <Card title="Sales — last 30 days" meta={`${fmt(trendTotal)} total · ${fmt(trendTotal / 30)} per day on average`}>
          <ChartCanvas config={trendConfig} height={280} label="Daily sales over the last 30 days" />
        </Card>

        <Card title="Top products this month" meta={`By sales value · ${month ? fmt(Number(month.summary.gross_total)) : '…'} this month`}>
          {month && topProducts.length === 0
            ? <EmptyState icon="analytics" title="No sales yet this month" hint="Products appear here once they are sold." />
            : <ChartCanvas config={productConfig} height={Math.max(240, topProducts.length * 34)} label="Top products by sales value this month" />}
        </Card>
      </div>
    </div>
  )
}

const money = (v) => (Math.round(Number(v)) || 0).toLocaleString('en-US')
