import { useState } from 'react'
import { Button, Card, Field, Icon, Input, NoticeBox, Tag } from '../components/ds/index.js'
import { useApi } from '../hooks/useApi.js'
import { useAuth } from '../auth/AuthContext.jsx'
import { createStore, deleteStore, listAllStores, updateStore } from '../api/core.js'
import { t, useT } from '../i18n/index.js'

const FIELD_LABEL = { name: 'Store name', address: 'Location' }

const EMPTY_DRAFT = { name: '', address: '' }

function th() {
  return { textAlign: 'left', fontWeight: 600, fontSize: 11, lineHeight: '16px', textTransform: 'uppercase', letterSpacing: 1.2, color: 'var(--fg-subtle)', padding: '12px 16px', borderBottom: '1px solid var(--grey-300)' }
}
function td(color) {
  return { padding: '14px 16px', borderBottom: '1px solid var(--grey-300)', fontSize: 14, color: color || 'var(--grey-700)' }
}

/** Flattens a DRF error body ({field: [msg]} / {detail}) into readable lines. */
function errorLines(err) {
  const body = err?.body
  if (!body || typeof body !== 'object') return [err?.message || t('Request failed')]
  return Object.entries(body).map(([field, msgs]) => {
    const text = Array.isArray(msgs) ? msgs.join(' ') : String(msgs)
    return field === 'detail' || field === 'non_field_errors' ? text : `${FIELD_LABEL[field] ? t(FIELD_LABEL[field]) : field}: ${text}`
  })
}

export default function AdminStores() {
  useT()
  const auth = useAuth()
  const { data: stores, loading, error: loadError, refetch } = useApi(() => listAllStores(), [])

  const [draft, setDraft] = useState(EMPTY_DRAFT)
  const [errors, setErrors] = useState([])
  const [notice, setNotice] = useState(null)
  const [saving, setSaving] = useState(false)
  const [busyStoreId, setBusyStoreId] = useState(null)

  const set = (field) => (e) => setDraft((d) => ({ ...d, [field]: e.target.value }))
  // Single shop: its one store is created and kept by the server.
  const isSingle = auth.entity?.store_mode === 'single'

  async function run(storeId, fn, successText) {
    setBusyStoreId(storeId)
    setErrors([])
    setNotice(null)
    try {
      await fn()
      setNotice(successText)
      refetch()
    } catch (err) {
      setErrors(errorLines(err))
    } finally {
      setBusyStoreId(null)
    }
  }

  function toggleActive(store) {
    const deactivating = store.is_active
    if (deactivating && !window.confirm(t('Deactivate {name}?', { name: store.name }))) return
    run(store.id, () => updateStore(store.id, { is_active: !deactivating }), t(deactivating ? '{name} deactivated.' : '{name} activated.', { name: store.name }))
  }

  function remove(store) {
    if (!window.confirm(t('Remove {name}? This permanently deletes the store, its stock and its staff assignments. This cannot be undone.', { name: store.name }))) return
    run(store.id, () => deleteStore(store.id), t('{name} removed.', { name: store.name }))
  }

  async function addStore() {
    setNotice(null)
    if (!draft.name.trim()) {
      setErrors([t('Store name is required.')])
      return
    }
    setSaving(true)
    setErrors([])
    try {
      const store = await createStore({ ...draft, name: draft.name.trim(), entity: auth.entity?.id })
      setNotice(t('{name} added.', { name: store.name }))
      setDraft(EMPTY_DRAFT)
      refetch()
    } catch (err) {
      setErrors(errorLines(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      {errors.length > 0 && (
        <NoticeBox variant="error" title={t('Could not update stores')} style={{ marginBottom: 12 }}>
          {errors.map((e) => <div key={e}>{e}</div>)}
        </NoticeBox>
      )}
      {notice && <NoticeBox variant="valid" title={notice} style={{ marginBottom: 12 }} />}
      {isSingle && (
        <NoticeBox variant="info" title={t('Single shop')} style={{ marginBottom: 12 }}>
          {t('Your shop trades from one store, and all staff are assigned to it. To open branches, switch to “Shop with multiple branches” under Shop profile.')}
        </NoticeBox>
      )}
      <div className="ds-table-card" style={{ marginBottom: 16 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 720 }}>
          <thead>
            <tr>
              <th style={th()}>{t('Store')}</th>
              <th style={th()}>{t('Location')}</th>
              <th style={th()}>{t('Role')}</th>
              <th style={th()}>{t('Status')}</th>
              <th style={th()}>{t('Actions')}</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td style={td()} colSpan={5}>{t('Loading stores…')}</td></tr>}
            {loadError && <tr><td style={td('var(--red-600)')} colSpan={5}>{t('Could not load stores:')} {loadError.message}</td></tr>}
            {!loading && !loadError && (stores ?? []).length === 0 && <tr><td style={td()} colSpan={5}>{t('No stores yet.')}</td></tr>}
            {(stores ?? []).map((st) => (
              <tr key={st.id}>
                <td style={td('var(--grey-900)')}>{st.name}</td>
                <td style={td()}>{st.address || '—'}</td>
                <td style={td()}>{st.is_main ? <Tag variant="neutral">{t('Main store')}</Tag> : <Tag>{t('Branch')}</Tag>}</td>
                <td style={td()}>{st.is_active ? <Tag variant="positive">{t('Active')}</Tag> : <Tag variant="negative">{t('Inactive')}</Tag>}</td>
                <td style={td()}>
                  {isSingle && st.is_active ? '—' : <div style={{ display: 'flex', gap: 6 }}>
                    <Button size="small" disabled={busyStoreId === st.id} onClick={() => toggleActive(st)}>
                      {st.is_active ? t('Deactivate') : t('Activate')}
                    </Button>
                    {!st.is_main && (
                      <Button size="small" variant="destructive" disabled={busyStoreId === st.id} onClick={() => remove(st)}>
                        {t('Remove')}
                      </Button>
                    )}
                  </div>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!isSingle && <Card>
        <p style={{ fontSize: 13, fontWeight: 500, color: 'var(--fg-subtle)', textTransform: 'uppercase', letterSpacing: 0.5, margin: '0 0 12px' }}>{t('Add store')}</p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 12, marginBottom: 12 }}>
          <Field label={t('Store name')} required><Input value={draft.name} onChange={set('name')} placeholder={t('e.g. Branch #004 — Sinza')} /></Field>
          <Field label={t('Location')}><Input value={draft.address} onChange={set('address')} /></Field>
        </div>
        <Button onClick={addStore} disabled={saving}><Icon name="add" size={16} /> {saving ? t('Adding…') : t('Add store')}</Button>
      </Card>}
    </>
  )
}
