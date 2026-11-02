import { useState } from 'react'
import { Button, Card, Chip, Field, Icon, NoticeBox, Select } from '../components/ds/index.js'
import { useApi } from '../hooks/useApi.js'
import { listImportKinds, runImport, downloadImportTemplate } from '../api/imports.js'
import { listAllStores } from '../api/core.js'
import { apiErrorText } from '../lib/apiError.js'
import { useT } from '../i18n/index.js'

/** Onboarding from a spreadsheet: pick what to import, preview it (nothing
 * is saved), fix any rows the preview flags, then import. Imports are
 * all-or-nothing on the server, so a file with errors never half-loads. */
export default function ImportPanel({ entity }) {
  const t = useT()
  const { data: kinds } = useApi(() => listImportKinds(), [])
  const { data: stores } = useApi(() => listAllStores(), [])
  const [kindKey, setKindKey] = useState('products')
  const [storeId, setStoreId] = useState('')
  const [file, setFile] = useState(null)
  const [fileInputKey, setFileInputKey] = useState(0)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const kind = kinds?.find((k) => k.key === kindKey)
  const pricesPerStore = entity.price_mode === 'store' && ['products', 'prices'].includes(kindKey)
  const needsStore = kind?.needs_store || pricesPerStore
  const store = storeId || stores?.[0]?.id || ''

  function choose(key) {
    setKindKey(key); setResult(null); setError(''); setFile(null); setFileInputKey((k) => k + 1)
  }

  async function submit(commit) {
    setBusy(true); setError('')
    try {
      const response = await runImport(kindKey, { file, store: needsStore ? store : undefined, commit })
      setResult(response)
      if (response.committed) { setFile(null); setFileInputKey((k) => k + 1) }
    } catch (err) {
      setResult(null)
      setError(apiErrorText(err, t('Could not read the file.')))
    } finally { setBusy(false) }
  }

  return (
    <>
      <p style={{ fontSize: 14, color: 'var(--fg-muted)', margin: '0 0 16px', maxWidth: 680 }}>
        {t('Load your existing data from Excel or CSV. Suggested order: suppliers, products (with prices), then opening stock for each store. Every import is previewed first and only saved if every row is valid.')}
      </p>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
        {(kinds ?? []).map((k) => <Chip key={k.key} selected={k.key === kindKey} onClick={() => choose(k.key)}>{t(k.title)}</Chip>)}
      </div>

      {kind && (
        <Card style={{ maxWidth: 900, marginBottom: 16 }}>
          <p style={{ fontSize: 13, color: 'var(--grey-700)', margin: '0 0 12px' }}>{t(kind.description)}</p>
          <details style={{ marginBottom: 12 }}>
            <summary style={{ cursor: 'pointer', fontSize: 13, color: 'var(--blue-700, var(--blue-600))' }}>{t('Columns ({n})', { n: kind.columns.length })}</summary>
            <table style={{ borderCollapse: 'collapse', marginTop: 8, fontSize: 13 }}>
              <tbody>
                {kind.columns.map((c) => (
                  <tr key={c.name}>
                    <td style={{ padding: '3px 12px 3px 0', fontFamily: 'monospace', whiteSpace: 'nowrap' }}>{c.name}{c.required && <span style={{ color: 'var(--status-error)' }}> *</span>}</td>
                    <td style={{ padding: '3px 12px 3px 0', color: 'var(--grey-700)' }}>{t(c.help)}</td>
                    <td style={{ padding: '3px 0', color: 'var(--fg-subtle)' }}>{c.example && t('e.g. {example}', { example: c.example })}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
          <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <Button onClick={() => downloadImportTemplate(kindKey)}><Icon name="download" size={16} /> {t('Download template')}</Button>
            {needsStore && (
              <Field label={kind.needs_store ? t('Store the stock is in') : t('Store to set prices for')}>
                <Select value={store} onChange={(e) => { setStoreId(e.target.value); setResult(null) }} options={(stores ?? []).map((s) => ({ value: s.id, label: s.name }))} style={{ width: 220 }} />
              </Field>
            )}
            <Field label={t('File (.xlsx or .csv)')}>
              <input
                key={fileInputKey} type="file" accept=".xlsx,.csv,text/csv"
                onChange={(e) => { setFile(e.target.files?.[0] ?? null); setResult(null); setError('') }}
                style={{ fontSize: 13 }}
              />
            </Field>
            <Button onClick={() => submit(false)} disabled={!file || busy}>{busy ? t('Checking…') : t('Preview')}</Button>
            <Button variant="primary" onClick={() => submit(true)} disabled={!file || busy || !result || result.error_count > 0 || result.committed}>{t('Import')}</Button>
          </div>
        </Card>
      )}

      {error && <NoticeBox variant="error" style={{ maxWidth: 900 }}>{error}</NoticeBox>}
      {result && <ImportResult result={result} />}
    </>
  )
}

function ImportResult({ result }) {
  const t = useT()
  const summary = t(result.rows === 1 ? '{n} row: {created} new, {updated} updated' : '{n} rows: {created} new, {updated} updated', { n: result.rows, created: result.created, updated: result.updated })
  const columns = result.preview.length ? Object.keys(result.preview[0]).filter((k) => k !== 'row') : []
  return (
    <div style={{ maxWidth: 900, display: 'flex', flexDirection: 'column', gap: 12 }}>
      {result.committed && <NoticeBox variant="valid" title={t('Imported')}>{summary}.</NoticeBox>}
      {!result.committed && result.error_count === 0 && (
        <NoticeBox variant="info" title={t('Preview — nothing saved yet')}>{summary}. {t('Click Import to save.')}</NoticeBox>
      )}
      {result.error_count > 0 && (
        <NoticeBox variant="error" title={t(result.error_count === 1 ? '{n} row needs fixing — nothing was saved' : '{n} rows need fixing — nothing was saved', { n: result.error_count })}>
          {t('Correct these rows in your file and preview again.')}
          <ul style={{ margin: '8px 0 0', paddingLeft: 20 }}>
            {result.errors.map((e) => <li key={`${e.row}-${e.message}`}>{t('Row {n}', { n: e.row })}: {e.message}</li>)}
          </ul>
        </NoticeBox>
      )}
      {result.ignored_columns.length > 0 && (
        <div style={{ fontSize: 12, color: 'var(--fg-subtle)' }}>{t('Columns not used:')} {result.ignored_columns.join(', ')}</div>
      )}
      {result.preview.length > 0 && result.error_count === 0 && (
        <div className="ds-table-card">
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr>{['Row', ...columns].map((c) => <th key={c} style={th}>{c === 'Row' ? t('Row') : c.replace(/_/g, ' ')}</th>)}</tr>
            </thead>
            <tbody>
              {result.preview.map((r) => (
                <tr key={r.row}>
                  <td style={td}>{r.row}</td>
                  {columns.map((c) => <td key={c} style={td}>{r[c] ?? '—'}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
          {result.rows > result.preview.length && <div style={{ ...td, color: 'var(--fg-subtle)' }}>{t('Showing the first {n} rows.', { n: result.preview.length })}</div>}
        </div>
      )}
    </div>
  )
}

const th = { textAlign: 'left', fontWeight: 600, fontSize: 11, lineHeight: '16px', textTransform: 'uppercase', letterSpacing: 1.2, color: 'var(--fg-subtle)', padding: '12px 16px', borderBottom: '1px solid var(--grey-300)' }
const td = { padding: '14px 16px', borderBottom: '1px solid var(--grey-300)', color: 'var(--grey-700)' }
