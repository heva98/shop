import { Children, useMemo, useState } from 'react'
import { Button, Card, Checkbox, Field, Icon, Input, NoticeBox, PageHeader, Select, SubNav, Switch, Tag } from '../components/ds/index.js'
import { useApi } from '../hooks/useApi.js'
import {
  createCategory, createProduct, createUnitOfMeasure, listAllCategories, listAllProducts,
  listAllUnitsOfMeasure, updateProduct, updateUnitOfMeasure,
} from '../api/catalog.js'
import { createSupplier, listAllSuppliers, updateSupplier } from '../api/receiving.js'
import {
  createPrice, createPromotion, deletePrice, deletePromotion, listAllPrices, listAllPromotions, updatePrice, updatePromotion,
} from '../api/pricing.js'
import { createStoreProduct, listAllStoreProducts, updateStoreProduct } from '../api/inventory.js'
import { listPaymentMethods, updatePaymentMethod } from '../api/payments.js'
import { listAllStores } from '../api/core.js'
import { fmt } from '../appData.js'
import { apiErrorText } from '../lib/apiError.js'
import ImportPanel from './SettingsImport.jsx'
import NotificationsPanel from './SettingsNotifications.jsx'
import FeaturesPanel from './SettingsFeatures.jsx'

const TABS = [
  { key: 'products', label: 'Products' },
  { key: 'uom', label: 'Units of measure' },
  { key: 'suppliers', label: 'Suppliers' },
  { key: 'pricing', label: 'Selling prices' },
  { key: 'promotions', label: 'Promotions' },
  { key: 'reorder', label: 'Reorder levels' },
  { key: 'payment-methods', label: 'Payment methods' },
  { key: 'notifications', label: 'Notifications' },
  { key: 'import', label: 'Import from Excel' },
  { key: 'features', label: 'Features' },
]
const VAT_OPTIONS = [
  { value: 'exempt', label: 'Exempt' }, { value: 'zero_rated', label: 'Zero-rated' }, { value: 'standard', label: 'Standard (18%)' },
]
const VAT_LABEL = Object.fromEntries(VAT_OPTIONS.map((o) => [o.value, o.label]))

export default function Settings({ entity }) {
  const [tab, setTab] = useState('products')
  return (
    <div>
      <PageHeader title="Settings" subtitle="Catalogue, suppliers, pricing and features for your entity." />
      <div className="ds-subnav-layout">
        <SubNav label="Settings sections" items={TABS.map((t) => ({ ...t, active: tab === t.key, select: () => setTab(t.key) }))} />
        <div className="ds-subnav-content">
          {tab === 'products' && <ProductsPanel entity={entity} />}
          {tab === 'uom' && <UomPanel entity={entity} />}
          {tab === 'suppliers' && <SuppliersPanel entity={entity} />}
          {tab === 'pricing' && <PricingPanel entity={entity} />}
          {tab === 'reorder' && <ReorderPanel />}
          {tab === 'payment-methods' && <PaymentMethodsPanel />}
          {tab === 'notifications' && <NotificationsPanel />}
          {tab === 'import' && <ImportPanel entity={entity} />}
          {tab === 'promotions' && <PromotionsPanel entity={entity} />}
          {tab === 'features' && <FeaturesPanel />}
        </div>
      </div>
    </div>
  )
}

/** Shared add/edit form state: `save` gets the draft and returns a promise. */
function useForm(initial) {
  const [draft, setDraft] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  return {
    draft, error, busy,
    open: (values) => { setDraft({ ...initial, ...values }); setError('') },
    close: () => setDraft(null),
    set: (field) => (e) => setDraft((d) => ({ ...d, [field]: e?.target ? (e.target.type === 'checkbox' ? e.target.checked : e.target.value) : e })),
    toggle: (field) => () => setDraft((d) => ({ ...d, [field]: !d[field] })),
    async submit(save, onDone) {
      setBusy(true); setError('')
      try {
        await save(draft)
        setDraft(null)
        onDone?.()
      } catch (err) {
        setError(apiErrorText(err, 'Could not save.'))
      } finally { setBusy(false) }
    },
  }
}

