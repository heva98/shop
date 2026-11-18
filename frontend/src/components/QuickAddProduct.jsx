import { useState } from 'react'
import { Button, Checkbox, Field, Icon, Input, Modal, NoticeBox, Select } from './ds/index.js'
import { useApi } from '../hooks/useApi.js'
import { useAuth } from '../auth/AuthContext.jsx'
import { listAllCategories, listAllUnitsOfMeasure, quickAddProduct } from '../api/catalog.js'
import { apiErrorText } from '../lib/apiError.js'
import { t, tOptions, useT } from '../i18n/index.js'

const VAT_OPTIONS = [
  { value: 'standard', label: 'Standard (18%)' }, { value: 'exempt', label: 'Exempt' }, { value: 'zero_rated', label: 'Zero-rated' },
]
const EMPTY = {
  name: '', uom: '', tracks_expiry: false, selling_price: '', buying_price: '', quantity: '', expiry_date: '',
  reorder_level: '', barcode: '', category: '', brand: '', size: '', vat_class: 'standard',
}
const number = (value) => value.replace(/[^\d.]/g, '')
const orNull = (value) => (value === '' ? null : value)

/** One form for everything a product needs before it can be sold: what it
 * is, its selling price and the stock on the shelf now. With `product`
 * (one already in the catalogue) only the price and stock are asked for.
 * `storeId`: where the stock goes; a multi-branch owner on "All stores"
 * picks one here. `initial` pre-fills a new product, e.g. the barcode the
 * till just scanned. */
