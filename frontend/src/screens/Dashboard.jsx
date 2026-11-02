import { Button, NoticeBox, PageHeader, StatCard } from '../components/ds/index.js'
import { useApi } from '../hooks/useApi.js'
import { getDashboard } from '../api/reports.js'
import PinnedVisualizations from './analytics/PinnedVisualizations.jsx'
import { useT } from '../i18n/index.js'


/** storeId null = an entity_admin's firm-wide view across every store. */
export default function Dashboard({ storeId, storeName, goTo, canGo = () => true }) {
  const t = useT()
  const { data: d, loading, error } = useApi(() => getDashboard({ store: storeId || undefined }), [storeId])
  const scope = storeId ? storeName : t('All stores')
  const link = (to) => (to && goTo && canGo(to) ? () => goTo(to) : undefined)

  const cards = d ? [
    {
      label: t('Sales today'), unit: 'TZS', value: (Math.round(Number(d.sales_today_total)) || 0).toLocaleString('en-US'),
      caption: `${t(d.sales_today_count === 1 ? '{n} sale' : '{n} sales', { n: d.sales_today_count })} · ${scope}`, icon: 'wallet', to: 'reports',
    },
    { label: t('Low on stock'), value: d.low_stock_count, caption: t('At or below reorder level'), icon: 'stock', tone: 'orange', to: 'stock' },
    { label: t('Out of stock'), value: d.stocked_out_count, caption: t('No unexpired stock left'), icon: 'package-x', tone: 'orange', to: 'stock' },
    { label: t('Expiring in 30 days'), value: d.expiring_30_count, caption: t('Batches to sell first or return'), icon: 'expiry', tone: 'orange', to: 'stock' },
    { label: t('Open shifts'), value: d.open_shifts_count, caption: t('Tills currently trading'), icon: 'pos' },
    { label: t('Open enquiries'), value: d.open_enquiries_count, caption: t('Awaiting response'), icon: 'transfer', to: 'enquiries' },
  ] : []

  return (
    <div>
      <PageHeader
        title={t('Dashboard')}
        subtitle={storeId ? t('Today at {store}.', { store: storeName }) : t('Overview across all stores in your entity.')}
      />
      {error && <NoticeBox variant="error" style={{ marginBottom: 24 }}>{t('Could not load the dashboard.')}</NoticeBox>}
      {loading && !d && <NoticeBox variant="info" style={{ marginBottom: 24 }}>{t('Loading…')}</NoticeBox>}
      {d && (d.expired_on_shelf_count > 0 || d.sales_missing_efd > 0) && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 24 }}>
          {d.expired_on_shelf_count > 0 && (
            <NoticeBox
              variant="warning"
              title={t(d.expired_on_shelf_count === 1 ? '{n} expired batch is still on the shelf' : '{n} expired batches are still on the shelf', { n: d.expired_on_shelf_count })}
              action={link('stock') && <Button variant="primary" onClick={link('stock')}>{t('Review batches')}</Button>}
            >
              {t('They can no longer be sold. Remove them from the shelf and write them off in the stock module.')}
            </NoticeBox>
          )}
          {d.sales_missing_efd > 0 && (
            <NoticeBox
              variant="warning"
              title={t(d.sales_missing_efd === 1 ? '{n} sale today has no EFD receipt number' : '{n} sales today have no EFD receipt number', { n: d.sales_missing_efd })}
              action={link('pos') && <Button variant="primary" onClick={link('pos')}>{t('Open point of sale')}</Button>}
            >
              {t('Every sale must have a fiscal receipt. Enter the missing numbers under Point of sale → Shift sales.')}
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