function ProductsPanel({ entity }) {
  const { data: products, refetch } = useApi(() => listAllProducts(), [])
  const { data: categories, refetch: refetchCategories } = useApi(() => listAllCategories(), [])
  const { data: uoms } = useApi(() => listAllUnitsOfMeasure(), [])
  const [filter, setFilter] = useState('')
  const form = useForm({
    name: '', category: '', brand: '', size: '', uom: '', vat_class: 'standard', barcode: '', tracks_expiry: false,
  })
  const categoryForm = useForm({ name: '', short_name: '', description: '' })

  const categoryName = useMemo(() => Object.fromEntries((categories ?? []).map((c) => [c.id, c.name])), [categories])
  const uomName = useMemo(() => Object.fromEntries((uoms ?? []).map((u) => [u.id, u.name])), [uoms])
  const q = filter.trim().toLowerCase()
  const visible = (products ?? []).filter((p) => !q || p.name.toLowerCase().includes(q) || p.barcode === filter.trim()
    || p.brand.toLowerCase().includes(q) || (categoryName[p.category] ?? '').toLowerCase().includes(q))

  function save(d) {
    const body = { ...d, entity: entity.id, category: d.category || null }
    return d.id ? updateProduct(d.id, body) : createProduct(body)
  }

  return (
    <>
      <p style={introStyle}>
        The products your shop sells. Scan the barcode on the pack so the till can find it by scanning. Mark goods that
        expire (food, drinks, cosmetics) as perishable: receiving then asks for the expiry date and expired stock cannot be sold.
        A product also needs a selling price before it can be sold.
      </p>
      {(uoms ?? []).length === 0 && <NoticeBox variant="warning" style={{ marginBottom: 16 }}>Add a unit of measure first (e.g. Piece, Packet, Bottle).</NoticeBox>}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        <Button variant="primary" onClick={() => form.open({ uom: uoms?.[0]?.id ?? '' })} disabled={(uoms ?? []).length === 0}><Icon name="add" size={16} /> Add product</Button>
        <Button onClick={() => categoryForm.open()}><Icon name="add" size={16} /> Add category</Button>
        <div style={{ flex: 1, minWidth: 200 }}><Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter by name, brand, category or barcode" prefixIcon="search" /></div>
      </div>

      {categoryForm.draft && (
        <Card style={{ marginBottom: 12 }}>
          <div style={gridStyle}>
            <Field label="Category" required><Input value={categoryForm.draft.name} onChange={categoryForm.set('name')} placeholder="e.g. Beverages" /></Field>
            <Field label="Short name"><Input value={categoryForm.draft.short_name} onChange={categoryForm.set('short_name')} placeholder="e.g. BEV" /></Field>
            <Field label="Description"><Input value={categoryForm.draft.description} onChange={categoryForm.set('description')} placeholder="e.g. Soft drinks, water, juice" /></Field>
          </div>
          <FormActions form={categoryForm} onSave={() => categoryForm.submit((d) => createCategory({ ...d, entity: entity.id }), refetchCategories)} disabled={!categoryForm.draft.name.trim()} />
        </Card>
      )}

      {form.draft && (
        <Card style={{ marginBottom: 12 }}>
          <div style={gridStyle}>
            <Field label="Product name" required><Input value={form.draft.name} onChange={form.set('name')} placeholder="e.g. Sugar 1kg" /></Field>
            <Field label="Barcode"><Input value={form.draft.barcode ?? ''} onChange={form.set('barcode')} placeholder="Scan or type" prefixIcon="barcode" /></Field>
            <Field label="Category">
              <Select value={form.draft.category ?? ''} onChange={form.set('category')} options={[{ value: '', label: '—' }, ...(categories ?? []).map((c) => ({ value: c.id, label: c.name }))]} />
            </Field>
            <Field label="Brand"><Input value={form.draft.brand} onChange={form.set('brand')} placeholder="e.g. Kilombero" /></Field>
            <Field label="Size"><Input value={form.draft.size} onChange={form.set('size')} placeholder="e.g. 1 kg, 500 ml" /></Field>
            <Field label="Stock unit (smallest unit sold)" required>
              <Select value={form.draft.uom} onChange={form.set('uom')} options={(uoms ?? []).map((u) => ({ value: u.id, label: u.name }))} />
            </Field>
            <Field label="VAT"><Select value={form.draft.vat_class} onChange={form.set('vat_class')} options={VAT_OPTIONS} /></Field>
          </div>
          <p style={{ fontSize: 12, color: 'var(--fg-subtle)', margin: '8px 0 0' }}>
            Stock is counted in the stock unit. Receiving converts supplier packs into it, and you can set extra selling units
            (e.g. a crate or a dozen) with their own price under Selling prices.
          </p>
          <div style={{ display: 'flex', gap: 24, margin: '12px 0' }}>
            <Checkbox checked={form.draft.tracks_expiry} onChange={form.toggle('tracks_expiry')} label="Perishable — has an expiry date" />
          </div>
          <FormActions form={form} onSave={() => form.submit(save, refetch)} disabled={!form.draft.name.trim() || !form.draft.uom} />
        </Card>
      )}

      <Table
        headers={['Product', 'Category', 'Unit', 'VAT', '', '']}
        rows={visible.map((p) => [
          <><div style={{ color: 'var(--grey-900)' }}>{p.name}</div><div style={{ fontSize: 12 }}>{[p.brand, p.size, p.barcode].filter(Boolean).join(' · ')}</div></>,
          categoryName[p.category] ?? '—', uomName[p.uom] ?? '', VAT_LABEL[p.vat_class],
          p.tracks_expiry ? <Tag key="exp" variant="neutral">Perishable</Tag> : '',
          <Button key="edit" size="small" onClick={() => form.open(p)}>Edit</Button>,
        ])}
        empty={products ? 'No products yet.' : 'Loading…'}
      />
    </>
  )
}

