import { useMemo, useState } from 'react'
import { Button, Input, NoticeBox, Select, Tag } from '../../components/ds/index.js'
import { useApi } from '../../hooks/useApi.js'
import { listAllProducts, listAllUnitsOfMeasure } from '../../api/catalog.js'
import { createPrice, deletePrice, listAllPrices, updatePrice } from '../../api/pricing.js'
import { listAllStores } from '../../api/core.js'
import { fmt } from '../../appData.js'
import { apiErrorText } from '../../lib/apiError.js'
import { t, useT } from '../../i18n/index.js'
import { Table } from './FormParts.jsx'
import { VAT_LABEL, omit, introStyle } from './shared.js'

export default function PricingPanel({ entity }) {
  useT()
  const perStore = entity.price_mode === 'store'
  const { data: stores } = useApi(() => (perStore ? listAllStores() : null), [perStore])
  const [storeId, setStoreId] = useState('')
  const activeStore = perStore ? (storeId || stores?.[0]?.id || '') : null
  const { data: products } = useApi(() => listAllProducts(), [])
  const { data: prices, refetch } = useApi(() => listAllPrices(), [])
  const [filter, setFilter] = useState('')
  const [editing, setEditing] = useState({}) // productId -> draft string
  const [error, setError] = useState('')

  const priceByProduct = useMemo(() => {
    const map = {}
    for (const p of prices ?? []) if ((p.store ?? null) === activeStore && !p.uom) map[p.product] = p
    return map
  }, [prices, activeStore])
  const unitPricesByProduct = useMemo(() => {
    const map = {}
    for (const p of prices ?? []) if ((p.store ?? null) === activeStore && p.uom) (map[p.product] ??= []).push(p)
    return map
  }, [prices, activeStore])
  const { data: uoms } = useApi(() => listAllUnitsOfMeasure(), [])
  const q = filter.trim().toLowerCase()
  const visible = (products ?? []).filter((p) => !q || p.name.toLowerCase().includes(q))
  const unpriced = (products ?? []).filter((p) => !priceByProduct[p.id]).length

  async function save(product) {
    setError('')
    const value = String(editing[product.id]).replace(/[,\s]/g, '')
    if (!(Number(value) > 0)) { setError(t('Enter a price above zero.')); return }
    try {
      const existing = priceByProduct[product.id]
      if (existing) await updatePrice(existing.id, { unit_price: value })
      else await createPrice({ entity: entity.id, store: activeStore, product: product.id, unit_price: value })
      setEditing((e) => omit(e, product.id))
      refetch()
    } catch (err) {
      setError(apiErrorText(err, t('Could not save the price.')))
    }
  }

  return (
    <>
      <p style={introStyle}>
        {t('Shelf prices, including VAT, per stock unit. Add a price for another unit (e.g. a crate) to sell in that unit too. The till always charges the price set here, or a running promotion’s price — cashiers cannot change it.')}
        {' '}{perStore ? t('Your shop prices each store separately.') : t('One price list applies to every store.')}
      </p>
      {unpriced > 0 && <NoticeBox variant="warning" style={{ marginBottom: 12 }}>{t(unpriced === 1 ? '{n} product has no price and cannot be sold yet.' : '{n} products have no price and cannot be sold yet.', { n: unpriced })}</NoticeBox>}
      {error && <NoticeBox variant="error" style={{ marginBottom: 12 }}>{error}</NoticeBox>}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        {perStore && <Select value={activeStore} onChange={(e) => setStoreId(e.target.value)} options={(stores ?? []).map((s) => ({ value: s.id, label: s.name }))} style={{ width: 240 }} />}
        <div style={{ flex: 1, minWidth: 200 }}><Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder={t('Filter products')} prefixIcon="search" /></div>
      </div>
      <Table
        headers={['Product', 'VAT', 'Price per stock unit', '', 'Other selling units']}
        rows={visible.map((p) => {
          const price = priceByProduct[p.id]
          const draft = editing[p.id]
          return [
            p.name, t(VAT_LABEL[p.vat_class]),
            draft !== undefined
              ? <Input key="input" value={draft} onChange={(e) => setEditing({ ...editing, [p.id]: e.target.value })} style={{ width: 140 }} />
              : (price ? fmt(Number(price.unit_price)) : <Tag key="unset" variant="negative">{t('Not set')}</Tag>),
            draft !== undefined
              ? <div key="actions" style={{ display: 'flex', gap: 4 }}><Button size="small" variant="primary" onClick={() => save(p)}>{t('Save')}</Button><Button size="small" onClick={() => setEditing((e) => omit(e, p.id))}>{t('Cancel')}</Button></div>
              : <Button key="edit" size="small" onClick={() => setEditing({ ...editing, [p.id]: price ? String(Number(price.unit_price)) : '' })}>{price ? t('Edit') : t('Set price')}</Button>,
            <UnitPrices
              key="units" product={p} prices={unitPricesByProduct[p.id] ?? []} uoms={uoms ?? []}
              entity={entity} store={activeStore} onChanged={refetch} onError={setError}
            />,
          ]
        })}
        empty={products ? t('No products yet — add them under Products.') : t('Loading…')}
      />
    </>
  )
}

/** Prices for selling a product in units other than its stock unit,
 * e.g. "Crate of 24: TZS 21,000" for a product stocked in bottles. */
function UnitPrices({ product, prices, uoms, entity, store, onChanged, onError }) {
  useT()
  const [adding, setAdding] = useState(null) // {uom, price}
  const choices = uoms.filter((u) => u.id !== product.uom && !prices.some((p) => p.uom === u.id))

  async function add() {
    const value = String(adding.price).replace(/[,\s]/g, '')
    if (!adding.uom || !(Number(value) > 0)) { onError(t('Choose a unit and enter a price above zero.')); return }
    try {
      await createPrice({ entity: entity.id, store, product: product.id, uom: adding.uom, unit_price: value })
      setAdding(null)
      onChanged()
    } catch (err) {
      onError(apiErrorText(err, t('Could not save the price.')))
    }
  }
  async function remove(price) {
    try {
      await deletePrice(price.id)
      onChanged()
    } catch (err) {
      onError(apiErrorText(err, t('Could not remove the price.')))
    }
  }

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
      {prices.map((p) => (
        <span key={p.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, background: 'var(--grey-100)', borderRadius: 'var(--radius-sm)', padding: '2px 6px', fontSize: 13 }}>
          {p.uom_name}: {fmt(Number(p.unit_price))}
          <button onClick={() => remove(p)} title={t('Remove')} style={{ border: 0, background: 'none', cursor: 'pointer', color: 'var(--status-error)', padding: 0 }}>×</button>
        </span>
      ))}
      {adding
        ? (
          <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
            <Select value={adding.uom} onChange={(e) => setAdding({ ...adding, uom: e.target.value })} options={[{ value: '', label: t('Unit…') }, ...choices.map((u) => ({ value: u.id, label: u.name }))]} style={{ width: 130 }} />
            <Input value={adding.price} onChange={(e) => setAdding({ ...adding, price: e.target.value })} placeholder={t('Price')} style={{ width: 90 }} />
            <Button size="small" variant="primary" onClick={add}>{t('Add')}</Button>
            <Button size="small" onClick={() => setAdding(null)}>{t('Cancel')}</Button>
          </span>
        )
        : choices.length > 0 && <Button size="small" onClick={() => setAdding({ uom: '', price: '' })}>+ {t('Unit')}</Button>}
    </div>
  )
}
