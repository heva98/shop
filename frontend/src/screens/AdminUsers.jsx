import { useMemo, useState } from 'react'
import { Button, Card, Field, Icon, Input, NoticeBox, Radio, Select, Tag } from '../components/ds/index.js'
import { useApi } from '../hooks/useApi.js'
import { useAuth } from '../auth/AuthContext.jsx'
import {
  createStoreRole, createUser, deleteStoreRole, listAllStoreRoles, listAllStores, listAllUsers, updateUser,
} from '../api/core.js'
import { GENDER_OPTIONS, ROLE_LABEL } from '../appData.js'

// Owners (entity_admin) are appointed by the platform administrator, not here.
const ROLES = ['cashier', 'storekeeper', 'store_manager']
const isOwner = (row) => row.roles.some((r) => r.role === 'entity_admin')

const EMPTY_DRAFT = {
  username: '', password: '', confirmPassword: '', first_name: '', middle_name: '', last_name: '',
  gender: '', date_of_birth: '', email: '', phone: '', role: 'cashier', store: '',
}
const PROFILE_FIELDS = ['username', 'first_name', 'middle_name', 'last_name', 'gender', 'date_of_birth', 'email', 'phone']
const REQUIRED = {
  username: 'Username', password: 'Password', first_name: 'First name', last_name: 'Last name',
  gender: 'Gender', date_of_birth: 'Date of birth',
}

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
    return field === 'detail' || field === 'non_field_errors' ? text : `${REQUIRED[field] || field}: ${text}`
  })
}

