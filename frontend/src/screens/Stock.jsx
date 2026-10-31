import { Fragment, useMemo, useState } from 'react'
import { Button, Chip, Icon, NoticeBox, PageHeader, Tag } from '../components/ds/index.js'
import { useApi } from '../hooks/useApi.js'
import { listAllBatches, listAllStoreProducts, listAllLedger } from '../api/inventory.js'
import { listAllProducts } from '../api/catalog.js'
import { StockTake, WriteOffs } from './StockControl.jsx'

const LEDGER_TYPE_LABEL = {
  transfer_in: 'Transfer In', transfer_out: 'Transfer Out', stolen: 'Stolen', lost: 'Lost',
  damaged: 'Damaged', expired: 'Expired', cold_chain_failure: 'Cold Chain Failure',
  wrong_entry: 'Wrong Entry', sold: 'Sold', sale_void: 'Sale voided', discard: 'Discard', consumption: 'Consumption', dispose: 'Dispose',
  opening_stock: 'Opening stock', stock_count: 'Stock count correction',
}
const LEDGER_GROUPS = {
  Transfers: ['transfer_in', 'transfer_out', 'opening_stock'],
  Sales: ['sold', 'sale_void'],
  Losses: ['stolen', 'lost', 'damaged', 'expired', 'cold_chain_failure', 'wrong_entry', 'discard', 'dispose', 'stock_count'],
  Consumption: ['consumption'],
}
const STOCK_TAB_DEFS = [
  { key: 'list', label: 'List' }, { key: 'nearly-stocked', label: 'Nearly stocked out' }, { key: 'stocked-out', label: 'Stocked out' },
  { key: 'nearly-expired', label: 'Nearly expired' }, { key: 'expired', label: 'Expired' }, { key: 'ledger', label: 'Ledger' },
  { key: 'count', label: 'Stock take', roles: ['storekeeper', 'store_manager', 'entity_admin'] },
  { key: 'write-offs', label: 'Write-offs', roles: ['storekeeper', 'store_manager', 'entity_admin'] },
]
const MANAGER_ROLES = ['store_manager', 'entity_admin']

