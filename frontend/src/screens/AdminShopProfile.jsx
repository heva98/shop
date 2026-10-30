import { useEffect, useRef, useState } from 'react'
import { Button, Card, Field, Input, NoticeBox, Radio, Select } from '../components/ds/index.js'
import { BUSINESS_TYPE_OPTIONS } from '../appData.js'
import { useAuth } from '../auth/AuthContext.jsx'
import { updateEntity, updateEntityLogo } from '../api/core.js'

/** Flattens a DRF error body ({field: [msg]} / {detail}) into readable lines. */
function errorLines(err) {
  const body = err?.body
  if (!body || typeof body !== 'object') return [err?.message || 'Request failed']
  return Object.entries(body).map(([field, msgs]) => {
    const text = Array.isArray(msgs) ? msgs.join(' ') : String(msgs)
    return field === 'detail' || field === 'non_field_errors' || field === 'store_mode' ? text : `${field}: ${text}`
  })
}

// Type, contact and location: set at registration, kept up to date by the owner.
const DETAIL_FIELDS = ['business_type', 'phone', 'email', 'region', 'district', 'address']
const detailsOf = (entity) => Object.fromEntries(DETAIL_FIELDS.map((f) => [f, entity?.[f] ?? '']))

const STORE_MODE_OPTIONS = [
  { value: 'single', label: 'Single shop', hint: 'One premises. Staff are assigned to it automatically and stores stay out of the way.' },
  { value: 'multi', label: 'Shop with multiple branches', hint: 'Add branches under Stores and choose which store each staff member works at.' },
]

