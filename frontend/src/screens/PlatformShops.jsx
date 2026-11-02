import { useMemo, useState } from 'react'
import { Button, Field, Icon, Input, Modal, NoticeBox, PageHeader, Radio, Select, Tag } from '../components/ds/index.js'
import { useApi } from '../hooks/useApi.js'
import LocationFields, { TANZANIA, countryName } from '../components/LocationFields.jsx'
import { addShopOwner, listAllShops, registerShop, updateShop } from '../api/platform.js'
import { updateUser } from '../api/core.js'
import { BUSINESS_TYPE_OPTIONS } from '../appData.js'
import { t, tOptions, useLanguage, useT } from '../i18n/index.js'
import { PHONE_DIGITS, phoneInput } from '../lib/phone.js'

const EMPTY_SHOP = {
  name: '', business_type: 'general', tin: '', phone: '', email: '', country: 'TZ', region: '', council: '', address: '',
  store_mode: 'single',
}
const EMPTY_OWNER = { first_name: '', last_name: '', username: '', phone: '', email: '', daily_sms_time: '', password: '', confirmPassword: '' }
const SHOP_FIELDS = Object.keys(EMPTY_SHOP)

const LABEL = {
  name: 'Shop name', business_type: 'Type of shop', tin: 'TIN', phone: 'Phone', email: 'Email', region: 'Region',
  country: 'Country', council: 'Council', address: 'Street / area', store_mode: 'Store setup', first_name: 'First name',
  last_name: 'Last name', username: 'Username', password: 'Password', owner: 'Owner', daily_sms_time: 'Daily sales SMS time',
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
  if (!body || typeof body !== 'object') return [err?.message || t('Request failed')]
  const lines = []
  const walk = (obj, prefix) => {
    for (const [field, msgs] of Object.entries(obj)) {
      if (msgs && typeof msgs === 'object' && !Array.isArray(msgs)) { walk(msgs, `${t('Owner')} — `); continue }
      const text = Array.isArray(msgs) ? msgs.join(' ') : String(msgs)
      lines.push(field === 'detail' || field === 'non_field_errors' ? text : `${prefix}${LABEL[field] ? t(LABEL[field]) : field}: ${text}`)
    }
  }
  walk(body, '')
  return lines
}

function ownerProblems(owner, { needsPassword = true } = {}) {
  const problems = ['first_name', 'last_name', 'username'].filter((f) => !owner[f].trim()).map((f) => `${t('Owner')} — ${t('{field} is required.', { field: t(LABEL[f]) })}`)
  if (needsPassword && !owner.password) problems.push(`${t('Owner')} — ${t('{field} is required.', { field: t('Password') })}`)
  if (owner.password !== owner.confirmPassword) problems.push(`${t('Owner')} — ${t('Passwords do not match.')}`)
  return problems
}

const ownerPayload = ({ confirmPassword, ...owner }) => ({ ...owner, daily_sms_time: owner.daily_sms_time || null })

/** "18:00:00" → "18:00"; blank → the server's DAILY_SUMMARY_TIME. */
const smsTimeLabel = (value) => (value ? value.slice(0, 5) : t('default time'))