export default function Stock({ storeId, storeName, roles }) {
  const isManager = MANAGER_ROLES.some((r) => roles.includes(r))
  const [tab, setTab] = useState('list')
  const [expanded, setExpanded] = useState({})
  const [ledgerGroup, setLedgerGroup] = useState('all')

  const { data: products } = useApi(() => (storeId ? listAllProducts() : null), [storeId])
  const { data: batches, loading: batchesLoading, error: batchesError } = useApi(
    () => (storeId ? listAllBatches({ store: storeId }) : null), [storeId],
  )
  const { data: storeProducts } = useApi(() => (storeId ? listAllStoreProducts({ store: storeId }) : null), [storeId])
  const { data: ledger, loading: ledgerLoading } = useApi(
    () => (storeId && tab === 'ledger' ? listAllLedger({ store: storeId }) : null), [storeId, tab],
  )

  const productNameById = useMemo(() => {
    const map = {}
    for (const p of products ?? []) map[p.id] = p.name
    return map
  }, [products])

  const batchesWithStatus = useMemo(() => {
    const today = new Date()
    return (batches ?? []).map((b) => {
      // Goods that don't expire have no expiry date.
      const days = b.expiry_date ? Math.round((new Date(b.expiry_date) - today) / 86400000) : null
      const qty = Number(b.qty_on_hand)
      let status, statusLabel, daysLabel
      if (qty === 0) { status = 'stocked-out'; statusLabel = 'Stocked out'; daysLabel = '—' } else if (days === null) {
        status = 'ok'; statusLabel = 'In stock'; daysLabel = 'Does not expire'
      } else if (days < 0) {
        status = 'expired'; statusLabel = 'Expired'; daysLabel = `Expired ${Math.abs(days)} days ago`
      } else if (days <= 30) { status = 'nearly-expired'; statusLabel = 'Nearly expired'; daysLabel = `${days} days to expiry` } else {
        status = 'ok'; statusLabel = 'In stock'; daysLabel = `${days} days to expiry`
      }
      return { ...b, productName: b.product_name, qty, status, statusLabel, daysLabel }
    })
  }, [batches])

  const expiryFilter = tab === 'nearly-expired' ? 'nearly-expired' : tab === 'expired' ? 'expired' : null
  const visibleBatches = (expiryFilter ? batchesWithStatus.filter((b) => b.status === expiryFilter) : batchesWithStatus)
    .map((b, i) => ({
      name: b.productName, batch: b.batch_no, qty: b.qty, expiry: b.expiry_date, daysLabel: b.daysLabel, statusLabel: b.statusLabel,
      num: i + 1, isExpired: b.status === 'expired', isNearlyExpired: b.status === 'nearly-expired',
      isOk: b.status === 'ok', isStockedOut: b.status === 'stocked-out',
    }))

  const stockList = useMemo(() => {
    const byProduct = {}
    for (const b of batchesWithStatus) {
      byProduct[b.product] ??= { name: b.productName, batches: [] }
      byProduct[b.product].batches.push(b)
    }
    return Object.values(byProduct).map((p, i) => {
      const totalQty = p.batches.reduce((sum, b) => sum + b.qty, 0)
      const expiredQty = p.batches.filter((b) => b.status === 'expired').reduce((sum, b) => sum + b.qty, 0)
      const isExpanded = !!expanded[p.name]
      return {
        num: i + 1, name: p.name, totalQty, expiredQty, eligibleQty: totalQty - expiredQty, batchCount: p.batches.length,
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
      const type = LEDGER_TYPE_LABEL[le.ledger_type] || le.ledger_type
      return {
        product: batchLookup[le.batch]?.productName ?? '', batch: batchLookup[le.batch]?.batchNo ?? '',
        store: storeName, type, timestamp: new Date(le.created_at).toLocaleString(),
        source: le.ref_type ? `${le.ref_type} ${le.ref_id}`.trim() : '—',
        deltaLabel: (delta > 0 ? '+' : '') + delta, deltaColor: delta > 0 ? 'var(--green-700)' : 'var(--red-700)',
        isPositive: le.ledger_type === 'transfer_in' || le.ledger_type === 'sale_void', isNegative: delta < 0, isNeutral: le.ledger_type === 'consumption',
      }
    })

  const stockTabs = STOCK_TAB_DEFS.filter((t) => !t.roles || t.roles.some((r) => roles.includes(r))).map((t) => ({ label: t.label, active: tab === t.key, select: () => setTab(t.key) }))
  const ledgerGroupChips = ['all', 'Transfers', 'Sales', 'Losses', 'Consumption'].map((g) => ({
    label: g === 'all' ? 'All' : g, active: ledgerGroup === g, select: () => setLedgerGroup(g),
  }))

  if (!storeId) return <NoticeBox variant="warning" title="No store selected">Select a store to view stock.</NoticeBox>

  return (
    <div>
      <PageHeader title="Stock" subtitle={`Batches, stock levels and movements at ${storeName}.`} />
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        {stockTabs.map((t) => <Chip key={t.label} selected={t.active} onClick={t.select}>{t.label}</Chip>)}
      </div>

      {tab === 'count' && <StockTake storeId={storeId} storeName={storeName} isManager={isManager} />}
      {tab === 'write-offs' && <WriteOffs storeId={storeId} isManager={isManager} />}

      {batchesError && <NoticeBox variant="error">Could not load stock data.</NoticeBox>}
      {batchesLoading && <NoticeBox variant="info">Loading…</NoticeBox>}

      {!batchesLoading && tab === 'list' && (
        <div className="ds-table-card">
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 640 }}>
            <thead>
              <tr>
                <th style={th('center', 32)}>#</th>
                <th style={th('left')}>Product</th>
                <th style={th('right')}>Total qty</th>
                <th style={th('right')}>Expired qty</th>
                <th style={th('right')}>Eligible qty</th>
                <th style={th('right')}>Batches</th>
                <th style={{ width: 32, borderBottom: '1px solid var(--grey-300)' }} />
              </tr>
            </thead>
            <tbody>
              {stockList.map((p) => (
                <Fragment key={p.name}>
                  <tr onClick={p.toggle} style={{ cursor: 'pointer' }}>
                    <td style={td('center')}>{p.num}</td>
                    <td style={{ ...td('left'), color: 'var(--grey-900)' }}>{p.name}</td>
                    <td style={{ ...td('right'), color: 'var(--grey-900)' }}>{p.totalQty}</td>
                    <td style={td('right')}>{p.expiredQty}</td>
                    <td style={{ ...td('right'), color: 'var(--grey-900)' }}>{p.eligibleQty}</td>
                    <td style={td('right')}>{p.batchCount}</td>
                    <td style={td('center')}><Icon name={p.chevronIcon} size={16} /></td>
                  </tr>
                  {p.expanded && (
                    <tr>
                      <td colSpan={7} style={{ padding: 0, borderBottom: '1px solid var(--grey-300)', background: 'var(--grey-050)' }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                          <tbody>
                            {p.batches.map((pb) => (
                              <tr key={pb.batch}>
                                <td style={{ padding: '8px 16px 8px 48px', fontSize: 13, color: 'var(--grey-700)', fontFamily: 'var(--font-family-mono)' }}>{pb.batch || '—'}</td>
                                <td style={{ padding: '8px 16px', fontSize: 13, color: 'var(--grey-700)' }}>Qty {pb.qty}</td>
                                <td style={{ padding: '8px 16px', fontSize: 13, color: 'var(--grey-700)' }}>{pb.expiry ? `Exp ${pb.expiry}` : 'No expiry'}</td>
                              </tr>
                            ))}
                            <tr>
                              <td colSpan={3} style={{ padding: '8px 16px 12px 48px' }}>
                                <Button size="small" disabled>
                                  <Icon name="add" size={16} /> Add batch
                                </Button>
                              </td>
                            </tr>
                          </tbody>
                        </table>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!batchesLoading && (tab === 'nearly-stocked' || tab === 'stocked-out') && (
        <div className="ds-table-card">
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 520 }}>
            <thead>
              <tr>
                <th style={th('center', 32)}>#</th>
                <th style={th('left')}>Product</th>
                <th style={th('right')}>Qty on hand</th>
                <th style={th('right')}>Reorder level</th>
                <th style={{ width: 44, borderBottom: '1px solid var(--grey-300)' }} />
              </tr>
            </thead>
            <tbody>
              {visibleStockLevels.map((lv) => (
                <tr key={lv.name}>
                  <td style={td('center')}>{lv.num}</td>
                  <td style={{ ...td('left'), color: 'var(--grey-900)' }}>{lv.name}</td>
                  <td style={{ ...td('right'), color: 'var(--grey-900)' }}>{lv.qty}</td>
                  <td style={td('right')}>{lv.reorderLevel}</td>
                  <td style={td('center')}><Icon name="location" size={16} /></td>
                </tr>
              ))}
              {visibleStockLevels.length === 0 && (
                <tr><td colSpan={5} style={{ padding: '32px 16px', textAlign: 'center', fontSize: 14, color: 'var(--fg-subtle)' }}>No products match this view.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {!batchesLoading && (tab === 'nearly-expired' || tab === 'expired') && (
        <div className="ds-table-card">
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 640 }}>
            <thead>
              <tr>
                <th style={th('center', 32)}>#</th>
                <th style={th('left')}>Product</th>
                <th style={th('left')}>Batch</th>
                <th style={th('right')}>Qty</th>
                <th style={th('left')}>Expiry</th>
                <th style={th('left')}>Status</th>
                <th style={{ width: 44, borderBottom: '1px solid var(--grey-300)' }} />
              </tr>
            </thead>
            <tbody>
              {visibleBatches.map((b) => (
                <tr key={b.name + b.batch}>
                  <td style={td('center')}>{b.num}</td>
                  <td style={{ ...td('left'), color: 'var(--grey-900)' }}>{b.name}</td>
                  <td style={{ ...td('left'), fontFamily: 'var(--font-family-mono)' }}>{b.batch || '—'}</td>
                  <td style={{ ...td('right'), color: 'var(--grey-900)' }}>{b.qty}</td>
                  <td style={td('left')}>
                    <div>{b.expiry || '—'}</div>
                    <div style={{ fontSize: 12, color: 'var(--fg-subtle)' }}>{b.daysLabel}</div>
                  </td>
                  <td style={td('left')}>
                    {b.isExpired && <Tag variant="negative">{b.statusLabel}</Tag>}
                    {b.isNearlyExpired && <Tag>{b.statusLabel}</Tag>}
                    {b.isOk && <Tag variant="positive">{b.statusLabel}</Tag>}
                    {b.isStockedOut && <Tag variant="negative" bold>{b.statusLabel}</Tag>}
                  </td>
                  <td style={td('center')}><Icon name="location" size={16} /></td>
                </tr>
              ))}
              {visibleBatches.length === 0 && (
                <tr><td colSpan={7} style={{ padding: '32px 16px', textAlign: 'center', fontSize: 14, color: 'var(--fg-subtle)' }}>No batches match this filter.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {tab === 'ledger' && (
        <>
          <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
            {ledgerGroupChips.map((lg) => <Chip key={lg.label} selected={lg.active} dense onClick={lg.select}>{lg.label}</Chip>)}
          </div>
          {ledgerLoading && <NoticeBox variant="info">Loading…</NoticeBox>}
          {!ledgerLoading && (
            <div className="ds-table-card">
              <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 760 }}>
                <thead>
                  <tr>
                    <th style={th('left')}>Product</th>
                    <th style={th('left')}>Batch</th>
                    <th style={th('left')}>Store</th>
                    <th style={th('right')}>Qty Δ</th>
                    <th style={th('left')}>Type</th>
                    <th style={th('left')}>Timestamp</th>
                    <th style={th('left')}>Source</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleLedger.map((le, i) => (
                    <tr key={i}>
                      <td style={{ ...td('left'), color: 'var(--grey-900)' }}>{le.product}</td>
                      <td style={{ ...td('left'), fontFamily: 'var(--font-family-mono)' }}>{le.batch}</td>
                      <td style={td('left')}>{le.store}</td>
                      <td style={{ ...td('right'), color: le.deltaColor }}>{le.deltaLabel}</td>
                      <td style={td('left')}>
                        {le.isPositive && <Tag variant="positive">{le.type}</Tag>}
                        {le.isNegative && <Tag variant="negative">{le.type}</Tag>}
                        {le.isNeutral && <Tag>{le.type}</Tag>}
                      </td>
                      <td style={{ ...td('left'), fontSize: 13 }}>{le.timestamp}</td>
                      <td style={{ ...td('left'), fontSize: 13, color: 'var(--fg-link)' }}>{le.source}</td>
                    </tr>
                  ))}
                  {visibleLedger.length === 0 && (
                    <tr><td colSpan={7} style={{ padding: '32px 16px', textAlign: 'center', fontSize: 14, color: 'var(--fg-subtle)' }}>No ledger entries match this filter.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function th(align, width) {
  return { width, textAlign: align, fontWeight: 600, fontSize: 11, lineHeight: '16px', textTransform: 'uppercase', letterSpacing: 1.2, color: 'var(--fg-subtle)', padding: align === 'center' ? '12px 8px' : '12px 16px', borderBottom: '1px solid var(--grey-300)' }
}
function td(align) {
  return { padding: align === 'left' ? '14px 16px' : align === 'center' ? '14px 8px' : '14px 16px', borderBottom: '1px solid var(--grey-300)', textAlign: align, fontSize: 14, color: 'var(--grey-700)' }
}
