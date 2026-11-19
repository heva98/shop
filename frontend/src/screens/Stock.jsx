import { useMemo, useState } from 'react'
import { Button, Chip, DataTable, EmptyState, Icon, NoticeBox, PageHeader, Tag } from '../components/ds/index.js'
import { useApi } from '../hooks/useApi.js'
import { listAllBatches, listAllStoreProducts, listAllLedger } from '../api/inventory.js'
import { listAllProducts } from '../api/catalog.js'
import { StockTake, WriteOffs } from './StockControl.jsx'
import QuickAddProduct from '../components/QuickAddProduct.jsx'
import { dateLocale, t, useLanguage } from '../i18n/index.js'

const LEDGER_TYPE_LABEL = {
  transfer_in: 'Transfer In', transfer_out: 'Transfer Out', stolen: 'Stolen', lost: 'Lost',
  damaged: 'Damaged', expired: 'Expired', cold_chain_failure: 'Spoiled (fridge failed)',
  wrong_entry: 'Wrong entry corrected', sold: 'Sold', sale_void: 'Sale voided', discard: 'Thrown away', consumption: 'Used in the shop', dispose: 'Disposed',
  opening_stock: 'Opening stock', stock_count: 'Corrected after a count',
  unrecorded: 'Sold without recorded stock',
}
const LEDGER_GROUPS = {
  Transfers: ['transfer_in', 'transfer_out', 'opening_stock'],
  Sales: ['sold', 'sale_void', 'unrecorded'],
  Losses: ['stolen', 'lost', 'damaged', 'expired', 'cold_chain_failure', 'wrong_entry', 'discard', 'dispose', 'stock_count'],
  'Used in the shop': ['consumption'],
}
const STOCK_TAB_DEFS = [
  { key: 'list', label: 'List' }, { key: 'nearly-stocked', label: 'Running low' }, { key: 'stocked-out', label: 'Out of stock' },
  { key: 'nearly-expired', label: 'Expiring soon' }, { key: 'expired', label: 'Expired' }, { key: 'ledger', label: 'Stock history' },
  { key: 'count', label: 'Count stock', roles: ['storekeeper', 'store_manager', 'entity_admin'] },
  { key: 'write-offs', label: 'Losses & damage', roles: ['storekeeper', 'store_manager', 'entity_admin'] },
]
const MANAGER_ROLES = ['store_manager', 'entity_admin']

