import { Button, Card, Field, Icon, Input } from '../../components/ds/index.js'
import { useApi } from '../../hooks/useApi.js'
import { createGenericDrug, listAllGenericDrugs, updateGenericDrug } from '../../api/catalog.js'
import { t, useT } from '../../i18n/index.js'
import { FormActions, Table } from './FormParts.jsx'
import { useForm, introStyle, gridStyle } from './shared.js'

export default function GenericsPanel({ entity }) {
  useT()
  const { data: generics, loading, error, refetch } = useApi(() => listAllGenericDrugs(), [])
  const form = useForm({ name: '', short_name: '', description: '' })
  const save = (d) => (d.id ? updateGenericDrug(d.id, d) : createGenericDrug({ ...d, entity: entity.id }))
  return (
    <>
      <p style={introStyle}>
        {t('The active ingredient each medicine is made of, e.g. Paracetamol or Amoxicillin. Link products to it, and the till finds every brand of a medicine when you search for the generic name.')}
      </p>
      <Button variant="primary" onClick={() => form.open()} style={{ marginBottom: 12 }}><Icon name="add" size={16} /> {t('Add generic medicine')}</Button>
      {form.draft && (
        <Card style={{ marginBottom: 12 }}>
          <div style={gridStyle}>
            <Field label={t('Name')} required><Input value={form.draft.name} onChange={form.set('name')} placeholder={t('e.g. Amoxicillin')} /></Field>
            <Field label={t('Short name')}><Input value={form.draft.short_name} onChange={form.set('short_name')} placeholder={t('e.g. AMOX')} /></Field>
            <Field label={t('Description')}><Input value={form.draft.description} onChange={form.set('description')} placeholder={t('e.g. Penicillin antibiotic')} /></Field>
          </div>
          <FormActions form={form} onSave={() => form.submit(save, refetch)} disabled={!form.draft.name.trim()} />
        </Card>
      )}
      <Table
        headers={['Name', 'Short name', 'Description', '']}
        rows={(generics ?? []).map((g) => [g.name, g.short_name || '—', g.description || '—', <Button key="edit" size="small" onClick={() => form.open(g)}>{t('Edit')}</Button>])}
        caption={t('Generic medicines')} loading={loading} error={error} onRetry={refetch}
        empty={t('No generic medicines yet. They are also created when you type a new one while adding a product.')}
      />
    </>
  )
}