export default function PlatformShops() {
  useT()
  const lang = useLanguage()
  const { data: shops, loading, error: loadError, refetch } = useApi(() => listAllShops(), [])
  const [search, setSearch] = useState('')
  const [notice, setNotice] = useState(null)
  const [errors, setErrors] = useState([])
  const [busyId, setBusyId] = useState(null)
  // { kind: 'register' | 'edit' | 'owner' | 'password' | 'smsTime', shop?, owner? }
  const [dialog, setDialog] = useState(null)

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase()
    return (shops ?? []).filter((s) => !q || [s.name, s.region, s.council, s.phone, ...s.owners.map((o) => o.username)]
      .some((v) => (v || '').toLowerCase().includes(q)))
  }, [shops, search])

  const done = (text) => { setDialog(null); setNotice(text); setErrors([]); refetch() }

  async function toggleActive(shop) {
    const suspending = shop.is_active
    if (suspending && !window.confirm(t('Suspend {name}? Everyone at this shop is signed out and cannot sign in until you reactivate it. Its data is kept.', { name: shop.name }))) return
    setBusyId(shop.id)
    setErrors([])
    setNotice(null)
    try {
      await updateShop(shop.id, { is_active: !suspending })
      setNotice(t(suspending ? '{name} suspended.' : '{name} reactivated.', { name: shop.name }))
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
        title={t('Shops')}
        subtitle={t('Register shops and their owners. Each owner then adds their own sellers.')}
        actions={<Button variant="primary" onClick={() => { setNotice(null); setDialog({ kind: 'register' }) }}><Icon name="add" size={16} /> {t('Register shop')}</Button>}
      />
      {errors.length > 0 && (
        <NoticeBox variant="error" title={t('Could not update the shop')} style={{ marginBottom: 12 }}>
          {errors.map((e) => <div key={e}>{e}</div>)}
        </NoticeBox>
      )}
      {notice && <NoticeBox variant="valid" title={notice} style={{ marginBottom: 12 }} />}
      <div style={{ maxWidth: 320, marginBottom: 12 }}>
        <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t('Search shop, place, phone or owner…')} />
      </div>
      <div className="ds-table-card">
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 900 }}>
          <thead>
            <tr>
              <th style={th()}>{t('Shop')}</th>
              <th style={th()}>{t('Location')}</th>
              <th style={th()}>{t('Owner')}</th>
              <th style={th()}>Stores · Staff</th>
              <th style={th()}>{t('Status')}</th>
              <th style={th()}>{t('Actions')}</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td style={td()} colSpan={6}>{t('Loading shops…')}</td></tr>}
            {loadError && <tr><td style={td('var(--red-600)')} colSpan={6}>{t('Could not load shops:')} {loadError.message}</td></tr>}
            {!loading && !loadError && rows.length === 0 && (
              <tr><td style={td()} colSpan={6}>{search ? t('No shop matches.') : t('No shops yet. Register the first one.')}</td></tr>
            )}
            {rows.map((s) => (
              <tr key={s.id}>
                <td style={td('var(--grey-900)')}>
                  <div style={{ fontWeight: 500 }}>{s.name}</div>
                  <div style={{ fontSize: 12, color: 'var(--fg-subtle)' }}>{t(s.business_type_label)}{s.phone ? ` · ${s.phone}` : ''}</div>
                </td>
                <td style={td()}>
                  {[s.council, s.region, s.country !== TANZANIA && countryName(s.country, lang)].filter(Boolean).join(', ') || '—'}
                  {s.address && <div style={{ fontSize: 12, color: 'var(--fg-subtle)' }}>{s.address}</div>}
                </td>
                <td style={td()}>
                  {s.owners.length === 0 && '—'}
                  {s.owners.map((o) => (
                    <div key={o.id} style={{ marginBottom: 6 }}>
                      <div>{[o.first_name, o.last_name].filter(Boolean).join(' ') || o.username}</div>
                      <div style={{ fontSize: 12, color: 'var(--fg-subtle)' }}>
                        {o.username}{o.phone ? ` · ${o.phone}` : ''}{!o.last_login && ` · ${t('never signed in')}`}
                        {' · '}
                        <button type="button" style={{ background: 'none', border: 0, padding: 0, color: 'var(--blue-700)', cursor: 'pointer', fontSize: 12 }}
                          onClick={() => { setNotice(null); setDialog({ kind: 'password', shop: s, owner: o }) }}>
                          {t('Reset password')}
                        </button>
                      </div>
                      <div style={{ fontSize: 12, color: 'var(--fg-subtle)' }}>
                        {t('Daily sales SMS at {time}', { time: smsTimeLabel(o.daily_sms_time) })}
                        {' · '}
                        <button type="button" style={{ background: 'none', border: 0, padding: 0, color: 'var(--blue-700)', cursor: 'pointer', fontSize: 12 }}
                          onClick={() => { setNotice(null); setDialog({ kind: 'smsTime', shop: s, owner: o }) }}>
                          {t('Change')}
                        </button>
                      </div>
                    </div>
                  ))}
                </td>
                <td style={td()}>{s.store_count} · {s.staff_count}</td>
                <td style={td()}>{s.is_active ? <Tag variant="positive">{t('Active')}</Tag> : <Tag variant="negative">{t('Suspended')}</Tag>}</td>
                <td style={td()}>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    <Button size="small" onClick={() => { setNotice(null); setDialog({ kind: 'edit', shop: s }) }}>{t('Edit')}</Button>
                    <Button size="small" onClick={() => { setNotice(null); setDialog({ kind: 'owner', shop: s }) }}>{t('Add owner')}</Button>
                    <Button size="small" variant={s.is_active ? 'destructive' : undefined} disabled={busyId === s.id} onClick={() => toggleActive(s)}>
                      {s.is_active ? t('Suspend') : t('Reactivate')}
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
      {dialog?.kind === 'smsTime' && <SmsTimeDialog owner={dialog.owner} onClose={() => setDialog(null)} onDone={done} />}
    </div>
  )
}

/** Shop details, plus the first owner when registering a new shop. */
function ShopDialog({ shop, onClose, onDone }) {
  useT()
  const registering = !shop
  const [draft, setDraft] = useState(registering ? EMPTY_SHOP : Object.fromEntries(SHOP_FIELDS.map((f) => [f, shop[f] ?? ''])))
  const [owner, setOwner] = useState(EMPTY_OWNER)
  const [errors, setErrors] = useState([])
  const [saving, setSaving] = useState(false)
  const set = (field) => (e) => setDraft((d) => ({ ...d, [field]: e.target.value }))

  async function save() {
    const problems = draft.name.trim() ? [] : [t('Shop name is required.')]
    if (registering) problems.push(...ownerProblems(owner))
    setErrors(problems)
    if (problems.length) return
    setSaving(true)
    try {
      const data = { ...draft, name: draft.name.trim() }
      if (registering) {
        await registerShop({ ...data, owner: ownerPayload(owner) })
        onDone(t('{name} registered. {user} can now sign in and add sellers.', { name: data.name, user: owner.username }))
      } else {
        await updateShop(shop.id, data)
        onDone(t('{name} saved.', { name: data.name }))
      }
    } catch (err) {
      setErrors(errorLines(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={registering ? t('Register shop') : t('Edit {name}', { name: shop.name })}
      size="lg"
      onClose={onClose}
      footer={(
        <>
          <Button onClick={onClose} disabled={saving}>{t('Cancel')}</Button>
          <Button variant="primary" onClick={save} disabled={saving}>{saving ? t('Saving…') : registering ? t('Register shop') : t('Save changes')}</Button>
        </>
      )}
    >
      {errors.length > 0 && (
        <NoticeBox variant="error" title={t('Could not save')} style={{ marginBottom: 12 }}>
          {errors.map((e) => <div key={e}>{e}</div>)}
        </NoticeBox>
      )}
      <SectionTitle>{t('Shop')}</SectionTitle>
      <div style={grid}>
        <Field label={t('Shop name')} required><Input value={draft.name} onChange={set('name')} autoFocus /></Field>
        <Field label={t('Type of shop')}><Select value={draft.business_type} onChange={set('business_type')} options={tOptions(BUSINESS_TYPE_OPTIONS)} /></Field>
        <Field label={t('TIN')}><Input value={draft.tin} onChange={set('tin')} /></Field>
        <Field label={t('Phone')}><Input value={draft.phone} onChange={set('phone')} placeholder={t('e.g. 0712 345 678')} /></Field>
        <Field label={t('Email')}><Input type="email" value={draft.email} onChange={set('email')} /></Field>
      </div>
      <SectionTitle>{t('Location')}</SectionTitle>
      <div style={grid}>
        <LocationFields country={draft.country} region={draft.region} council={draft.council} onChange={(loc) => setDraft((d) => ({ ...d, ...loc }))} />
        <Field label={t('Street / area')}><Input value={draft.address} onChange={set('address')} placeholder={t('e.g. Sinza, near the market')} /></Field>
      </div>
      {registering && (
        <>
          <SectionTitle>{t('Store setup')}</SectionTitle>
          <div style={{ display: 'flex', gap: 16, marginBottom: 16, flexWrap: 'wrap' }}>
            <Radio checked={draft.store_mode === 'single'} onChange={() => setDraft((d) => ({ ...d, store_mode: 'single' }))} label={t('Single shop')} />
            <Radio checked={draft.store_mode === 'multi'} onChange={() => setDraft((d) => ({ ...d, store_mode: 'multi' }))} label={t('Shop with multiple branches')} />
          </div>
          <SectionTitle>{t('Owner')}</SectionTitle>
          <OwnerFields owner={owner} setOwner={setOwner} />
        </>
      )}
    </Modal>
  )
}

function OwnerDialog({ shop, onClose, onDone }) {
  useT()
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
      onDone(t('{user} added as an owner of {name}.', { user: owner.username, name: shop.name }))
    } catch (err) {
      setErrors(errorLines(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={`${t('Add owner')} — ${shop.name}`}
      onClose={onClose}
      footer={(
        <>
          <Button onClick={onClose} disabled={saving}>{t('Cancel')}</Button>
          <Button variant="primary" onClick={save} disabled={saving}>{saving ? t('Adding…') : t('Add owner')}</Button>
        </>
      )}
    >
      {errors.length > 0 && (
        <NoticeBox variant="error" title={t('Could not add the owner')} style={{ marginBottom: 12 }}>
          {errors.map((e) => <div key={e}>{e}</div>)}
        </NoticeBox>
      )}
      <OwnerFields owner={owner} setOwner={setOwner} />
    </Modal>
  )
}

function PasswordDialog({ owner, onClose, onDone }) {
  useT()
  const [draft, setDraft] = useState({ password: '', confirmPassword: '' })
  const [errors, setErrors] = useState([])
  const [saving, setSaving] = useState(false)

  async function save() {
    const problems = []
    if (!draft.password) problems.push(t('Enter a new password.'))
    else if (draft.password !== draft.confirmPassword) problems.push(t('Passwords do not match.'))
    setErrors(problems)
    if (problems.length) return
    setSaving(true)
    try {
      await updateUser(owner.id, { password: draft.password })
      onDone(t('Password of {user} reset.', { user: owner.username }))
    } catch (err) {
      setErrors(errorLines(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={`${t('Reset password')} — ${owner.username}`}
      size="sm"
      onClose={onClose}
      footer={(
        <>
          <Button onClick={onClose} disabled={saving}>{t('Cancel')}</Button>
          <Button variant="primary" onClick={save} disabled={saving}>{saving ? t('Saving…') : t('Reset password')}</Button>
        </>
      )}
    >
      {errors.length > 0 && (
        <NoticeBox variant="error" title={t('Could not reset the password')} style={{ marginBottom: 12 }}>
          {errors.map((e) => <div key={e}>{e}</div>)}
        </NoticeBox>
      )}
      <div style={{ display: 'grid', gap: 12 }}>
        <Field label={t('New password')} required>
          <Input type="password" value={draft.password} onChange={(e) => setDraft((d) => ({ ...d, password: e.target.value }))} autoFocus />
        </Field>
        <Field label={t('Confirm new password')} required>
          <Input type="password" value={draft.confirmPassword} onChange={(e) => setDraft((d) => ({ ...d, confirmPassword: e.target.value }))} />
        </Field>
      </div>
      <p style={hint}>{t('The owner is signed out everywhere and must choose their own password at their next sign-in.')}</p>
    </Modal>
  )
}

/** When this owner gets the daily sales SMS. The summary job runs every
 * 5 minutes, so the server only takes times on a 5-minute mark. */
function SmsTimeDialog({ owner, onClose, onDone }) {
  useT()
  const [value, setValue] = useState(owner.daily_sms_time ? owner.daily_sms_time.slice(0, 5) : '')
  const [errors, setErrors] = useState([])
  const [saving, setSaving] = useState(false)

  async function save(time) {
    setSaving(true)
    setErrors([])
    try {
      await updateUser(owner.id, { daily_sms_time: time || null })
      onDone(time
        ? t('{user} gets the daily sales SMS at {time}.', { user: owner.username, time })
        : t('{user} gets the daily sales SMS at the default time.', { user: owner.username }))
    } catch (err) {
      setErrors(errorLines(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={`${t('Daily sales SMS time')} — ${owner.username}`}
      size="sm"
      onClose={onClose}
      footer={(
        <>
          <Button onClick={onClose} disabled={saving}>{t('Cancel')}</Button>
          {owner.daily_sms_time && <Button onClick={() => save(null)} disabled={saving}>{t('Use the default time')}</Button>}
          <Button variant="primary" onClick={() => save(value)} disabled={saving || !value}>{saving ? t('Saving…') : t('Save changes')}</Button>
        </>
      )}
    >
      {errors.length > 0 && (
        <NoticeBox variant="error" title={t('Could not save')} style={{ marginBottom: 12 }}>
          {errors.map((e) => <div key={e}>{e}</div>)}
        </NoticeBox>
      )}
      <Field label={t('Daily sales SMS time')}>
        <Input type="time" step={300} value={value} onChange={(e) => setValue(e.target.value)} />
      </Field>
      <p style={hint}>{t("The SMS covers that day's sales up to the time it is sent. Pick a time on a 5-minute mark, e.g. 20:00 or 20:05.")}</p>
    </Modal>
  )
}

function OwnerFields({ owner, setOwner }) {
  useT()
  const set = (field) => (e) => setOwner((o) => ({ ...o, [field]: e.target.value }))
  return (
    <>
      <div style={grid}>
        <Field label={t('First name')} required><Input value={owner.first_name} onChange={set('first_name')} /></Field>
        <Field label={t('Last name')} required><Input value={owner.last_name} onChange={set('last_name')} /></Field>
        <Field label={t('Mobile number')}><Input value={owner.phone} onChange={(e) => setOwner((o) => ({ ...o, phone: phoneInput(e.target.value) }))} inputMode="numeric" maxLength={PHONE_DIGITS} placeholder={t('e.g. 0712 345 678')} /></Field>
        <Field label={t('Email')}><Input type="email" value={owner.email} onChange={set('email')} /></Field>
        <Field label={t('Daily sales SMS time')}><Input type="time" step={300} value={owner.daily_sms_time} onChange={set('daily_sms_time')} /></Field>
        <Field label={t('Username')} required><Input value={owner.username} onChange={set('username')} /></Field>
        <Field label={t('Password')} required><Input type="password" value={owner.password} onChange={set('password')} /></Field>
        <Field label={t('Confirm password')} required><Input type="password" value={owner.confirmPassword} onChange={set('confirmPassword')} /></Field>
      </div>
      <p style={hint}>{t('Leave the SMS time blank to use the default time.')} {t('This password is temporary: the owner must choose their own the first time they sign in.')}</p>
    </>
  )
}

const grid = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(200px,1fr))', gap: 12, marginBottom: 16 }
const hint = { fontSize: 12, color: 'var(--fg-subtle)', margin: '4px 0 0' }

function SectionTitle({ children }) {
  return <p style={{ fontSize: 13, fontWeight: 500, color: 'var(--fg-subtle)', textTransform: 'uppercase', letterSpacing: 0.5, margin: '0 0 12px' }}>{children}</p>
}