export default function AdminUsers() {
  const auth = useAuth()
  const { data: users, loading, error: loadError, refetch: refetchUsers } = useApi(() => listAllUsers(), [])
  const { data: storeRoles, refetch: refetchRoles } = useApi(() => listAllStoreRoles(), [])
  const { data: stores } = useApi(() => listAllStores(), [])

  const [draft, setDraft] = useState(EMPTY_DRAFT)
  const [errors, setErrors] = useState([])
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState(null)
  const [showForm, setShowForm] = useState(false)
  // null = creating a new user; otherwise the row being edited.
  const [editing, setEditing] = useState(null)
  const [busyUserId, setBusyUserId] = useState(null)

  const set = (field) => (e) => setDraft((d) => ({ ...d, [field]: e.target.value }))
  const needsStore = draft.role !== 'entity_admin'
  // Single shop: every staff role goes to its one store, so there's
  // nothing to pick (the server assigns it too if store is left out).
  const isSingle = auth.entity?.store_mode === 'single'
  const singleStoreId = isSingle ? (stores ?? []).find((s) => s.is_active)?.id ?? null : null
  // Role/store can be changed from this form only while the user holds at
  // most one StoreRole — multi-store staff would lose their other roles.
  const canEditRole = !editing || (editing.roles.length <= 1 && !isOwner(editing))

  const rows = useMemo(() => {
    const storeName = Object.fromEntries((stores ?? []).map((s) => [s.id, s.name]))
    const rolesByUser = {}
    for (const sr of storeRoles ?? []) (rolesByUser[sr.user] ||= []).push(sr)
    return (users ?? []).map((u) => ({
      ...u,
      fullName: [u.first_name, u.middle_name, u.last_name].filter(Boolean).join(' ') || u.username,
      roles: (rolesByUser[u.id] ?? []).map((sr) => ({
        id: sr.id,
        role: sr.role,
        store: sr.store,
        label: ROLE_LABEL[sr.role] || sr.role,
        scope: sr.store ? storeName[sr.store] ?? '—' : 'All stores',
      })),
    }))
  }, [users, storeRoles, stores])

  function closeForm() {
    setShowForm(false)
    setEditing(null)
    setDraft(EMPTY_DRAFT)
    setErrors([])
  }

  function openCreate() {
    setEditing(null)
    setDraft(EMPTY_DRAFT)
    setErrors([])
    setNotice(null)
    setShowForm(true)
  }

  function openEdit(row) {
    const current = row.roles[0]
    setEditing(row)
    setDraft({
      ...EMPTY_DRAFT,
      ...Object.fromEntries(PROFILE_FIELDS.map((f) => [f, row[f] ?? ''])),
      role: current?.role ?? 'cashier',
      store: current?.store ?? '',
    })
    setErrors([])
    setNotice(null)
    setShowForm(true)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  async function toggleActive(row) {
    const disabling = row.is_active
    if (disabling && !window.confirm(`Disable ${row.fullName}? They will no longer be able to sign in.`)) return
    setBusyUserId(row.id)
    setErrors([])
    setNotice(null)
    try {
      await updateUser(row.id, { is_active: !disabling })
      setNotice(`${row.fullName} ${disabling ? 'disabled' : 'enabled'}.`)
      refetchUsers()
    } catch (err) {
      setErrors(errorLines(err))
    } finally {
      setBusyUserId(null)
    }
  }

  async function syncRole(userId, existingRoles) {
    const current = existingRoles[0]
    const store = needsStore ? (isSingle ? singleStoreId : draft.store) : null
    if (current && current.role === draft.role && (current.store ?? null) === store) return
    // Create the new role first so a failure never leaves the user role-less.
    await createStoreRole({ user: userId, store, role: draft.role })
    for (const r of existingRoles) await deleteStoreRole(r.id)
  }

  async function submit() {
    const required = editing ? Object.entries(REQUIRED).filter(([f]) => f !== 'password') : Object.entries(REQUIRED)
    const problems = required.filter(([f]) => !String(draft[f] ?? '').trim()).map(([, label]) => `${label} is required.`)
    if (draft.password && draft.password !== draft.confirmPassword) problems.push('Passwords do not match.')
    if (canEditRole && needsStore && !isSingle && !draft.store) problems.push('Store is required for this role.')
    setErrors(problems)
    setNotice(null)
    if (problems.length) return

    setSaving(true)
    try {
      const { confirmPassword, role, store, password, ...profile } = draft
      const payload = password ? { ...profile, password } : profile
      const user = editing ? await updateUser(editing.id, payload) : await createUser(payload)
      try {
        if (canEditRole) await syncRole(user.id, editing ? editing.roles : [])
      } catch (err) {
        setErrors([`User "${user.username}" was saved, but updating the role failed:`, ...errorLines(err)])
      }
      setNotice(editing ? `User "${user.username}" updated.` : `User "${user.username}" created.`)
      closeForm()
      refetchUsers()
      refetchRoles()
    } catch (err) {
      setErrors(errorLines(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      {!showForm && (
        <div style={{ marginBottom: 12 }}>
          <Button variant="primary" onClick={openCreate}><Icon name="add" size={16} /> Add user</Button>
        </div>
      )}
      {errors.length > 0 && (
        <NoticeBox variant="error" title="Could not save user" style={{ marginBottom: 12 }}>
          {errors.map((e) => <div key={e}>{e}</div>)}
        </NoticeBox>
      )}
      {notice && <NoticeBox variant="valid" title={notice} style={{ marginBottom: 12 }} />}
      {showForm && (
        <div style={{ marginBottom: 16 }}>
          <Card>
            <p style={{ fontSize: 13, fontWeight: 500, color: 'var(--fg-subtle)', textTransform: 'uppercase', letterSpacing: 0.5, margin: '0 0 12px' }}>
              {editing ? `Edit user — ${editing.fullName}` : 'Create user'}
            </p>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 12, marginBottom: 12 }}>
              <Field label="First name" required><Input value={draft.first_name} onChange={set('first_name')} /></Field>
              <Field label="Middle name"><Input value={draft.middle_name} onChange={set('middle_name')} /></Field>
              <Field label="Last name" required><Input value={draft.last_name} onChange={set('last_name')} /></Field>
              <Field label="Gender" required><Select value={draft.gender} onChange={set('gender')} options={GENDER_OPTIONS} /></Field>
              <Field label="Date of birth" required><Input type="date" value={draft.date_of_birth} onChange={set('date_of_birth')} /></Field>
              <Field label="Email"><Input type="email" value={draft.email} onChange={set('email')} /></Field>
              <Field label="Mobile number"><Input value={draft.phone} onChange={set('phone')} placeholder="e.g. 0712 345 678" /></Field>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 12, marginBottom: 12 }}>
              <Field label="Username" required><Input value={draft.username} onChange={set('username')} /></Field>
              <Field label={editing ? 'New password' : 'Password'} required={!editing}>
                <Input type="password" value={draft.password} onChange={set('password')} placeholder={editing ? 'Leave blank to keep current' : undefined} />
              </Field>
              <Field label={editing ? 'Confirm new password' : 'Confirm password'} required={!editing}>
                <Input type="password" value={draft.confirmPassword} onChange={set('confirmPassword')} />
              </Field>
            </div>
            <p style={{ fontSize: 12, color: 'var(--fg-subtle)', margin: '-4px 0 12px' }}>
              A password you set here is temporary: the user must choose their own the next time they sign in
              {editing ? ', and setting it signs them out of every device now' : ''}.
            </p>
            {canEditRole ? (
              <>
                <div style={{ display: 'flex', gap: 16, marginBottom: 12, flexWrap: 'wrap' }}>
                  {ROLES.map((r) => (
                    <Radio key={r} checked={draft.role === r} onChange={() => setDraft((d) => ({ ...d, role: r }))} label={ROLE_LABEL[r]} />
                  ))}
                </div>
                {needsStore && !isSingle && (
                  <Field label="Store" required style={{ maxWidth: 320, marginBottom: 16 }}>
                    <Select
                      value={draft.store}
                      onChange={set('store')}
                      options={[{ value: '', label: 'Select store…' }, ...(stores ?? []).map((s) => ({ value: s.id, label: s.name }))]}
                    />
                  </Field>
                )}
              </>
            ) : (
              <p style={{ fontSize: 13, color: 'var(--fg-subtle)', margin: '0 0 16px' }}>
                {isOwner(editing)
                  ? 'Owners are appointed by the system administrator, so this role can’t be changed here.'
                  : 'This user holds roles at several stores, so roles can’t be changed from this form.'}
              </p>
            )}
            <div style={{ display: 'flex', gap: 8 }}>
              <Button variant="primary" onClick={submit} disabled={saving}>
                {saving ? 'Saving…' : editing ? 'Save changes' : 'Create user'}
              </Button>
              <Button onClick={closeForm} disabled={saving}>Cancel</Button>
            </div>
          </Card>
        </div>
      )}

      {!showForm && (
        <div className="ds-table-card" style={{ marginBottom: 16 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 820 }}>
            <thead>
              <tr>
                <th style={th()}>Name</th>
                <th style={th()}>Username</th>
                <th style={th()}>Role · Store scope</th>
                <th style={th()}>Status</th>
                <th style={th()}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading && <tr><td style={td()} colSpan={5}>Loading users…</td></tr>}
              {loadError && <tr><td style={td('var(--red-600)')} colSpan={5}>Could not load users: {loadError.message}</td></tr>}
              {rows.map((u) => {
                const isSelf = u.id === auth.profile?.id
                // Another owner's account is the system administrator's to change.
                const locked = !isSelf && isOwner(u)
                return (
                  <tr key={u.id}>
                    <td style={td('var(--grey-900)')}>{u.fullName}</td>
                    <td style={td()}>{u.username}</td>
                    <td style={td()}>
                      {u.roles.length === 0 && '—'}
                      {u.roles.map((r) => <div key={r.id} style={{ marginBottom: 4 }}><Tag>{r.label}</Tag> {r.scope}</div>)}
                    </td>
                    <td style={td()}>
                      {u.is_active ? <Tag variant="positive">Active</Tag> : <Tag variant="negative">Disabled</Tag>}
                    </td>
                    <td style={td()}>
                      {locked ? <span style={{ fontSize: 13, color: 'var(--fg-subtle)' }}>Managed by the system administrator</span> : (
                      <div style={{ display: 'flex', gap: 6 }}>
                        <Button size="small" onClick={() => openEdit(u)}>Edit</Button>
                        {!isSelf && (
                          <Button
                            size="small"
                            variant={u.is_active ? 'destructive' : undefined}
                            disabled={busyUserId === u.id}
                            onClick={() => toggleActive(u)}
                          >
                            {u.is_active ? 'Disable' : 'Enable'}
                          </Button>
                        )}
                      </div>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
