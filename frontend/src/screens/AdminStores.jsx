import { useState } from 'react'
import { Button, Card, Field, Icon, Input, NoticeBox, Tag } from '../components/ds/index.js'
import { useApi } from '../hooks/useApi.js'
import { useAuth } from '../auth/AuthContext.jsx'
import { createStore, deleteStore, listAllStores, updateStore } from '../api/core.js'

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
  if (!body || typeof body !== 'object') return [err?.message || 'Request failed']
  return Object.entries(body).map(([field, msgs]) => {
    const text = Array.isArray(msgs) ? msgs.join(' ') : String(msgs)
    return field === 'detail' || field === 'non_field_errors' ? text : `${FIELD_LABEL[field] || field}: ${text}`
  })
}

export default function AdminStores() {
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
    if (deactivating && !window.confirm(`Deactivate ${store.name}?`)) return
    run(store.id, () => updateStore(store.id, { is_active: !deactivating }), `${store.name} ${deactivating ? 'deactivated' : 'activated'}.`)
  }

  function remove(store) {
    if (!window.confirm(`Remove ${store.name}? This permanently deletes the store, its stock and its staff assignments. This cannot be undone.`)) return
    run(store.id, () => deleteStore(store.id), `${store.name} removed.`)
  }

  async function addStore() {
    setNotice(null)
    if (!draft.name.trim()) {
      setErrors(['Store name is required.'])
      return
    }
    setSaving(true)
    setErrors([])
    try {
      const store = await createStore({ ...draft, name: draft.name.trim(), entity: auth.entity?.id })
      setNotice(`${store.name} added.`)
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
        <NoticeBox variant="error" title="Could not update stores" style={{ marginBottom: 12 }}>
          {errors.map((e) => <div key={e}>{e}</div>)}
        </NoticeBox>
      )}
      {notice && <NoticeBox variant="valid" title={notice} style={{ marginBottom: 12 }} />}
      {isSingle && (
        <NoticeBox variant="info" title="Single shop" style={{ marginBottom: 12 }}>
          Your shop trades from one store, and all staff are assigned to it. To open branches, switch to
          “Shop with multiple branches” under Shop profile.
        </NoticeBox>
      )}
      <div className="ds-table-card" style={{ marginBottom: 16 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 720 }}>
          <thead>
            <tr>
              <th style={th()}>Store</th>
              <th style={th()}>Location</th>
              <th style={th()}>Role</th>
              <th style={th()}>Status</th>
              <th style={th()}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td style={td()} colSpan={5}>Loading stores…</td></tr>}
            {loadError && <tr><td style={td('var(--red-600)')} colSpan={5}>Could not load stores: {loadError.message}</td></tr>}
            {!loading && !loadError && (stores ?? []).length === 0 && <tr><td style={td()} colSpan={5}>No stores yet.</td></tr>}
            {(stores ?? []).map((st) => (
              <tr key={st.id}>
                <td style={td('var(--grey-900)')}>{st.name}</td>
                <td style={td()}>{st.address || '—'}</td>
                <td style={td()}>{st.is_main ? <Tag variant="neutral">Main store</Tag> : <Tag>Branch</Tag>}</td>
                <td style={td()}>{st.is_active ? <Tag variant="positive">Active</Tag> : <Tag variant="negative">Inactive</Tag>}</td>
                <td style={td()}>
                  {isSingle && st.is_active ? '—' : <div style={{ display: 'flex', gap: 6 }}>
                    <Button size="small" disabled={busyStoreId === st.id} onClick={() => toggleActive(st)}>
                      {st.is_active ? 'Deactivate' : 'Activate'}
                    </Button>
                    {!st.is_main && (
                      <Button size="small" variant="destructive" disabled={busyStoreId === st.id} onClick={() => remove(st)}>
                        Remove
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
        <p style={{ fontSize: 13, fontWeight: 500, color: 'var(--fg-subtle)', textTransform: 'uppercase', letterSpacing: 0.5, margin: '0 0 12px' }}>Add store</p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 12, marginBottom: 12 }}>
          <Field label="Store name" required><Input value={draft.name} onChange={set('name')} placeholder="e.g. Branch #004 — Sinza" /></Field>
          <Field label="Location"><Input value={draft.address} onChange={set('address')} /></Field>
        </div>
        <Button onClick={addStore} disabled={saving}><Icon name="add" size={16} /> {saving ? 'Adding…' : 'Add store'}</Button>
      </Card>}
    </>
  )
}
