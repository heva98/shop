import { useMemo, useState } from 'react'
import { Button, Field, Icon, Input, Modal, NoticeBox, PageHeader, Radio, Select, Tag } from '../components/ds/index.js'
import { useApi } from '../hooks/useApi.js'
import { addShopOwner, listAllShops, registerShop, updateShop } from '../api/platform.js'
import { updateUser } from '../api/core.js'
import { BUSINESS_TYPE_OPTIONS } from '../appData.js'

const EMPTY_SHOP = {
  name: '', business_type: 'general', tin: '', phone: '', email: '', region: '', district: '', address: '',
  store_mode: 'single',
}
const EMPTY_OWNER = { first_name: '', last_name: '', username: '', phone: '', email: '', password: '', confirmPassword: '' }
const SHOP_FIELDS = Object.keys(EMPTY_SHOP)

const LABEL = {
  name: 'Shop name', business_type: 'Type of shop', tin: 'TIN', phone: 'Phone', email: 'Email', region: 'Region',
  district: 'District', address: 'Street / area', store_mode: 'Store setup', first_name: 'First name',
  last_name: 'Last name', username: 'Username', password: 'Password', owner: 'Owner',
}

function th() {
  return { textAlign: 'left', fontWeight: 600, fontSize: 11, lineHeight: '16px', textTransform: 'uppercase', letterSpacing: 1.2, color: 'var(--fg-subtle)', padding: '12px 16px', borderBottom: '1px solid var(--grey-300)' }
}
function td(color) {
  return { padding: '14px 16px', borderBottom: '1px solid var(--grey-300)', fontSize: 14, color: color || 'var(--grey-700)', verticalAlign: 'top' }
}

/** Flattens a DRF error body, including the nested {owner: {field: [msg]}}
 * of a registration, into readable lines. */
function errorLines(err) {
  const body = err?.body
  if (!body || typeof body !== 'object') return [err?.message || 'Request failed']
  const lines = []
  const walk = (obj, prefix) => {
    for (const [field, msgs] of Object.entries(obj)) {
      if (msgs && typeof msgs === 'object' && !Array.isArray(msgs)) { walk(msgs, 'Owner — '); continue }
      const text = Array.isArray(msgs) ? msgs.join(' ') : String(msgs)
      lines.push(field === 'detail' || field === 'non_field_errors' ? text : `${prefix}${LABEL[field] || field}: ${text}`)
    }
  }
  walk(body, '')
  return lines
}

function ownerProblems(owner, { needsPassword = true } = {}) {
  const problems = ['first_name', 'last_name', 'username'].filter((f) => !owner[f].trim()).map((f) => `Owner — ${LABEL[f]} is required.`)
  if (needsPassword && !owner.password) problems.push('Owner — Password is required.')
  if (owner.password !== owner.confirmPassword) problems.push('Owner — Passwords do not match.')
  return problems
}

const ownerPayload = ({ confirmPassword, ...owner }) => owner

