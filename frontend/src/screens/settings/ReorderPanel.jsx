import { useMemo, useState } from 'react'
import { Button, Input, NoticeBox, Select } from '../../components/ds/index.js'
import { useApi } from '../../hooks/useApi.js'
import { listAllProducts } from '../../api/catalog.js'
import { createStoreProduct, listAllStoreProducts, updateStoreProduct } from '../../api/inventory.js'
import { listAllStores } from '../../api/core.js'
import { apiErrorText } from '../../lib/apiError.js'
import { t, useT } from '../../i18n/index.js'
import { Table } from './FormParts.jsx'
import { omit, introStyle } from './shared.js'

export default function ReorderPanel() {
  useT()
  const { data: stores } = useApi(() => listAllStores(), [])
  const [storeId, setStoreId] = useState('')
  const activeStore = storeId || stores?.[0]?.id || ''
  const { data: products } = useApi(() => listAllProducts(), [])
  const { data: storeProducts, refetch } = useApi(() => (activeStore ? listAllStoreProducts({ store: activeStore }) : null), [activeStore])
  const [editing, setEditing] = useState({})
  const [filter, setFilter] = useState('')
  const [error, setError] = useState('')

  const spByProduct = useMemo(() => Object.fromEntries((storeProducts ?? []).map((sp) => [sp.product, sp])), [storeProducts])
  const q = filter.trim().toLowerCase()
  const visible = (products ?? []).filter((p) => !q || p.name.toLowerCase().includes(q))

  async function save(product) {
    setError('')
    const value = String(editing[product.id]).replace(/[,\s]/g, '')
    if (!(Number(value) >= 0) || value === '') { setError(t('Enter a number of units (0 or more).')); return }
    try {
      const sp = spByProduct[product.id]
      if (sp) await updateStoreProduct(sp.id, { reorder_level: value })
      else await createStoreProduct({ store: activeStore, product: product.id, reorder_level: value, enabled: true })
      setEditing((e) => omit(e, product.id))
      refetch()
    } catch (err) {
      setError(apiErrorText(err, t('Could not save the warning level.')))
    }
  }

  return (
    <>
      <p style={introStyle}>{t('When the stock you can sell falls to this level, the product shows as running low on the dashboard and in reports.')}</p>
      {error && <NoticeBox variant="error" style={{ marginBottom: 12 }}>{error}</NoticeBox>}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        <Select value={activeStore} onChange={(e) => setStoreId(e.target.value)} options={(stores ?? []).map((s) => ({ value: s.id, label: s.name }))} style={{ width: 240 }} />
        <div style={{ flex: 1, minWidth: 200 }}><Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder={t('Filter products')} prefixIcon="search" /></div>
      </div>
      <Table
        headers={['Product', 'Warn at', '']}
        rows={visible.map((p) => {
          const sp = spByProduct[p.id]
          const draft = editing[p.id]
          return [
            p.name,
            draft !== undefined
              ? <Input key="input" value={draft} onChange={(e) => setEditing({ ...editing, [p.id]: e.target.value })} style={{ width: 120 }} />
              : (sp ? Number(sp.reorder_level) : '—'),
            draft !== undefined
              ? <div key="actions" style={{ display: 'flex', gap: 4 }}><Button size="small" variant="primary" onClick={() => save(p)}>{t('Save')}</Button><Button size="small" onClick={() => setEditing((e) => omit(e, p.id))}>{t('Cancel')}</Button></div>
              : <Button key="edit" size="small" onClick={() => setEditing({ ...editing, [p.id]: sp ? String(Number(sp.reorder_level)) : '' })}>{sp ? t('Edit') : t('Set')}</Button>,
          ]
        })}
        empty={products ? t('No products yet.') : t('Loading…')}
      />
    </>
  )
}
