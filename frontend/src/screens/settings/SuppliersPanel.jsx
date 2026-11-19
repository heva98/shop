import { Button, Card, EmptyState, Field, Icon, Input } from '../../components/ds/index.js'
import { useApi } from '../../hooks/useApi.js'
import { createSupplier, listAllSuppliers, updateSupplier } from '../../api/receiving.js'
import { t, useT } from '../../i18n/index.js'
import { FormActions, Table } from './FormParts.jsx'
import { useForm, introStyle, gridStyle } from './shared.js'

export default function SuppliersPanel({ entity }) {
  useT()
  const { data: suppliers, loading, error, refetch } = useApi(() => listAllSuppliers(), [])
  const form = useForm({ name: '', description: '', location: '', email: '', phone: '', payment_terms_days: '0' })
  const save = (d) => (d.id ? updateSupplier(d.id, d) : createSupplier({ ...d, entity: entity.id }))
  return (
    <>
      <p style={introStyle}>{t('Wholesalers and distributors you buy from. They appear on receiving invoices and in the purchases report.')}</p>
      <Button variant="primary" onClick={() => form.open()} style={{ marginBottom: 12 }}><Icon name="add" size={16} /> {t('Add supplier')}</Button>
      {form.draft && (
        <Card style={{ marginBottom: 12 }}>
          <div style={gridStyle}>
            <Field label={t('Name')} required><Input value={form.draft.name} onChange={form.set('name')} /></Field>
            <Field label={t('Description')}><Input value={form.draft.description} onChange={form.set('description')} /></Field>
            <Field label={t('Location')}><Input value={form.draft.location} onChange={form.set('location')} /></Field>
            <Field label={t('Phone')}><Input value={form.draft.phone} onChange={form.set('phone')} /></Field>
            <Field label={t('Email')}><Input value={form.draft.email} onChange={form.set('email')} /></Field>
            <Field label={t('Credit (days to pay)')}><Input value={String(form.draft.payment_terms_days ?? 0)} onChange={form.set('payment_terms_days')} /></Field>
          </div>
          <FormActions form={form} onSave={() => form.submit(save, refetch)} disabled={!form.draft.name.trim()} />
        </Card>
      )}
      <Table
        headers={['Name', 'Location', 'Phone', 'Email', 'Credit', '']}
        rows={(suppliers ?? []).map((s) => [s.name, s.location || '—', s.phone || '—', s.email || '—',
          s.payment_terms_days ? t('{n} days', { n: s.payment_terms_days }) : t('Pay on delivery'), <Button key="edit" size="small" onClick={() => form.open(s)}>{t('Edit')}</Button>])}
        caption={t('Suppliers')} loading={loading} error={error} onRetry={refetch}
        empty={(
          <EmptyState
            icon="receiving" title={t('No suppliers yet')}
            hint={t('Suppliers are the businesses you buy stock from. Add them to record deliveries and keep track of what you owe each one.')}
            action={<Button variant="primary" onClick={() => form.open()}><Icon name="add" size={16} /> {t('Add supplier')}</Button>}
          />
        )}
      />
    </>
  )
}