export default function AdminShopProfile() {
  const auth = useAuth()
  const entity = auth.entity
  const [name, setName] = useState(entity?.name || '')
  const [details, setDetails] = useState(detailsOf(entity))
  const setDetail = (field) => (e) => setDetails((d) => ({ ...d, [field]: e.target.value }))
  const [storeMode, setStoreMode] = useState(entity?.store_mode || 'multi')
  const [discountLimit, setDiscountLimit] = useState(String(Number(entity?.cashier_discount_limit ?? 10)))
  const [logoFile, setLogoFile] = useState(null)
  const [removeLogo, setRemoveLogo] = useState(false)
  const [previewUrl, setPreviewUrl] = useState(null)
  const [errors, setErrors] = useState([])
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const fileInputRef = useRef(null)

  // Re-sync local drafts if the entity reloads with different data (e.g.
  // after refreshProfile() following a save).
  useEffect(() => { setName(entity?.name || '') }, [entity?.id, entity?.name])
  useEffect(() => { setDetails(detailsOf(entity)) }, [entity])
  useEffect(() => { setStoreMode(entity?.store_mode || 'multi') }, [entity?.id, entity?.store_mode])
  useEffect(() => { setDiscountLimit(String(Number(entity?.cashier_discount_limit ?? 10))) }, [entity?.id, entity?.cashier_discount_limit])

  useEffect(() => {
    if (!logoFile) { setPreviewUrl(null); return }
    const url = URL.createObjectURL(logoFile)
    setPreviewUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [logoFile])

  function onPickLogo(e) {
    const file = e.target.files?.[0] || null
    if (file && file.size > 2 * 1024 * 1024) {
      setErrors(['Logo must be 2MB or smaller.'])
      return
    }
    setErrors([])
    setRemoveLogo(false)
    setLogoFile(file)
  }

  function onRemoveLogo() {
    setLogoFile(null)
    setRemoveLogo(true)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  async function save() {
    if (!name.trim()) {
      setErrors(['Shop name is required.'])
      return
    }
    const limit = Number(discountLimit)
    if (discountLimit.trim() === '' || Number.isNaN(limit) || limit < 0 || limit > 100) {
      setErrors(['The cashier discount limit must be a percentage between 0 and 100.'])
      return
    }
    setErrors([])
    setSaved(false)
    setSaving(true)
    try {
      const changes = {}
      if (name.trim() !== entity.name) changes.name = name.trim()
      for (const f of DETAIL_FIELDS) if (details[f].trim() !== (entity[f] ?? '')) changes[f] = details[f].trim()
      if (storeMode !== entity.store_mode) changes.store_mode = storeMode
      if (limit !== Number(entity.cashier_discount_limit)) changes.cashier_discount_limit = String(limit)
      if (Object.keys(changes).length) await updateEntity(entity.id, changes)
      if (logoFile) await updateEntityLogo(entity.id, logoFile)
      else if (removeLogo) await updateEntityLogo(entity.id, null)
      await auth.refreshProfile()
      setLogoFile(null)
      setRemoveLogo(false)
      setSaved(true)
    } catch (err) {
      setErrors(errorLines(err))
    } finally {
      setSaving(false)
    }
  }

  if (!entity) {
    return <NoticeBox variant="info" title="No shop to edit">Sign in as the shop's owner to edit its profile.</NoticeBox>
  }

  const logoToShow = previewUrl || (removeLogo ? null : entity.logo)
  const unchanged = name.trim() === entity.name && DETAIL_FIELDS.every((f) => details[f].trim() === (entity[f] ?? ''))
    && storeMode === entity.store_mode && !logoFile && !removeLogo
    && Number(discountLimit) === Number(entity.cashier_discount_limit)

  return (
    <div style={{ maxWidth: 560 }}>
      <p style={{ fontSize: 14, color: 'var(--fg-muted)', margin: '0 0 16px' }}>
        The shop's name and logo appear in the app header and on printed documents — set once per firm, shared across every store.
      </p>

      {errors.length > 0 && (
        <NoticeBox variant="error" title="Could not save" style={{ marginBottom: 12 }}>
          {errors.map((e) => <div key={e}>{e}</div>)}
        </NoticeBox>
      )}
      {saved && <NoticeBox variant="valid" title="Shop profile saved" style={{ marginBottom: 12 }} />}

      <Card>
        <div style={{ marginBottom: 16 }}>
          <Field label="Shop name" required>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Kariakoo General Stores" />
          </Field>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(200px,1fr))', gap: 12, marginBottom: 16 }}>
          <Field label="Type of shop">
            <Select value={details.business_type} onChange={setDetail('business_type')} options={BUSINESS_TYPE_OPTIONS} />
          </Field>
          <Field label="Phone"><Input value={details.phone} onChange={setDetail('phone')} placeholder="e.g. 0712 345 678" /></Field>
          <Field label="Email"><Input type="email" value={details.email} onChange={setDetail('email')} /></Field>
          <Field label="Region"><Input value={details.region} onChange={setDetail('region')} placeholder="e.g. Dar es Salaam" /></Field>
          <Field label="District"><Input value={details.district} onChange={setDetail('district')} placeholder="e.g. Kinondoni" /></Field>
          <Field label="Street / area"><Input value={details.address} onChange={setDetail('address')} placeholder="e.g. Sinza, near the market" /></Field>
        </div>

        <div style={{ marginBottom: 16 }}>
          <Field label="Cashier discount limit (%)">
            <Input type="number" value={discountLimit} onChange={(e) => setDiscountLimit(e.target.value)} style={{ width: 140 }} />
          </Field>
          <div style={{ fontSize: 12, color: 'var(--fg-subtle)', marginTop: 4 }}>
            The largest discount a cashier may give on a sale. Above it, a manager approves at the till. Managers may give any discount.
          </div>
        </div>

        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--fg-default)', marginBottom: 8 }}>Store setup</div>
          {STORE_MODE_OPTIONS.map((o) => (
            <div key={o.value} style={{ marginBottom: 8 }}>
              <Radio checked={storeMode === o.value} onChange={() => setStoreMode(o.value)} label={o.label} />
              <div style={{ fontSize: 12, color: 'var(--fg-subtle)', margin: '2px 0 0 26px' }}>{o.hint}</div>
            </div>
          ))}
        </div>

        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--fg-default)', marginBottom: 8 }}>Logo</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <div style={{
              width: 64, height: 64, borderRadius: 'var(--radius-md)', border: '1px solid var(--grey-400)',
              display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden', background: 'var(--grey-050)',
            }}>
              {logoToShow
                ? <img src={logoToShow} alt="Shop logo" style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }} />
                : <span style={{ fontSize: 11, color: 'var(--fg-subtle)' }}>No logo</span>}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <input ref={fileInputRef} type="file" accept="image/*" onChange={onPickLogo} style={{ fontSize: 13 }} />
              {logoToShow && <Button size="small" onClick={onRemoveLogo}>Remove logo</Button>}
            </div>
          </div>
        </div>

        <Button variant="primary" onClick={save} disabled={saving || unchanged}>{saving ? 'Saving…' : 'Save changes'}</Button>
      </Card>
    </div>
  )
}