function UomPanel({ entity }) {
  const { data: uoms, refetch } = useApi(() => listAllUnitsOfMeasure(), [])
  const form = useForm({ name: '', description: '', unit_value: '1' })
  const save = (d) => (d.id ? updateUnitOfMeasure(d.id, d) : createUnitOfMeasure({ ...d, entity: entity.id }))
  return (
    <>
      <p style={introStyle}>The units products are sold and received in, e.g. Piece, Packet, Dozen (12 pieces), Crate of 24.</p>
      <Button variant="primary" onClick={() => form.open()} style={{ marginBottom: 12 }}><Icon name="add" size={16} /> Add unit</Button>
      {form.draft && (
        <Card style={{ marginBottom: 12 }}>
          <div style={gridStyle}>
            <Field label="Name" required><Input value={form.draft.name} onChange={form.set('name')} placeholder="e.g. Crate of 24" /></Field>
            <Field label="Description"><Input value={form.draft.description} onChange={form.set('description')} placeholder="e.g. Crate of 24 bottles" /></Field>
            <Field label="Units inside" required><Input value={form.draft.unit_value} onChange={form.set('unit_value')} /></Field>
          </div>
          <FormActions form={form} onSave={() => form.submit(save, refetch)} disabled={!form.draft.name.trim()} />
        </Card>
      )}
      <Table
        headers={['Name', 'Description', 'Units inside', '']}
        rows={(uoms ?? []).map((u) => [u.name, u.description || '—', Number(u.unit_value), <Button key="edit" size="small" onClick={() => form.open(u)}>Edit</Button>])}
        empty={uoms ? 'No units yet.' : 'Loading…'}
      />
    </>
  )
}

function SuppliersPanel({ entity }) {
  const { data: suppliers, refetch } = useApi(() => listAllSuppliers(), [])
  const form = useForm({ name: '', description: '', location: '', email: '', phone: '', payment_terms_days: '0' })
  const save = (d) => (d.id ? updateSupplier(d.id, d) : createSupplier({ ...d, entity: entity.id }))
  return (
    <>
      <p style={introStyle}>Wholesalers and distributors you buy from. They appear on receiving invoices and in the purchases report.</p>
      <Button variant="primary" onClick={() => form.open()} style={{ marginBottom: 12 }}><Icon name="add" size={16} /> Add supplier</Button>
      {form.draft && (
        <Card style={{ marginBottom: 12 }}>
          <div style={gridStyle}>
            <Field label="Name" required><Input value={form.draft.name} onChange={form.set('name')} /></Field>
            <Field label="Description"><Input value={form.draft.description} onChange={form.set('description')} /></Field>
            <Field label="Location"><Input value={form.draft.location} onChange={form.set('location')} /></Field>
            <Field label="Phone"><Input value={form.draft.phone} onChange={form.set('phone')} /></Field>
            <Field label="Email"><Input value={form.draft.email} onChange={form.set('email')} /></Field>
            <Field label="Credit (days to pay)"><Input value={String(form.draft.payment_terms_days ?? 0)} onChange={form.set('payment_terms_days')} /></Field>
          </div>
          <FormActions form={form} onSave={() => form.submit(save, refetch)} disabled={!form.draft.name.trim()} />
        </Card>
      )}
      <Table
        headers={['Name', 'Location', 'Phone', 'Email', 'Credit', '']}
        rows={(suppliers ?? []).map((s) => [s.name, s.location || '—', s.phone || '—', s.email || '—',
          s.payment_terms_days ? `${s.payment_terms_days} days` : 'Pay on delivery', <Button key="edit" size="small" onClick={() => form.open(s)}>Edit</Button>])}
        empty={suppliers ? 'No suppliers yet.' : 'Loading…'}
      />
    </>
  )
}