export default function Stock({ storeId, storeName, roles, goTo, canGo = () => false }) {
  const lang = useLanguage()
  const isManager = MANAGER_ROLES.some((r) => roles.includes(r))
  const [tab, setTab] = useState('list')
  const [expanded, setExpanded] = useState({})
  const [ledgerGroup, setLedgerGroup] = useState('all')
  // Catalogue changes are the owner's (catalog/setup.py): { product? } while the form is open.
  const isOwner = roles.includes('entity_admin')
  const [adding, setAdding] = useState(null)

  const { data: products } = useApi(() => (storeId ? listAllProducts() : null), [storeId])
  const { data: batches, loading: batchesLoading, error: batchesError, refetch: refetchBatches } = useApi(
    () => (storeId ? listAllBatches({ store: storeId }) : null), [storeId],
  )
  const { data: storeProducts, refetch: refetchStoreProducts } = useApi(() => (storeId ? listAllStoreProducts({ store: storeId }) : null), [storeId])
  const { data: ledger, loading: ledgerLoading, error: ledgerError, refetch: refetchLedger } = useApi(
    () => (storeId && tab === 'ledger' ? listAllLedger({ store: storeId }) : null), [storeId, tab],
  )

  const productNameById = useMemo(() => {
    const map = {}
    for (const p of products ?? []) map[p.id] = p.name
    return map
  }, [products])

  const addStockTo = (id) => {
    const product = (products ?? []).find((p) => p.id === id)
    if (product) setAdding({ product: { id, name: product.name, uom_name: product.uom_name, tracks_expiry: product.tracks_expiry, has_price: true } })
  }

  const batchesWithStatus = useMemo(() => {
    const today = new Date()
    return (batches ?? []).map((b) => {
      // Goods that don't expire have no expiry date.
      const days = b.expiry_date ? Math.round((new Date(b.expiry_date) - today) / 86400000) : null
      const qty = Number(b.qty_on_hand)
      let status, statusLabel, daysLabel
      if (qty === 0) { status = 'stocked-out'; statusLabel = t('Out of stock'); daysLabel = '—' } else if (days === null) {
        status = 'ok'; statusLabel = t('In stock'); daysLabel = t('Does not expire')
      } else if (days < 0) {
        status = 'expired'; statusLabel = t('Expired'); daysLabel = t('Expired {n} days ago', { n: Math.abs(days) })
      } else if (days <= 30) { status = 'nearly-expired'; statusLabel = t('Expiring soon'); daysLabel = t('{n} days to expiry', { n: days }) } else {
        status = 'ok'; statusLabel = t('In stock'); daysLabel = t('{n} days to expiry', { n: days })
      }
      return { ...b, productName: b.product_name, qty, status, statusLabel, daysLabel }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batches, lang])

  const expiryFilter = tab === 'nearly-expired' ? 'nearly-expired' : tab === 'expired' ? 'expired' : null
  const visibleBatches = (expiryFilter ? batchesWithStatus.filter((b) => b.status === expiryFilter) : batchesWithStatus)
    .map((b, i) => ({
      id: b.id, name: b.productName, batch: b.batch_no, qty: b.qty, expiry: b.expiry_date, daysLabel: b.daysLabel, statusLabel: b.statusLabel,
      num: i + 1, isExpired: b.status === 'expired', isNearlyExpired: b.status === 'nearly-expired',
      isOk: b.status === 'ok', isStockedOut: b.status === 'stocked-out',
    }))

  const stockList = useMemo(() => {
    const byProduct = {}
    for (const b of batchesWithStatus) {
      byProduct[b.product] ??= { id: b.product, name: b.productName, batches: [] }
      byProduct[b.product].batches.push(b)
    }
    return Object.values(byProduct).map((p, i) => {
      const totalQty = p.batches.reduce((sum, b) => sum + b.qty, 0)
      const expiredQty = p.batches.filter((b) => b.status === 'expired').reduce((sum, b) => sum + b.qty, 0)
      const isExpanded = !!expanded[p.name]
      return {
        num: i + 1, id: p.id, name: p.name, totalQty, expiredQty, eligibleQty: totalQty - expiredQty, batchCount: p.batches.length,
        expanded: isExpanded, chevronIcon: isExpanded ? 'chevron-up' : 'chevron-down',
        toggle: () => setExpanded((prev) => ({ ...prev, [p.name]: !prev[p.name] })),
        batches: p.batches.map((b) => ({ batch: b.batch_no, qty: b.qty, expiry: b.expiry_date })),
      }
    })
  }, [batchesWithStatus, expanded])

  const stockLevels = useMemo(() => {
    const qtyByProduct = {}
    for (const b of batches ?? []) qtyByProduct[b.product] = (qtyByProduct[b.product] ?? 0) + Number(b.qty_on_hand)
    return (storeProducts ?? []).map((sp) => ({
      name: productNameById[sp.product] ?? sp.product,
      qty: qtyByProduct[sp.product] ?? 0,
      reorderLevel: Number(sp.reorder_level),
    }))
  }, [batches, storeProducts, productNameById])

  const levelFilter = tab === 'nearly-stocked' ? 'nearly' : tab === 'stocked-out' ? 'out' : null
  const visibleStockLevels = stockLevels.filter((l) => {
    if (levelFilter === 'out') return l.qty === 0
    if (levelFilter === 'nearly') return l.qty > 0 && l.qty <= l.reorderLevel
    return false
  }).map((l, i) => ({ num: i + 1, ...l }))

  const batchLookup = useMemo(() => {
    const map = {}
    for (const b of batches ?? []) map[b.id] = { batchNo: b.batch_no, productName: b.product_name }
    return map
  }, [batches])
  const visibleLedger = (ledger ?? [])
    .filter((le) => ledgerGroup === 'all' || (LEDGER_GROUPS[ledgerGroup] ?? []).includes(le.ledger_type))
    .map((le) => {
      const delta = Number(le.qty_delta)
      const type = LEDGER_TYPE_LABEL[le.ledger_type] ? t(LEDGER_TYPE_LABEL[le.ledger_type]) : le.ledger_type
      return {
        id: le.id,
        product: batchLookup[le.batch]?.productName ?? '', batch: batchLookup[le.batch]?.batchNo ?? '',
        store: storeName, type, timestamp: new Date(le.created_at).toLocaleString(dateLocale()),
        source: le.ref_type ? `${le.ref_type} ${le.ref_id}`.trim() : '—',
        deltaLabel: (delta > 0 ? '+' : '') + delta, deltaColor: delta > 0 ? 'var(--green-700)' : 'var(--red-700)',
        isPositive: le.ledger_type === 'transfer_in' || le.ledger_type === 'sale_void', isNegative: delta < 0, isNeutral: le.ledger_type === 'consumption',
      }
    })

  const stockTabs = STOCK_TAB_DEFS.filter((d) => !d.roles || d.roles.some((r) => roles.includes(r))).map((d) => ({ label: t(d.label), active: tab === d.key, select: () => setTab(d.key) }))
  const ledgerGroupChips = ['all', 'Transfers', 'Sales', 'Losses', 'Used in the shop'].map((g) => ({
    label: g === 'all' ? t('All') : t(g), active: ledgerGroup === g, select: () => setLedgerGroup(g),
  }))

  if (!storeId) return <NoticeBox variant="warning" title={t('No store selected')}>{t('Select a store to view stock.')}</NoticeBox>

  const batchState = { loading: batchesLoading, error: batchesError, errorTitle: t('Could not load stock data.'), onRetry: refetchBatches }
  const rowNumber = { key: 'num', header: '#', label: '', width: 40, align: 'center', hideOnMobile: true, cell: (_, i) => i + 1 }
  const listColumns = [
    rowNumber,
    { key: 'name', header: t('Product'), primary: true, sortable: true },
    { key: 'totalQty', header: t('Total qty'), align: 'end', sortable: true, firstDirection: 'desc' },
    { key: 'expiredQty', header: t('Expired qty'), align: 'end', sortable: true, firstDirection: 'desc' },
    { key: 'eligibleQty', header: t('Eligible qty'), align: 'end', sortable: true, firstDirection: 'desc' },
    { key: 'batchCount', header: t('Batches'), align: 'end', sortable: true, firstDirection: 'desc' },
    {
      key: 'expand', header: <span className="sr-only">{t('Show details')}</span>, label: '', width: 44, align: 'center',
      cell: (p) => (
        <button
          type="button" className="ds-dt-expand" aria-expanded={p.expanded} onClick={p.toggle}
          aria-label={`${p.expanded ? t('Hide details') : t('Show details')}: ${p.name}`}
        >
          <Icon name={p.chevronIcon} size={16} />
        </button>
      ),
    },
  ]
  const levelColumns = [
    rowNumber,
    { key: 'name', header: t('Product'), primary: true, sortable: true },
    { key: 'qty', header: t('Qty on hand'), align: 'end', sortable: true },
    { key: 'reorderLevel', header: t('Warn at'), align: 'end', sortable: true, firstDirection: 'desc' },
  ]
  const batchColumns = [
    rowNumber,
    { key: 'name', header: t('Product'), primary: true, sortable: true },
    { key: 'batch', header: t('Batch') },
    { key: 'qty', header: t('Qty'), align: 'end', sortable: true, firstDirection: 'desc' },
    {
      key: 'expiry', header: t('Expiry'), sortable: true,
      cell: (b) => <div><div>{b.expiry || '—'}</div><div className="ds-dt-sub">{b.daysLabel}</div></div>,
    },
    {
      key: 'status', header: t('Status'),
      cell: (b) => (
        <>
          {b.isExpired && <Tag variant="negative">{b.statusLabel}</Tag>}
          {b.isNearlyExpired && <Tag>{b.statusLabel}</Tag>}
          {b.isOk && <Tag variant="positive">{b.statusLabel}</Tag>}
          {b.isStockedOut && <Tag variant="negative" bold>{b.statusLabel}</Tag>}
        </>
      ),
    },
  ]
  const ledgerColumns = [
    { key: 'product', header: t('Product'), primary: true },
    { key: 'batch', header: t('Batch') },
    { key: 'store', header: t('Store'), hideOnMobile: true },
    { key: 'delta', header: t('Qty change'), align: 'end', cell: (le) => <span style={{ color: le.deltaColor }}>{le.deltaLabel}</span> },
    {
      key: 'type', header: t('Type'),
      cell: (le) => (
        <>
          {le.isPositive && <Tag variant="positive">{le.type}</Tag>}
          {le.isNegative && <Tag variant="negative">{le.type}</Tag>}
          {le.isNeutral && <Tag>{le.type}</Tag>}
          {!le.isPositive && !le.isNegative && !le.isNeutral && le.type}
        </>
      ),
    },
    { key: 'timestamp', header: t('Timestamp') },
    { key: 'source', header: t('Source') },
  ]

  return (
    <div>
      <PageHeader
        title={t('Stock')} subtitle={t('Batches, stock levels and movements at {store}.', { store: storeName })}
        actions={isOwner && <Button variant="primary" icon="add" onClick={() => setAdding({})}>{t('Add product')}</Button>}
      />
      {adding && (
        <QuickAddProduct
          product={adding.product} storeId={storeId} onClose={() => setAdding(null)}
          onSaved={() => { refetchBatches(); refetchStoreProducts() }}
        />
      )}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        {stockTabs.map((s) => <Chip key={s.label} selected={s.active} onClick={s.select}>{s.label}</Chip>)}
      </div>

      {tab === 'count' && <StockTake storeId={storeId} storeName={storeName} isManager={isManager} />}
      {tab === 'write-offs' && <WriteOffs storeId={storeId} isManager={isManager} />}

      {tab === 'list' && (
        <DataTable
          caption={t('Stock at {store}', { store: storeName })}
          columns={listColumns}
          rows={stockList}
          {...batchState}
          minWidth={640}
          renderDetail={(p) => (p.expanded ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, paddingLeft: 32 }}>
              {p.batches.map((pb) => (
                <div key={pb.batch ?? 'none'} style={{ display: 'flex', gap: 24, flexWrap: 'wrap', fontSize: 13 }}>
                  <span style={{ minWidth: 120 }}>{pb.batch || '—'}</span>
                  <span>{t('Qty')} {pb.qty}</span>
                  <span>{pb.expiry ? `${t('Exp')} ${pb.expiry}` : t('No expiry')}</span>
                </div>
              ))}
              <div><Button size="small" icon="add" disabled={!isOwner} onClick={() => addStockTo(p.id)}>{t('Add batch')}</Button></div>
            </div>
          ) : null)}
          empty={(
            <EmptyState
              icon="stock" title={t('No stock at {store} yet', { store: storeName })}
              hint={t('Stock shows here once you enter what is on your shelves, or record a delivery from a supplier. Each sale then takes it down by itself.')}
              action={(
                <>
                  {isOwner && <Button variant="primary" icon="add" onClick={() => setAdding({})}>{t('Add product')}</Button>}
                  {canGo('receiving') && <Button onClick={() => goTo('receiving')}>{t('Record a delivery')}</Button>}
                </>
              )}
            />
          )}
        />
      )}

      {(tab === 'nearly-stocked' || tab === 'stocked-out') && (
        <DataTable
          caption={tab === 'stocked-out' ? t('Out of stock') : t('Running low')}
          columns={levelColumns}
          rows={visibleStockLevels}
          rowKey="name"
          {...batchState}
          minWidth={520}
          empty={t('No products match this view.')}
        />
      )}

      {(tab === 'nearly-expired' || tab === 'expired') && (
        <DataTable
          caption={tab === 'expired' ? t('Expired') : t('Expiring soon')}
          columns={batchColumns}
          rows={visibleBatches}
          {...batchState}
          defaultSort={{ key: 'expiry', direction: 'asc' }}
          minWidth={640}
          empty={t('No batches match this filter.')}
        />
      )}

      {tab === 'ledger' && (
        <>
          <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
            {ledgerGroupChips.map((lg) => <Chip key={lg.label} selected={lg.active} dense onClick={lg.select}>{lg.label}</Chip>)}
          </div>
          <DataTable
            caption={t('Stock history')}
            columns={ledgerColumns}
            rows={visibleLedger}
            loading={ledgerLoading}
            error={ledgerError}
            onRetry={refetchLedger}
            density="compact"
            minWidth={760}
            empty={t('No stock movements match this filter.')}
          />
        </>
      )}
    </div>
  )
}
