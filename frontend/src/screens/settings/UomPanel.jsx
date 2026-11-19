import { Button, Card, Field, Icon, Input } from '../../components/ds/index.js'
import { useApi } from '../../hooks/useApi.js'
import { createUnitOfMeasure, listAllUnitsOfMeasure, updateUnitOfMeasure } from '../../api/catalog.js'
import { t, useT } from '../../i18n/index.js'
import { FormActions, Table } from './FormParts.jsx'
import { useForm, introStyle, gridStyle } from './shared.js'

export default function UomPanel({ entity }) {
  useT()
  const { data: uoms, refetch } = useApi(() => listAllUnitsOfMeasure(), [])
  const form = useForm({ name: '', description: '', unit_value: '1' })
  const save = (d) => (d.id ? updateUnitOfMeasure(d.id, d) : createUnitOfMeasure({ ...d, entity: entity.id }))
  return (
    <>
      <p style={introStyle}>{t('The units products are sold and received in, e.g. Piece, Packet, Dozen (12 pieces), Crate of 24.')}</p>
      <Button variant="primary" onClick={() => form.open()} style={{ marginBottom: 12 }}><Icon name="add" size={16} /> {t('Add unit')}</Button>
      {form.draft && (
        <Card style={{ marginBottom: 12 }}>
          <div style={gridStyle}>
            <Field label={t('Name')} required><Input value={form.draft.name} onChange={form.set('name')} placeholder={t('e.g. Crate of 24')} /></Field>
            <Field label={t('Description')}><Input value={form.draft.description} onChange={form.set('description')} placeholder={t('e.g. Crate of 24 bottles')} /></Field>
            <Field label={t('Units inside')} required><Input value={form.draft.unit_value} onChange={form.set('unit_value')} /></Field>
          </div>
          <FormActions form={form} onSave={() => form.submit(save, refetch)} disabled={!form.draft.name.trim()} />
        </Card>
      )}
      <Table
        headers={['Name', 'Description', 'Units inside', '']}
        rows={(uoms ?? []).map((u) => [u.name, u.description || '—', Number(u.unit_value), <Button key="edit" size="small" onClick={() => form.open(u)}>{t('Edit')}</Button>])}
        empty={uoms ? t('No units yet.') : t('Loading…')}
      />
    </>
  )
}