function PricingPanel({ entity }) {
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
    if (!(Number(value) > 0)) { setError('Enter a price above zero.'); return }
    try {
      const existing = priceByProduct[product.id]
      if (existing) await updatePrice(existing.id, { unit_price: value })
      else await createPrice({ entity: entity.id, store: activeStore, product: product.id, unit_price: value })
      setEditing((e) => omit(e, product.id))
      refetch()
    } catch (err) {
      setError(apiErrorText(err, 'Could not save the price.'))
    }
  }

  return (
    <>
      <p style={introStyle}>
        Shelf prices, including VAT, per stock unit. Add a price for another unit (e.g. a crate) to sell in that unit too.
        The till always charges the price set here, or a running promotion&rsquo;s price — cashiers cannot change it.
        {perStore ? ' Your shop prices each store separately.' : ' One price list applies to every store.'}
      </p>
      {unpriced > 0 && <NoticeBox variant="warning" style={{ marginBottom: 12 }}>{unpriced} product{unpriced === 1 ? ' has' : 's have'} no price and cannot be sold yet.</NoticeBox>}
      {error && <NoticeBox variant="error" style={{ marginBottom: 12 }}>{error}</NoticeBox>}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        {perStore && <Select value={activeStore} onChange={(e) => setStoreId(e.target.value)} options={(stores ?? []).map((s) => ({ value: s.id, label: s.name }))} style={{ width: 240 }} />}
        <div style={{ flex: 1, minWidth: 200 }}><Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter products" prefixIcon="search" /></div>
      </div>
      <Table
        headers={['Product', 'VAT', 'Price per stock unit', '', 'Other selling units']}
        rows={visible.map((p) => {
          const price = priceByProduct[p.id]
          const draft = editing[p.id]
          return [
            p.name, VAT_LABEL[p.vat_class],
            draft !== undefined
              ? <Input key="input" value={draft} onChange={(e) => setEditing({ ...editing, [p.id]: e.target.value })} style={{ width: 140 }} />
              : (price ? fmt(Number(price.unit_price)) : <Tag key="unset" variant="negative">Not set</Tag>),
            draft !== undefined
              ? <div key="actions" style={{ display: 'flex', gap: 4 }}><Button size="small" variant="primary" onClick={() => save(p)}>Save</Button><Button size="small" onClick={() => setEditing((e) => omit(e, p.id))}>Cancel</Button></div>
              : <Button key="edit" size="small" onClick={() => setEditing({ ...editing, [p.id]: price ? String(Number(price.unit_price)) : '' })}>{price ? 'Edit' : 'Set price'}</Button>,
            <UnitPrices
              key="units" product={p} prices={unitPricesByProduct[p.id] ?? []} uoms={uoms ?? []}
              entity={entity} store={activeStore} onChanged={refetch} onError={setError}
            />,
          ]
        })}
        empty={products ? 'No products yet — add them under Products.' : 'Loading…'}
      />
    </>
  )
}