export default function PlatformShops() {
  const { data: shops, loading, error: loadError, refetch } = useApi(() => listAllShops(), [])
  const [search, setSearch] = useState('')
  const [notice, setNotice] = useState(null)
  const [errors, setErrors] = useState([])
  const [busyId, setBusyId] = useState(null)
  // { kind: 'register' | 'edit' | 'owner' | 'password', shop?, owner? }
  const [dialog, setDialog] = useState(null)

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase()
    return (shops ?? []).filter((s) => !q || [s.name, s.region, s.district, s.phone, ...s.owners.map((o) => o.username)]
      .some((v) => (v || '').toLowerCase().includes(q)))
  }, [shops, search])

  const done = (text) => { setDialog(null); setNotice(text); setErrors([]); refetch() }

  async function toggleActive(shop) {
    const suspending = shop.is_active
    if (suspending && !window.confirm(`Suspend ${shop.name}? Everyone at this shop is signed out and cannot sign in until you reactivate it. Its data is kept.`)) return
    setBusyId(shop.id)
    setErrors([])
    setNotice(null)
    try {
      await updateShop(shop.id, { is_active: !suspending })
      setNotice(`${shop.name} ${suspending ? 'suspended' : 'reactivated'}.`)
      refetch()
    } catch (err) {
      setErrors(errorLines(err))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div>
      <PageHeader
        title="Shops"
        subtitle="Register shops and their owners. Each owner then adds their own sellers."
        actions={<Button variant="primary" onClick={() => { setNotice(null); setDialog({ kind: 'register' }) }}><Icon name="add" size={16} /> Register shop</Button>}
      />
      {errors.length > 0 && (
        <NoticeBox variant="error" title="Could not update the shop" style={{ marginBottom: 12 }}>
          {errors.map((e) => <div key={e}>{e}</div>)}
        </NoticeBox>
      )}
      {notice && <NoticeBox variant="valid" title={notice} style={{ marginBottom: 12 }} />}
      <div style={{ maxWidth: 320, marginBottom: 12 }}>
        <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search shop, place, phone or owner…" />
      </div>
      <div className="ds-table-card">
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 900 }}>
          <thead>
            <tr>
              <th style={th()}>Shop</th>
              <th style={th()}>Location</th>
              <th style={th()}>Owner</th>
              <th style={th()}>Stores · Staff</th>
              <th style={th()}>Status</th>
              <th style={th()}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td style={td()} colSpan={6}>Loading shops…</td></tr>}
            {loadError && <tr><td style={td('var(--red-600)')} colSpan={6}>Could not load shops: {loadError.message}</td></tr>}
            {!loading && !loadError && rows.length === 0 && (
              <tr><td style={td()} colSpan={6}>{search ? 'No shop matches.' : 'No shops yet. Register the first one.'}</td></tr>
            )}
            {rows.map((s) => (
              <tr key={s.id}>
                <td style={td('var(--grey-900)')}>
                  <div style={{ fontWeight: 500 }}>{s.name}</div>
                  <div style={{ fontSize: 12, color: 'var(--fg-subtle)' }}>{s.business_type_label}{s.phone ? ` · ${s.phone}` : ''}</div>
                </td>
                <td style={td()}>
                  {[s.district, s.region].filter(Boolean).join(', ') || '—'}
                  {s.address && <div style={{ fontSize: 12, color: 'var(--fg-subtle)' }}>{s.address}</div>}
                </td>
                <td style={td()}>
                  {s.owners.length === 0 && '—'}
                  {s.owners.map((o) => (
                    <div key={o.id} style={{ marginBottom: 6 }}>
                      <div>{[o.first_name, o.last_name].filter(Boolean).join(' ') || o.username}</div>
                      <div style={{ fontSize: 12, color: 'var(--fg-subtle)' }}>
                        {o.username}{o.phone ? ` · ${o.phone}` : ''}{!o.last_login && ' · never signed in'}
                        {' · '}
                        <button type="button" style={{ background: 'none', border: 0, padding: 0, color: 'var(--blue-700)', cursor: 'pointer', fontSize: 12 }}
                          onClick={() => { setNotice(null); setDialog({ kind: 'password', shop: s, owner: o }) }}>
                          Reset password
                        </button>
                      </div>
                    </div>
                  ))}
                </td>
                <td style={td()}>{s.store_count} · {s.staff_count}</td>
                <td style={td()}>{s.is_active ? <Tag variant="positive">Active</Tag> : <Tag variant="negative">Suspended</Tag>}</td>
                <td style={td()}>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    <Button size="small" onClick={() => { setNotice(null); setDialog({ kind: 'edit', shop: s }) }}>Edit</Button>
                    <Button size="small" onClick={() => { setNotice(null); setDialog({ kind: 'owner', shop: s }) }}>Add owner</Button>
                    <Button size="small" variant={s.is_active ? 'destructive' : undefined} disabled={busyId === s.id} onClick={() => toggleActive(s)}>
                      {s.is_active ? 'Suspend' : 'Reactivate'}
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {dialog?.kind === 'register' && <ShopDialog onClose={() => setDialog(null)} onDone={done} />}
      {dialog?.kind === 'edit' && <ShopDialog shop={dialog.shop} onClose={() => setDialog(null)} onDone={done} />}
      {dialog?.kind === 'owner' && <OwnerDialog shop={dialog.shop} onClose={() => setDialog(null)} onDone={done} />}
      {dialog?.kind === 'password' && <PasswordDialog owner={dialog.owner} onClose={() => setDialog(null)} onDone={done} />}
    </div>
  )
}

/** Shop details, plus the first owner when registering a new shop. */
function ShopDialog({ shop, onClose, onDone }) {
  const registering = !shop
  const [draft, setDraft] = useState(registering ? EMPTY_SHOP : Object.fromEntries(SHOP_FIELDS.map((f) => [f, shop[f] ?? ''])))
  const [owner, setOwner] = useState(EMPTY_OWNER)
  const [errors, setErrors] = useState([])
  const [saving, setSaving] = useState(false)
  const set = (field) => (e) => setDraft((d) => ({ ...d, [field]: e.target.value }))

  async function save() {
    const problems = draft.name.trim() ? [] : ['Shop name is required.']
    if (registering) problems.push(...ownerProblems(owner))
    setErrors(problems)
    if (problems.length) return
    setSaving(true)
    try {
      const data = { ...draft, name: draft.name.trim() }
      if (registering) {
        await registerShop({ ...data, owner: ownerPayload(owner) })
        onDone(`${data.name} registered. ${owner.username} can now sign in and add sellers.`)
      } else {
        await updateShop(shop.id, data)
        onDone(`${data.name} saved.`)
      }
    } catch (err) {
      setErrors(errorLines(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={registering ? 'Register shop' : `Edit ${shop.name}`}
      size="lg"
      onClose={onClose}
      footer={(
        <>
          <Button onClick={onClose} disabled={saving}>Cancel</Button>
          <Button variant="primary" onClick={save} disabled={saving}>{saving ? 'Saving…' : registering ? 'Register shop' : 'Save changes'}</Button>
        </>
      )}
    >
      {errors.length > 0 && (
        <NoticeBox variant="error" title="Could not save" style={{ marginBottom: 12 }}>
          {errors.map((e) => <div key={e}>{e}</div>)}
        </NoticeBox>
      )}
      <SectionTitle>Shop</SectionTitle>
      <div style={grid}>
        <Field label="Shop name" required><Input value={draft.name} onChange={set('name')} autoFocus /></Field>
        <Field label="Type of shop"><Select value={draft.business_type} onChange={set('business_type')} options={BUSINESS_TYPE_OPTIONS} /></Field>
        <Field label="TIN"><Input value={draft.tin} onChange={set('tin')} /></Field>
        <Field label="Phone"><Input value={draft.phone} onChange={set('phone')} placeholder="e.g. 0712 345 678" /></Field>
        <Field label="Email"><Input type="email" value={draft.email} onChange={set('email')} /></Field>
      </div>
      <SectionTitle>Location</SectionTitle>
      <div style={grid}>
        <Field label="Region"><Input value={draft.region} onChange={set('region')} placeholder="e.g. Dar es Salaam" /></Field>
        <Field label="District"><Input value={draft.district} onChange={set('district')} placeholder="e.g. Kinondoni" /></Field>
        <Field label="Street / area"><Input value={draft.address} onChange={set('address')} placeholder="e.g. Sinza, near the market" /></Field>
      </div>
      {registering && (
        <>
          <SectionTitle>Store setup</SectionTitle>
          <div style={{ display: 'flex', gap: 16, marginBottom: 16, flexWrap: 'wrap' }}>
            <Radio checked={draft.store_mode === 'single'} onChange={() => setDraft((d) => ({ ...d, store_mode: 'single' }))} label="Single shop" />
            <Radio checked={draft.store_mode === 'multi'} onChange={() => setDraft((d) => ({ ...d, store_mode: 'multi' }))} label="Shop with multiple branches" />
          </div>
          <SectionTitle>Owner</SectionTitle>
          <OwnerFields owner={owner} setOwner={setOwner} />
        </>
      )}
    </Modal>
  )
}

function OwnerDialog({ shop, onClose, onDone }) {
  const [owner, setOwner] = useState(EMPTY_OWNER)
  const [errors, setErrors] = useState([])
  const [saving, setSaving] = useState(false)

  async function save() {
    const problems = ownerProblems(owner)
    setErrors(problems)
    if (problems.length) return
    setSaving(true)
    try {
      await addShopOwner(shop.id, ownerPayload(owner))
      onDone(`${owner.username} added as an owner of ${shop.name}.`)
    } catch (err) {
      setErrors(errorLines(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={`Add owner — ${shop.name}`}
      onClose={onClose}
      footer={(
        <>
          <Button onClick={onClose} disabled={saving}>Cancel</Button>
          <Button variant="primary" onClick={save} disabled={saving}>{saving ? 'Adding…' : 'Add owner'}</Button>
        </>
      )}
    >
      {errors.length > 0 && (
        <NoticeBox variant="error" title="Could not add the owner" style={{ marginBottom: 12 }}>
          {errors.map((e) => <div key={e}>{e}</div>)}
        </NoticeBox>
      )}
      <OwnerFields owner={owner} setOwner={setOwner} />
    </Modal>
  )
}

function PasswordDialog({ owner, onClose, onDone }) {
  const [draft, setDraft] = useState({ password: '', confirmPassword: '' })
  const [errors, setErrors] = useState([])
  const [saving, setSaving] = useState(false)

  async function save() {
    const problems = []
    if (!draft.password) problems.push('Enter a new password.')
    else if (draft.password !== draft.confirmPassword) problems.push('Passwords do not match.')
    setErrors(problems)
    if (problems.length) return
    setSaving(true)
    try {
      await updateUser(owner.id, { password: draft.password })
      onDone(`Password of ${owner.username} reset.`)
    } catch (err) {
      setErrors(errorLines(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={`Reset password — ${owner.username}`}
      size="sm"
      onClose={onClose}
      footer={(
        <>
          <Button onClick={onClose} disabled={saving}>Cancel</Button>
          <Button variant="primary" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Reset password'}</Button>
        </>
      )}
    >
      {errors.length > 0 && (
        <NoticeBox variant="error" title="Could not reset the password" style={{ marginBottom: 12 }}>
          {errors.map((e) => <div key={e}>{e}</div>)}
        </NoticeBox>
      )}
      <div style={{ display: 'grid', gap: 12 }}>
        <Field label="New password" required>
          <Input type="password" value={draft.password} onChange={(e) => setDraft((d) => ({ ...d, password: e.target.value }))} autoFocus />
        </Field>
        <Field label="Confirm new password" required>
          <Input type="password" value={draft.confirmPassword} onChange={(e) => setDraft((d) => ({ ...d, confirmPassword: e.target.value }))} />
        </Field>
      </div>
      <p style={hint}>The owner is signed out everywhere and must choose their own password at their next sign-in.</p>
    </Modal>
  )
}

function OwnerFields({ owner, setOwner }) {
  const set = (field) => (e) => setOwner((o) => ({ ...o, [field]: e.target.value }))
  return (
    <>
      <div style={grid}>
        <Field label="First name" required><Input value={owner.first_name} onChange={set('first_name')} /></Field>
        <Field label="Last name" required><Input value={owner.last_name} onChange={set('last_name')} /></Field>
        <Field label="Mobile number"><Input value={owner.phone} onChange={set('phone')} placeholder="e.g. 0712 345 678" /></Field>
        <Field label="Email"><Input type="email" value={owner.email} onChange={set('email')} /></Field>
        <Field label="Username" required><Input value={owner.username} onChange={set('username')} /></Field>
        <Field label="Password" required><Input type="password" value={owner.password} onChange={set('password')} /></Field>
        <Field label="Confirm password" required><Input type="password" value={owner.confirmPassword} onChange={set('confirmPassword')} /></Field>
      </div>
      <p style={hint}>This password is temporary: the owner must choose their own the first time they sign in.</p>
    </>
  )
}

const grid = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(200px,1fr))', gap: 12, marginBottom: 16 }
const hint = { fontSize: 12, color: 'var(--fg-subtle)', margin: '4px 0 0' }

function SectionTitle({ children }) {
  return <p style={{ fontSize: 13, fontWeight: 500, color: 'var(--fg-subtle)', textTransform: 'uppercase', letterSpacing: 0.5, margin: '0 0 12px' }}>{children}</p>
}
