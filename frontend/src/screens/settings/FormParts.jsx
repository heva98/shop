// The table and the save/cancel buttons every settings panel uses.
import { Button, DataTable, NoticeBox } from '../../components/ds/index.js'
import { t, useT } from '../../i18n/index.js'

export function FormActions({ form, onSave, disabled }) {
  useT()
  return (
    <>
      {form.error && <NoticeBox variant="error" style={{ margin: '12px 0' }}>{form.error}</NoticeBox>}
      <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
        <Button variant="primary" onClick={onSave} disabled={disabled || form.busy}>{form.busy ? t('Saving…') : t('Save')}</Button>
        <Button onClick={form.close} disabled={form.busy}>{t('Cancel')}</Button>
      </div>
    </>
  )
}

/** A list table from header labels and rows of cells, in order:
 *
 *   <Table caption={t('Suppliers')} headers={['Name', 'Phone', '']}
 *     rows={suppliers.map((s) => [s.name, s.phone, <Button …/>])}
 *     loading={loading} error={error} onRetry={refetch} empty={…} />
 *
 * A thin layer over DataTable for the many simple lists: headers are
 * translated here, a blank cell shows "—", and loading / error / empty
 * states come for free. Reach for DataTable directly when a list needs
 * sorting or per-column options. */
export function Table({ headers, rows, empty, loading, error, onRetry, caption, minWidth = 560, density }) {
  useT()
  const columns = headers.map((h, i) => ({ key: String(i), header: h ? t(h) : '', primary: i === 0, cell: (row) => blankDash(row[i]) }))
  return (
    <DataTable
      caption={caption} columns={columns} rows={rows} rowKey={(_, i) => i}
      loading={loading} error={error} onRetry={onRetry} empty={empty}
      minWidth={minWidth} density={density}
    />
  )
}

const blankDash = (v) => (v == null || v === '' || v === false ? '—' : v)