function ReorderPanel() {
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
    if (!(Number(value) >= 0) || value === '') { setError('Enter a number of units (0 or more).'); return }
    try {
      const sp = spByProduct[product.id]
      if (sp) await updateStoreProduct(sp.id, { reorder_level: value })
      else await createStoreProduct({ store: activeStore, product: product.id, reorder_level: value, enabled: true })
      setEditing((e) => omit(e, product.id))
      refetch()
    } catch (err) {
      setError(apiErrorText(err, 'Could not save the reorder level.'))
    }
  }

  return (
    <>
      <p style={introStyle}>When unexpired stock falls to the reorder level, the product shows as low on stock on the dashboard and in reports.</p>
      {error && <NoticeBox variant="error" style={{ marginBottom: 12 }}>{error}</NoticeBox>}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        <Select value={activeStore} onChange={(e) => setStoreId(e.target.value)} options={(stores ?? []).map((s) => ({ value: s.id, label: s.name }))} style={{ width: 240 }} />
        <div style={{ flex: 1, minWidth: 200 }}><Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter products" prefixIcon="search" /></div>
      </div>
      <Table
        headers={['Product', 'Reorder level', '']}
        rows={visible.map((p) => {
          const sp = spByProduct[p.id]
          const draft = editing[p.id]
          return [
            p.name,
            draft !== undefined
              ? <Input key="input" value={draft} onChange={(e) => setEditing({ ...editing, [p.id]: e.target.value })} style={{ width: 120 }} />
              : (sp ? Number(sp.reorder_level) : '—'),
            draft !== undefined
              ? <div key="actions" style={{ display: 'flex', gap: 4 }}><Button size="small" variant="primary" onClick={() => save(p)}>Save</Button><Button size="small" onClick={() => setEditing((e) => omit(e, p.id))}>Cancel</Button></div>
              : <Button key="edit" size="small" onClick={() => setEditing({ ...editing, [p.id]: sp ? String(Number(sp.reorder_level)) : '' })}>{sp ? 'Edit' : 'Set'}</Button>,
          ]
        })}
        empty={products ? 'No products yet.' : 'Loading…'}
      />
    </>
  )
}

const PAYMENT_HELP = {
  cash: 'Always on. Counted in the drawer at shift close.',
  mobile_money: 'M-Pesa, Mixx by Yas, Airtel Money, HaloPesa. The cashier enters the transaction reference from the SMS.',
  bank_transfer: 'Direct bank payments. The cashier enters the bank reference.',
}

function PaymentMethodsPanel() {
  const { data, refetch } = useApi(() => listPaymentMethods(), [])
  const [error, setError] = useState('')
  async function toggle(m) {
    setError('')
    try {
      await updatePaymentMethod(m.id, { is_active: !m.is_active })
      refetch()
    } catch (err) {
      setError(apiErrorText(err, 'Could not update the payment method.'))
    }
  }
  return (
    <>
      <p style={introStyle}>Which payment methods the till offers.</p>
      {error && <NoticeBox variant="error" style={{ marginBottom: 12 }}>{error}</NoticeBox>}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 640 }}>
        {(data?.results ?? []).map((m) => (
          <Card key={m.id}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 16 }}>
              <div>
                <div style={{ fontSize: 14, color: 'var(--grey-900)' }}>{m.name}</div>
                <div style={{ fontSize: 13, color: 'var(--fg-subtle)' }}>{PAYMENT_HELP[m.implementation]}</div>
              </div>
              <Switch on={m.is_active} onChange={() => toggle(m)} disabled={m.implementation === 'cash'} />
            </div>
          </Card>
        ))}
      </div>
    </>
  )
}

const PROMOTION_STATUS = (p) => {
  const today = new Date().toISOString().slice(0, 10)
  if (!p.is_active) return ['neutral', 'Switched off']
  if (p.ends_on < today) return ['neutral', 'Ended']
  if (p.starts_on > today) return [undefined, 'Starts soon']
  return ['positive', 'Running']
}

