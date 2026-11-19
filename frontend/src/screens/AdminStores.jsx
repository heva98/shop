import { useState } from 'react'
import { Button, Card, DataTable, EmptyState, Field, Input, NoticeBox, Select, Tag } from '../components/ds/index.js'
import { useApi } from '../hooks/useApi.js'
import { useAuth } from '../auth/AuthContext.jsx'
import { createStore, deleteStore, listAllStores, updateStore } from '../api/core.js'
import { OUTLET_CLASS_OPTIONS, isPharmacy } from '../appData.js'
import { t, tOptions, useT } from '../i18n/index.js'

const FIELD_LABEL = { name: 'Store name', address: 'Location' }

const EMPTY_DRAFT = { name: '', address: '', outlet_class: '' }

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
  const [nameError, setNameError] = useState('')
  const [busyStoreId, setBusyStoreId] = useState(null)

  const set = (field) => (e) => setDraft((d) => ({ ...d, [field]: e.target.value }))
  // Single shop: its one store is created and kept by the server.
  const isSingle = auth.entity?.store_mode === 'single'
  const pharmacy = isPharmacy(auth.entity)

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

  const columns = [
    { key: 'name', header: t('Store'), primary: true, sortable: true },
    { key: 'address', header: t('Location'), sortable: true },
    pharmacy && {
      key: 'outlet_class', header: t('Licence'),
      cell: (st) => (
        <Select
          value={st.outlet_class} aria-label={t('Licence')} disabled={busyStoreId === st.id}
          onChange={(e) => run(st.id, () => updateStore(st.id, { outlet_class: e.target.value }), t('Licence saved.'))}
          options={tOptions(OUTLET_CLASS_OPTIONS)}
        />
      ),
    },
    {
      key: 'is_main', header: t('Role'), sortable: true, firstDirection: 'desc',
      cell: (st) => (st.is_main ? <Tag variant="neutral">{t('Main store')}</Tag> : <Tag>{t('Branch')}</Tag>),
    },
    {
      key: 'is_active', header: t('Status'), sortable: true, firstDirection: 'desc',
      cell: (st) => (st.is_active ? <Tag variant="positive">{t('Active')}</Tag> : <Tag variant="negative">{t('Inactive')}</Tag>),
    },
    {
      key: 'actions', header: t('Actions'),
      cell: (st) => (isSingle && st.is_active ? '—' : (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', justifyContent: 'inherit' }}>
          <Button size="small" disabled={busyStoreId === st.id} onClick={() => toggleActive(st)}>
            {st.is_active ? t('Deactivate') : t('Activate')}
          </Button>
          {!st.is_main && (
            <Button size="small" variant="destructive" disabled={busyStoreId === st.id} onClick={() => remove(st)}>
              {t('Remove')}
            </Button>
          )}
        </div>
      )),
    },
  ].filter(Boolean)

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
      setNameError(t('Store name is required.'))
      return
    }
    setNameError('')
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
      <DataTable
        caption={t('Stores')}
        columns={columns}
        rows={stores}
        loading={loading}
        error={loadError}
        onRetry={refetch}
        empty={<EmptyState icon="store" title={t('No stores yet.')} />}
        minWidth={720}
        style={{ marginBottom: 16 }}
      />
      {!isSingle && <Card>
        <p style={{ fontSize: 13, fontWeight: 500, color: 'var(--fg-subtle)', textTransform: 'uppercase', letterSpacing: 0.5, margin: '0 0 12px' }}>{t('Add store')}</p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 12, marginBottom: 12 }}>
          <Field label={t('Store name')} required error={nameError}>
            <Input value={draft.name} onChange={(e) => { set('name')(e); if (nameError) setNameError('') }} placeholder={t('e.g. Branch #004 — Sinza')} autoComplete="off" />
          </Field>
          <Field label={t('Location')}><Input value={draft.address} onChange={set('address')} /></Field>
          {pharmacy && <Field label={t('Licence')}><Select value={draft.outlet_class} onChange={set('outlet_class')} options={tOptions(OUTLET_CLASS_OPTIONS)} /></Field>}
        </div>
        <Button icon="add" loading={saving} onClick={addStore}>{t('Add store')}</Button>
      </Card>}
    </>
  )
}