export default function QuickAddProduct({ product = null, storeId = null, initial = null, onClose, onSaved }) {
  useT()
  const auth = useAuth()
  const { data: uoms } = useApi(() => (product ? null : listAllUnitsOfMeasure()), [product])
  const { data: categories } = useApi(() => (product ? null : listAllCategories()), [product])
  const stores = auth.workplaces.filter((w) => w.store).map((w) => ({ value: w.store, label: w.store_name }))
  const [store, setStore] = useState(storeId ?? (stores.length === 1 ? stores[0].value : ''))
  const [draft, setDraft] = useState({ ...EMPTY, ...initial })
  const [more, setMore] = useState(Boolean(initial?.barcode))
  const [error, setError] = useState('')
  const [saved, setSaved] = useState('')
  const [busy, setBusy] = useState(false)

  const uom = draft.uom || uoms?.[0]?.id || ''
  const unitName = product?.uom_name ?? uoms?.find((u) => u.id === uom)?.name ?? ''
  const perishable = product ? product.tracks_expiry : draft.tracks_expiry
  const set = (field, clean) => (e) => setDraft((d) => ({ ...d, [field]: clean ? clean(e.target.value) : e.target.value }))
  const hasStock = Number(draft.quantity) > 0

  async function save(addAnother) {
    setError('')
    setSaved('')
    if (!product && !draft.name.trim()) { setError(t('{field} is required.', { field: t('Product name') })); return }
    if (!product && draft.selling_price === '') { setError(t('Give the price you sell it at.')); return }
    if (hasStock && !store) { setError(t('Choose the store this is for.')); return }
    if (hasStock && perishable && !draft.expiry_date) { setError(t('Give the expiry date of the stock on the shelf.')); return }
    setBusy(true)
    try {
      const body = {
        store: orNull(store), selling_price: orNull(draft.selling_price), buying_price: orNull(draft.buying_price),
        quantity: orNull(draft.quantity), expiry_date: perishable ? orNull(draft.expiry_date) : null,
        reorder_level: store ? orNull(draft.reorder_level) : null,
        ...(product ? { product: product.id } : {
          name: draft.name.trim(), uom, tracks_expiry: draft.tracks_expiry, barcode: draft.barcode.trim(),
          category: orNull(draft.category), brand: draft.brand, size: draft.size, vat_class: draft.vat_class,
        }),
      }
      const result = await quickAddProduct(body)
      onSaved?.(result)
      if (!addAnother) { onClose(); return }
      setSaved(t('{name} saved. Add the next one.', { name: result.product.name }))
      setDraft((d) => ({ ...EMPTY, uom: d.uom, vat_class: d.vat_class }))
    } catch (err) {
      setError(apiErrorText(err, t('Could not save.')))
    } finally { setBusy(false) }
  }

  const footer = (
    <>
      <Button onClick={onClose} disabled={busy}>{t('Cancel')}</Button>
      {!product && <Button onClick={() => save(true)} disabled={busy}>{t('Save and add another')}</Button>}
      <Button variant="primary" onClick={() => save(false)} disabled={busy}>{busy ? t('Saving…') : t('Save')}</Button>
    </>
  )

  return (
    <Modal title={product ? t('Price and stock: {name}', { name: product.name }) : t('Add a product')} onClose={onClose} footer={footer}>
      <form onSubmit={(e) => { e.preventDefault(); save(false) }} className="quick-add">
        {saved && <NoticeBox variant="valid">{saved}</NoticeBox>}
        {error && <NoticeBox variant="error">{error}</NoticeBox>}

        {!product && (
          <div className="quick-add-grid">
            <Field label={t('Product name')} required><Input value={draft.name} onChange={set('name')} placeholder={t('e.g. Sugar 1kg')} /></Field>
            <Field label={t('Sold by')} required>
              <Select value={uom} onChange={set('uom')} options={(uoms ?? []).map((u) => ({ value: u.id, label: u.name }))} />
            </Field>
          </div>
        )}

        <div className="quick-add-grid">
          <Field label={t('Selling price (TZS)')} required={!product}>
            <Input value={draft.selling_price} onChange={set('selling_price', number)} inputMode="decimal" placeholder={product?.has_price ? t('Leave empty to keep the price') : '3200'} />
          </Field>
          <Field label={t('Buying price (TZS)')}>
            <Input value={draft.buying_price} onChange={set('buying_price', number)} inputMode="decimal" placeholder="2800" />
          </Field>
        </div>
        <p className="quick-add-hint">{t('Per {unit}. The buying price lets the reports show your profit.', { unit: unitName || t('unit') })}</p>

        {!product && (
          <Checkbox checked={draft.tracks_expiry} onChange={() => setDraft((d) => ({ ...d, tracks_expiry: !d.tracks_expiry }))} label={t('It has an expiry date (food, drinks, medicine, cosmetics)')} />
        )}

        {!storeId && stores.length > 1 && (
          <Field label={t('Store')}><Select value={store} onChange={(e) => setStore(e.target.value)} options={[{ value: '', label: t('Select store…') }, ...stores]} /></Field>
        )}
        <div className="quick-add-grid">
          <Field label={t('How many do you have now?')}>
            <Input value={draft.quantity} onChange={set('quantity', number)} inputMode="decimal" placeholder="0" />
          </Field>
          {perishable && hasStock && (
            <Field label={t('Expiry date')} required><Input type="date" value={draft.expiry_date} onChange={set('expiry_date')} /></Field>
          )}
          {store && (
            <Field label={t('Warn me when stock falls to')}>
              <Input value={draft.reorder_level} onChange={set('reorder_level', number)} inputMode="decimal" placeholder={t('e.g. 5')} />
            </Field>
          )}
        </div>

        {!product && (
          <>
            <button type="button" className="login-link quick-add-more" onClick={() => setMore((m) => !m)} aria-expanded={more}>
              <Icon name={more ? 'chevron-up' : 'chevron-down'} size={16} /> {more ? t('Fewer options') : t('More options (barcode, category, brand, VAT)')}
            </button>
            {more && (
              <div className="quick-add-grid">
                <Field label={t('Barcode')}><Input value={draft.barcode} onChange={set('barcode')} placeholder={t('Scan or type')} prefixIcon="barcode" /></Field>
                <Field label={t('Category')}>
                  <Select value={draft.category} onChange={set('category')} options={[{ value: '', label: '—' }, ...(categories ?? []).map((c) => ({ value: c.id, label: c.name }))]} />
                </Field>
                <Field label={t('Brand')}><Input value={draft.brand} onChange={set('brand')} placeholder={t('e.g. Kilombero')} /></Field>
                <Field label={t('Size')}><Input value={draft.size} onChange={set('size')} placeholder={t('e.g. 1 kg, 500 ml')} /></Field>
                <Field label={t('VAT')}><Select value={draft.vat_class} onChange={set('vat_class')} options={tOptions(VAT_OPTIONS)} /></Field>
              </div>
            )}
          </>
        )}
        <button type="submit" hidden aria-hidden="true" tabIndex={-1} />
      </form>
    </Modal>
  )
}