function PromotionsPanel({ entity }) {
  const { data: promotions, refetch } = useApi(() => listAllPromotions(), [])
  const { data: products } = useApi(() => listAllProducts(), [])
  const { data: uoms } = useApi(() => listAllUnitsOfMeasure(), [])
  const { data: stores } = useApi(() => (entity.store_mode === 'multi' ? listAllStores() : null), [entity.store_mode])
  const today = new Date().toISOString().slice(0, 10)
  const form = useForm({ name: '', product: '', uom: '', store: '', promo_price: '', starts_on: today, ends_on: today, is_active: true })
  const [error, setError] = useState('')

  function save(d) {
    const body = {
      name: d.name, product: d.product, uom: d.uom || null, store: d.store || null,
      promo_price: String(d.promo_price).replace(/[,\s]/g, ''), starts_on: d.starts_on, ends_on: d.ends_on, is_active: d.is_active,
    }
    return d.id ? updatePromotion(d.id, body) : createPromotion(body)
  }
  async function remove(promotion) {
    if (!window.confirm(`Remove the promotion "${promotion.name}"? To end it early but keep the record, switch it off instead.`)) return
    setError('')
    try {
      await deletePromotion(promotion.id)
      refetch()
    } catch (err) {
      setError(apiErrorText(err, 'Could not remove the promotion.'))
    }
  }

  return (
    <>
      <p style={introStyle}>
        Time-limited offer prices. While a promotion runs, the till charges its price instead of the regular one,
        and receipts and reports show what was really charged. A promotion for one store wins over one for every store.
      </p>
      <Button variant="primary" onClick={() => form.open({ product: products?.[0]?.id ?? '' })} style={{ marginBottom: 12 }} disabled={!products?.length}>
        <Icon name="add" size={16} /> Add promotion
      </Button>
      {error && <NoticeBox variant="error" style={{ marginBottom: 12 }}>{error}</NoticeBox>}
      {form.draft && (
        <Card style={{ marginBottom: 12 }}>
          <div style={gridStyle}>
            <Field label="Name" required><Input value={form.draft.name} onChange={form.set('name')} placeholder="e.g. Weekend soda offer" /></Field>
            <Field label="Product" required>
              <Select value={form.draft.product} onChange={form.set('product')} options={(products ?? []).map((p) => ({ value: p.id, label: p.name }))} />
            </Field>
            <Field label="Unit">
              <Select value={form.draft.uom ?? ''} onChange={form.set('uom')} options={[{ value: '', label: 'Its stock unit' }, ...(uoms ?? []).map((u) => ({ value: u.id, label: u.name }))]} />
            </Field>
            {stores && (
              <Field label="Store">
                <Select value={form.draft.store ?? ''} onChange={form.set('store')} options={[{ value: '', label: 'Every store' }, ...stores.map((st) => ({ value: st.id, label: st.name }))]} />
              </Field>
            )}
            <Field label="Offer price (TZS)" required><Input value={String(form.draft.promo_price)} onChange={form.set('promo_price')} /></Field>
            <Field label="From" required><Input type="date" value={form.draft.starts_on} onChange={form.set('starts_on')} /></Field>
            <Field label="To (inclusive)" required><Input type="date" value={form.draft.ends_on} onChange={form.set('ends_on')} /></Field>
          </div>
          <div style={{ margin: '12px 0' }}>
            <Checkbox checked={form.draft.is_active} onChange={form.toggle('is_active')} label="Switched on" />
          </div>
          <FormActions
            form={form} onSave={() => form.submit(save, refetch)}
            disabled={!form.draft.name.trim() || !form.draft.product || !(Number(String(form.draft.promo_price).replace(/[,\s]/g, '')) > 0)}
          />
        </Card>
      )}
      <Table
        headers={['Promotion', 'Store', 'Price', 'Dates', 'Status', '']}
        rows={(promotions ?? []).map((pr) => {
          const [variant, label] = PROMOTION_STATUS(pr)
          return [
            <><div style={{ color: 'var(--grey-900)' }}>{pr.name}</div><div style={{ fontSize: 12 }}>{pr.product_name}{pr.uom_name ? ` · per ${pr.uom_name}` : ''}</div></>,
            pr.store_name ?? 'Every store',
            <>{fmt(Number(pr.promo_price))}{pr.regular_price && <div style={{ fontSize: 12, textDecoration: 'line-through' }}>{fmt(Number(pr.regular_price))}</div>}</>,
            `${new Date(pr.starts_on).toLocaleDateString()} – ${new Date(pr.ends_on).toLocaleDateString()}`,
            <Tag key="status" variant={variant}>{label}</Tag>,
            <div key="actions" style={{ display: 'flex', gap: 4 }}>
              <Button size="small" onClick={() => form.open({ ...pr, uom: pr.uom ?? '', store: pr.store ?? '', promo_price: String(Number(pr.promo_price)) })}>Edit</Button>
              <Button size="small" variant="destructive" onClick={() => remove(pr)}>Remove</Button>
            </div>,
          ]
        })}
        empty={promotions ? 'No promotions yet.' : 'Loading…'}
      />
    </>
  )
}

