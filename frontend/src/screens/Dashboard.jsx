import { Button, NoticeBox, PageHeader, StatCard } from '../components/ds/index.js'
import { useApi } from '../hooks/useApi.js'
import { getDashboard } from '../api/reports.js'
import PinnedVisualizations from './analytics/PinnedVisualizations.jsx'

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`

/** storeId null = an entity_admin's firm-wide view across every store. */
export default function Dashboard({ storeId, storeName, goTo, canGo = () => true }) {
  const { data: d, loading, error } = useApi(() => getDashboard({ store: storeId || undefined }), [storeId])
  const scope = storeId ? storeName : 'All stores'
  const link = (to) => (to && goTo && canGo(to) ? () => goTo(to) : undefined)

  const cards = d ? [
    {
      label: 'Sales today', unit: 'TZS', value: (Math.round(Number(d.sales_today_total)) || 0).toLocaleString('en-US'),
      caption: `${plural(d.sales_today_count, 'sale', 'sales')} · ${scope}`, icon: 'wallet', to: 'reports',
    },
    { label: 'Low on stock', value: d.low_stock_count, caption: 'At or below reorder level', icon: 'stock', tone: 'orange', to: 'stock' },
    { label: 'Out of stock', value: d.stocked_out_count, caption: 'No unexpired stock left', icon: 'package-x', tone: 'orange', to: 'stock' },
    { label: 'Expiring in 30 days', value: d.expiring_30_count, caption: 'Batches to sell first or return', icon: 'expiry', tone: 'orange', to: 'stock' },
    { label: 'Open shifts', value: d.open_shifts_count, caption: 'Tills currently trading', icon: 'pos' },
    { label: 'Open enquiries', value: d.open_enquiries_count, caption: 'Awaiting response', icon: 'transfer', to: 'enquiries' },
  ] : []

  return (
    <div>
      <PageHeader
        title="Dashboard"
        subtitle={storeId ? `Today at ${storeName}.` : 'Overview across all stores in your entity.'}
      />
      {error && <NoticeBox variant="error" style={{ marginBottom: 24 }}>Could not load the dashboard.</NoticeBox>}
      {loading && !d && <NoticeBox variant="info" style={{ marginBottom: 24 }}>Loading…</NoticeBox>}
      {d && (d.expired_on_shelf_count > 0 || d.sales_missing_efd > 0) && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 24 }}>
          {d.expired_on_shelf_count > 0 && (
            <NoticeBox
              variant="warning"
              title={`${plural(d.expired_on_shelf_count, 'expired batch is', 'expired batches are')} still on the shelf`}
              action={link('stock') && <Button variant="primary" onClick={link('stock')}>Review batches</Button>}
            >
              They can no longer be sold. Remove them from the shelf and write them off in the stock module.
            </NoticeBox>
          )}
          {d.sales_missing_efd > 0 && (
            <NoticeBox
              variant="warning"
              title={`${plural(d.sales_missing_efd, 'sale', 'sales')} today ${d.sales_missing_efd === 1 ? 'has' : 'have'} no EFD receipt number`}
              action={link('pos') && <Button variant="primary" onClick={link('pos')}>Open point of sale</Button>}
            >
              Every sale must have a fiscal receipt. Enter the missing numbers under Point of sale → Shift sales.
            </NoticeBox>
          )}
        </div>
      )}
      <div className="ds-stat-grid">
        {cards.map((card) => (
          <StatCard
            key={card.label} label={card.label} value={card.value} unit={card.unit} caption={card.caption}
            icon={card.icon} tone={card.tone} onClick={link(card.to)}
          />
        ))}
      </div>
      {canGo('analytics') && <PinnedVisualizations onOpen={(viz) => goTo('analytics', { viz })} />}
    </div>
  )
}
