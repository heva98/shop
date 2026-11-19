import { useMemo, useState } from 'react'
import { Button, Card, Checkbox, EmptyState, Field, Icon, Input, NoticeBox, Select, Tag } from '../../components/ds/index.js'
import { useApi } from '../../hooks/useApi.js'
import {
  createCategory, createProduct, listAllCategories, listAllGenericDrugs, listAllProducts, listAllUnitsOfMeasure, updateProduct,
} from '../../api/catalog.js'
import { isPharmacy } from '../../appData.js'
import QuickAddProduct from '../../components/QuickAddProduct.jsx'
import { t, tOptions, useT } from '../../i18n/index.js'
import { FormActions, Table } from './FormParts.jsx'
import { VAT_OPTIONS, VAT_LABEL, useForm, introStyle, gridStyle } from './shared.js'

export default function ProductsPanel({ entity }) {
  useT()
  const { data: products, loading, error, refetch } = useApi(() => listAllProducts(), [])
  const { data: categories, refetch: refetchCategories } = useApi(() => listAllCategories(), [])
  const { data: uoms } = useApi(() => listAllUnitsOfMeasure(), [])
  const [filter, setFilter] = useState('')
  const pharmacy = isPharmacy(entity)
  const { data: generics } = useApi(() => (pharmacy ? listAllGenericDrugs() : null), [pharmacy])
  const genericName = useMemo(() => Object.fromEntries((generics ?? []).map((g) => [g.id, g.name])), [generics])
  const form = useForm({
    name: '', category: '', brand: '', size: '', uom: '', vat_class: 'standard', barcode: '', tracks_expiry: false,
    generic_drug: '', is_prescription_only: false, is_controlled_substance: false, registration_number: '',
  })
  const categoryForm = useForm({ name: '', short_name: '', description: '' })
  const [quickAdd, setQuickAdd] = useState(false)

  const categoryName = useMemo(() => Object.fromEntries((categories ?? []).map((c) => [c.id, c.name])), [categories])
  const uomName = useMemo(() => Object.fromEntries((uoms ?? []).map((u) => [u.id, u.name])), [uoms])
  const q = filter.trim().toLowerCase()
  const visible = (products ?? []).filter((p) => !q || p.name.toLowerCase().includes(q) || p.barcode === filter.trim()
    || p.brand.toLowerCase().includes(q) || (categoryName[p.category] ?? '').toLowerCase().includes(q)
    || (p.generic_drug_name ?? '').toLowerCase().includes(q))

  function save(d) {
    const body = { ...d, entity: entity.id, category: d.category || null, generic_drug: d.generic_drug || null }
    return d.id ? updateProduct(d.id, body) : createProduct(body)
  }

  return (
    <>
      <p style={introStyle}>
        {t('The products your shop sells. Scan the barcode on the pack so the till can find it by scanning. Mark goods that expire (food, drinks, cosmetics) as perishable: receiving then asks for the expiry date and expired stock cannot be sold. A product also needs a selling price before it can be sold.')}
      </p>
      {(uoms ?? []).length === 0 && <NoticeBox variant="warning" style={{ marginBottom: 16 }}>{t('Add a unit first (e.g. Piece, Packet, Bottle).')}</NoticeBox>}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        <Button variant="primary" onClick={() => setQuickAdd(true)} disabled={(uoms ?? []).length === 0}><Icon name="add" size={16} /> {t('Add product')}</Button>
        <Button onClick={() => categoryForm.open()}><Icon name="add" size={16} /> {t('Add category')}</Button>
        <div style={{ flex: 1, minWidth: 200 }}><Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder={t('Filter by name, brand, category or barcode')} prefixIcon="search" /></div>
      </div>

      {quickAdd && <QuickAddProduct onClose={() => setQuickAdd(false)} onSaved={refetch} />}
      {categoryForm.draft && (
        <Card style={{ marginBottom: 12 }}>
          <div style={gridStyle}>
            <Field label={t('Category')} required><Input value={categoryForm.draft.name} onChange={categoryForm.set('name')} placeholder={t('e.g. Beverages')} /></Field>
            <Field label={t('Short name')}><Input value={categoryForm.draft.short_name} onChange={categoryForm.set('short_name')} placeholder={t('e.g. BEV')} /></Field>
            <Field label={t('Description')}><Input value={categoryForm.draft.description} onChange={categoryForm.set('description')} placeholder={t('e.g. Soft drinks, water, juice')} /></Field>
          </div>
          <FormActions form={categoryForm} onSave={() => categoryForm.submit((d) => createCategory({ ...d, entity: entity.id }), refetchCategories)} disabled={!categoryForm.draft.name.trim()} />
        </Card>
      )}

      {form.draft && (
        <Card style={{ marginBottom: 12 }}>
          <div style={gridStyle}>
            <Field label={t('Product name')} required><Input value={form.draft.name} onChange={form.set('name')} placeholder={t('e.g. Sugar 1kg')} /></Field>
            <Field label={t('Barcode')}><Input value={form.draft.barcode ?? ''} onChange={form.set('barcode')} placeholder={t('Scan or type')} prefixIcon="barcode" /></Field>
            <Field label={t('Category')}>
              <Select value={form.draft.category ?? ''} onChange={form.set('category')} options={[{ value: '', label: '—' }, ...(categories ?? []).map((c) => ({ value: c.id, label: c.name }))]} />
            </Field>
            <Field label={t('Brand')}><Input value={form.draft.brand} onChange={form.set('brand')} placeholder={t('e.g. Kilombero')} /></Field>
            {pharmacy && (
              <Field label={t('Generic medicine')}>
                <Select value={form.draft.generic_drug ?? ''} onChange={form.set('generic_drug')} options={[{ value: '', label: t('— not a medicine —') }, ...(generics ?? []).map((g) => ({ value: g.id, label: g.name }))]} />
              </Field>
            )}
            <Field label={pharmacy ? t('Strength / pack') : t('Size')}><Input value={form.draft.size} onChange={form.set('size')} placeholder={pharmacy ? t('e.g. 500mg tablet') : t('e.g. 1 kg, 500 ml')} /></Field>
            {pharmacy && <Field label={t('TMDA registration no.')}><Input value={form.draft.registration_number ?? ''} onChange={form.set('registration_number')} /></Field>}
            <Field label={t('Stock unit (smallest unit sold)')} required>
              <Select value={form.draft.uom} onChange={form.set('uom')} options={(uoms ?? []).map((u) => ({ value: u.id, label: u.name }))} />
            </Field>
            <Field label={t('VAT')}><Select value={form.draft.vat_class} onChange={form.set('vat_class')} options={tOptions(VAT_OPTIONS)} /></Field>
          </div>
          <p style={{ fontSize: 12, color: 'var(--fg-subtle)', margin: '8px 0 0' }}>
            {t('Stock is counted in this unit. When you receive stock, supplier packs (e.g. a carton of 12) are converted into it. You can also sell in bigger units (a crate, a dozen) with their own price under Selling prices.')}
          </p>
          <div style={{ display: 'flex', gap: 24, margin: '12px 0' }}>
            <Checkbox checked={form.draft.tracks_expiry} onChange={form.toggle('tracks_expiry')} label={t('Perishable — has an expiry date')} />
            {pharmacy && <Checkbox checked={form.draft.is_prescription_only} onChange={form.toggle('is_prescription_only')} label={t('Prescription only (POM)')} />}
            {pharmacy && <Checkbox checked={form.draft.is_controlled_substance} onChange={form.toggle('is_controlled_substance')} label={t('Controlled drug')} />}
          </div>
          <FormActions form={form} onSave={() => form.submit(save, refetch)} disabled={!form.draft.name.trim() || !form.draft.uom} />
        </Card>
      )}

      <Table
        headers={['Product', 'Category', 'Unit', 'VAT', '', '']}
        rows={visible.map((p) => [
          <><div style={{ color: 'var(--grey-900)' }}>{p.name}</div><div style={{ fontSize: 12 }}>{[genericName[p.generic_drug], p.brand, p.size, p.barcode].filter(Boolean).join(' · ')}</div></>,
          categoryName[p.category] ?? '—', uomName[p.uom] ?? '', t(VAT_LABEL[p.vat_class]),
          <span key="tags" style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
            {p.tracks_expiry && <Tag variant="neutral">{t('Perishable')}</Tag>}
            {p.is_prescription_only && <Tag variant="warning">{t('Prescription')}</Tag>}
            {p.is_controlled_substance && <Tag variant="negative">{t('Controlled')}</Tag>}
          </span>,
          <Button key="edit" size="small" onClick={() => form.open(p)}>{t('Edit')}</Button>,
        ])}
        caption={t('Products')} loading={loading} error={error} onRetry={refetch}
        empty={q ? t('Nothing matches.') : (
          <EmptyState
            icon="stock" title={t('No products yet')}
            hint={t('Add each product with its price and how many you have, or load them all at once under Import from Excel.')}
            action={<Button variant="primary" onClick={() => setQuickAdd(true)}><Icon name="add" size={16} /> {t('Add product')}</Button>}
          />
        )}
      />
    </>
  )
}