/** Prices for selling a product in units other than its stock unit,
 * e.g. "Crate of 24: TZS 21,000" for a product stocked in bottles. */
function UnitPrices({ product, prices, uoms, entity, store, onChanged, onError }) {
  const [adding, setAdding] = useState(null) // {uom, price}
  const choices = uoms.filter((u) => u.id !== product.uom && !prices.some((p) => p.uom === u.id))

  async function add() {
    const value = String(adding.price).replace(/[,\s]/g, '')
    if (!adding.uom || !(Number(value) > 0)) { onError('Choose a unit and enter a price above zero.'); return }
    try {
      await createPrice({ entity: entity.id, store, product: product.id, uom: adding.uom, unit_price: value })
      setAdding(null)
      onChanged()
    } catch (err) {
      onError(apiErrorText(err, 'Could not save the price.'))
    }
  }
  async function remove(price) {
    try {
      await deletePrice(price.id)
      onChanged()
    } catch (err) {
      onError(apiErrorText(err, 'Could not remove the price.'))
    }
  }

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
      {prices.map((p) => (
        <span key={p.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, background: 'var(--grey-100)', borderRadius: 'var(--radius-sm)', padding: '2px 6px', fontSize: 13 }}>
          {p.uom_name}: {fmt(Number(p.unit_price))}
          <button onClick={() => remove(p)} title="Remove" style={{ border: 0, background: 'none', cursor: 'pointer', color: 'var(--status-error)', padding: 0 }}>×</button>
        </span>
      ))}
      {adding
        ? (
          <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
            <Select value={adding.uom} onChange={(e) => setAdding({ ...adding, uom: e.target.value })} options={[{ value: '', label: 'Unit…' }, ...choices.map((u) => ({ value: u.id, label: u.name }))]} style={{ width: 130 }} />
            <Input value={adding.price} onChange={(e) => setAdding({ ...adding, price: e.target.value })} placeholder="Price" style={{ width: 90 }} />
            <Button size="small" variant="primary" onClick={add}>Add</Button>
            <Button size="small" onClick={() => setAdding(null)}>Cancel</Button>
          </span>
        )
        : choices.length > 0 && <Button size="small" onClick={() => setAdding({ uom: '', price: '' })}>+ Unit</Button>}
    </div>
  )
}

function FormActions({ form, onSave, disabled }) {
  return (
    <>
      {form.error && <NoticeBox variant="error" style={{ margin: '12px 0' }}>{form.error}</NoticeBox>}
      <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
        <Button variant="primary" onClick={onSave} disabled={disabled || form.busy}>{form.busy ? 'Saving…' : 'Save'}</Button>
        <Button onClick={form.close} disabled={form.busy}>Cancel</Button>
      </div>
    </>
  )
}

function Table({ headers, rows, empty }) {
  return (
    <div className="ds-table-card">
      <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 560 }}>
        <thead><tr>{headers.map((h, i) => <th key={i} style={th()}>{h}</th>)}</tr></thead>
        <tbody>
          {rows.map((cells, i) => <tr key={i}>{Children.toArray(cells).map((c, j) => <td key={j} style={td()}>{c}</td>)}</tr>)}
          {rows.length === 0 && <tr><td colSpan={headers.length} style={{ ...td(), textAlign: 'center', color: 'var(--fg-subtle)' }}>{empty}</td></tr>}
        </tbody>
      </table>
    </div>
  )
}

const omit = (obj, key) => Object.fromEntries(Object.entries(obj).filter(([k]) => k !== key))

const introStyle = { fontSize: 14, color: 'var(--fg-muted)', margin: '0 0 16px', maxWidth: 640 }
const gridStyle = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 12 }
function th(align) {
  return { textAlign: align || 'left', fontWeight: 600, fontSize: 11, lineHeight: '16px', textTransform: 'uppercase', letterSpacing: 1.2, color: 'var(--fg-subtle)', padding: '12px 16px', borderBottom: '1px solid var(--grey-300)' }
}
function td(align) {
  return { padding: '10px 16px', borderBottom: '1px solid var(--grey-300)', textAlign: align || 'left', fontSize: 14, color: 'var(--grey-700)', verticalAlign: 'middle' }
}
