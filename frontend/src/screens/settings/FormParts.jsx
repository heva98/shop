// The table and the save/cancel buttons every settings panel uses.
import { Children } from 'react'
import { Button, NoticeBox } from '../../components/ds/index.js'
import { t, useT } from '../../i18n/index.js'
import { th, td } from './shared.js'

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

export function Table({ headers, rows, empty }) {
  useT()
  return (
    <div className="ds-table-card">
      <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 560 }}>
        <thead><tr>{headers.map((h, i) => <th key={i} style={th()}>{h && t(h)}</th>)}</tr></thead>
        <tbody>
          {rows.map((cells, i) => <tr key={i}>{Children.toArray(cells).map((c, j) => <td key={j} style={td()}>{c}</td>)}</tr>)}
          {rows.length === 0 && <tr><td colSpan={headers.length} style={{ ...td(), textAlign: 'center', color: 'var(--fg-subtle)' }}>{empty}</td></tr>}
        </tbody>
      </table>
    </div>
  )
}
