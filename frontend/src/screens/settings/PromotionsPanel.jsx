import { useState } from 'react'
import { Button, Card, Checkbox, Field, Icon, Input, NoticeBox, Select, Tag } from '../../components/ds/index.js'
import { useApi } from '../../hooks/useApi.js'
import { listAllProducts, listAllUnitsOfMeasure } from '../../api/catalog.js'
import { createPromotion, deletePromotion, listAllPromotions, updatePromotion } from '../../api/pricing.js'
import { listAllStores } from '../../api/core.js'
import { fmt } from '../../appData.js'
import { apiErrorText } from '../../lib/apiError.js'
import { dateLocale, t, useT } from '../../i18n/index.js'
import { FormActions, Table } from './FormParts.jsx'
import { useForm, introStyle, gridStyle } from './shared.js'

const PROMOTION_STATUS = (p) => {
  const today = new Date().toISOString().slice(0, 10)
  if (!p.is_active) return ['neutral', 'Switched off']
  if (p.ends_on < today) return ['neutral', 'Ended']
  if (p.starts_on > today) return [undefined, 'Starts soon']
  return ['positive', 'Running']
}

export default function PromotionsPanel({ entity }) {
  useT()
  const { data: promotions, loading, error: loadError, refetch } = useApi(() => listAllPromotions(), [])
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
    if (!window.confirm(t('Remove the promotion “{name}”? To end it early but keep the record, switch it off instead.', { name: promotion.name }))) return
    setError('')
    try {
      await deletePromotion(promotion.id)
      refetch()
    } catch (err) {
      setError(apiErrorText(err, t('Could not remove the promotion.')))
    }
  }

  return (
    <>
      <p style={introStyle}>
        {t('Time-limited offer prices. While a promotion runs, the till charges its price instead of the regular one, and receipts and reports show what was really charged. A promotion for one store wins over one for every store.')}
      </p>
      <Button variant="primary" onClick={() => form.open({ product: products?.[0]?.id ?? '' })} style={{ marginBottom: 12 }} disabled={!products?.length}>
        <Icon name="add" size={16} /> {t('Add promotion')}
      </Button>
      {error && <NoticeBox variant="error" style={{ marginBottom: 12 }}>{error}</NoticeBox>}
      {form.draft && (
        <Card style={{ marginBottom: 12 }}>
          <div style={gridStyle}>
            <Field label={t('Name')} required><Input value={form.draft.name} onChange={form.set('name')} placeholder={t('e.g. Weekend soda offer')} /></Field>
            <Field label={t('Product')} required>
              <Select value={form.draft.product} onChange={form.set('product')} options={(products ?? []).map((p) => ({ value: p.id, label: p.name }))} />
            </Field>
            <Field label={t('Unit')}>
              <Select value={form.draft.uom ?? ''} onChange={form.set('uom')} options={[{ value: '', label: t('Its stock unit') }, ...(uoms ?? []).map((u) => ({ value: u.id, label: u.name }))]} />
            </Field>
            {stores && (
              <Field label={t('Store')}>
                <Select value={form.draft.store ?? ''} onChange={form.set('store')} options={[{ value: '', label: t('Every store') }, ...stores.map((st) => ({ value: st.id, label: st.name }))]} />
              </Field>
            )}
            <Field label={t('Offer price (TZS)')} required><Input value={String(form.draft.promo_price)} onChange={form.set('promo_price')} /></Field>
            <Field label={t('From')} required><Input type="date" value={form.draft.starts_on} onChange={form.set('starts_on')} /></Field>
            <Field label={t('To (inclusive)')} required><Input type="date" value={form.draft.ends_on} onChange={form.set('ends_on')} /></Field>
          </div>
          <div style={{ margin: '12px 0' }}>
            <Checkbox checked={form.draft.is_active} onChange={form.toggle('is_active')} label={t('Switched on')} />
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
            <><div style={{ color: 'var(--grey-900)' }}>{pr.name}</div><div style={{ fontSize: 12 }}>{pr.product_name}{pr.uom_name ? ` · ${t('per {unit}', { unit: pr.uom_name })}` : ''}</div></>,
            pr.store_name ?? t('Every store'),
            <>{fmt(Number(pr.promo_price))}{pr.regular_price && <div style={{ fontSize: 12, textDecoration: 'line-through' }}>{fmt(Number(pr.regular_price))}</div>}</>,
            `${new Date(pr.starts_on).toLocaleDateString(dateLocale())} – ${new Date(pr.ends_on).toLocaleDateString(dateLocale())}`,
            <Tag key="status" variant={variant}>{t(label)}</Tag>,
            <div key="actions" style={{ display: 'flex', gap: 4 }}>
              <Button size="small" onClick={() => form.open({ ...pr, uom: pr.uom ?? '', store: pr.store ?? '', promo_price: String(Number(pr.promo_price)) })}>{t('Edit')}</Button>
              <Button size="small" variant="destructive" onClick={() => remove(pr)}>{t('Remove')}</Button>
            </div>,
          ]
        })}
        caption={t('Promotions')} loading={loading} error={loadError} onRetry={refetch} empty={t('No promotions yet.')}
      />
    </>
  )
}
