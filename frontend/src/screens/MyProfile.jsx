import { useState } from 'react'
import { Button, Card, Field, Input, NoticeBox, Select } from '../components/ds/index.js'
import { useAuth } from '../auth/AuthContext.jsx'
import { GENDER_OPTIONS } from '../appData.js'
import { t, tOptions, useT } from '../i18n/index.js'
import { PHONE_DIGITS, localPhone, phoneInput } from '../lib/phone.js'

const PROFILE_FIELDS = ['first_name', 'middle_name', 'last_name', 'gender', 'date_of_birth', 'email', 'phone']
const FIELD_LABEL = {
  first_name: 'First name', last_name: 'Last name', gender: 'Gender', date_of_birth: 'Date of birth',
  email: 'Email', phone: 'Mobile number',
  current_password: 'Current password', new_password: 'New password',
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

function draftFrom(profile) {
  return {
    ...Object.fromEntries(PROFILE_FIELDS.map((f) => [f, profile?.[f] ?? ''])),
    phone: localPhone(profile?.phone),
    current_password: '', new_password: '', confirm_password: '',
  }
}

export default function MyProfile({ onDone }) {
  useT()
  const auth = useAuth()
  const [draft, setDraft] = useState(() => draftFrom(auth.profile))
  const [errors, setErrors] = useState([])
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  const set = (field) => (e) => setDraft((d) => ({ ...d, [field]: e.target.value }))

  async function save() {
    const problems = ['first_name', 'last_name']
      .filter((f) => !draft[f].trim()).map((f) => t('{field} is required.', { field: t(FIELD_LABEL[f]) }))
    if (draft.new_password) {
      if (!draft.current_password) problems.push(t('Enter your current password to set a new one.'))
      if (draft.new_password !== draft.confirm_password) problems.push(t('New passwords do not match.'))
    }
    setErrors(problems)
    setSaved(false)
    if (problems.length) return

    setSaving(true)
    try {
      const payload = Object.fromEntries(PROFILE_FIELDS.map((f) => [f, draft[f] === '' && f === 'date_of_birth' ? null : draft[f]]))
      if (draft.new_password) Object.assign(payload, { current_password: draft.current_password, new_password: draft.new_password })
      const updated = await auth.updateProfile(payload)
      setDraft(draftFrom(updated))
      setSaved(true)
    } catch (err) {
      setErrors(errorLines(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{ maxWidth: 820 }}>
      <h1 className="page-title">{t('My profile')}</h1>
      <p className="page-subtitle" style={{ marginBottom: 24 }}>
        {t('Signed in as')} <strong>{auth.profile?.username}</strong>. {t('Your username and roles are managed by an administrator.')}
      </p>

      {errors.length > 0 && (
        <NoticeBox variant="error" title={t('Could not save your details')} style={{ marginBottom: 12 }}>
          {errors.map((e) => <div key={e}>{e}</div>)}
        </NoticeBox>
      )}
      {saved && <NoticeBox variant="valid" title={t('Your details were saved')} style={{ marginBottom: 12 }} />}

      <Card>
        <p style={{ fontSize: 13, fontWeight: 500, color: 'var(--fg-subtle)', textTransform: 'uppercase', letterSpacing: 0.5, margin: '0 0 12px' }}>{t('Personal details')}</p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 12, marginBottom: 20 }}>
          <Field label={t('First name')} required><Input value={draft.first_name} onChange={set('first_name')} /></Field>
          <Field label={t('Middle name')}><Input value={draft.middle_name} onChange={set('middle_name')} /></Field>
          <Field label={t('Last name')} required><Input value={draft.last_name} onChange={set('last_name')} /></Field>
          <Field label={t('Gender')}><Select value={draft.gender} onChange={set('gender')} options={tOptions(GENDER_OPTIONS)} /></Field>
          <Field label={t('Date of birth')}><Input type="date" value={draft.date_of_birth} onChange={set('date_of_birth')} /></Field>
          <Field label={t('Email')}><Input type="email" value={draft.email} onChange={set('email')} /></Field>
          <Field label={t('Mobile number (for SMS summaries)')}><Input value={draft.phone} onChange={(e) => setDraft((d) => ({ ...d, phone: phoneInput(e.target.value) }))} inputMode="numeric" maxLength={PHONE_DIGITS} placeholder={t('e.g. 0712 345 678')} /></Field>
        </div>

        <p style={{ fontSize: 13, fontWeight: 500, color: 'var(--fg-subtle)', textTransform: 'uppercase', letterSpacing: 0.5, margin: '0 0 12px' }}>{t('Change password')}</p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 12, marginBottom: 16 }}>
          <Field label={t('Current password')}><Input type="password" value={draft.current_password} onChange={set('current_password')} /></Field>
          <Field label={t('New password')}>
            <Input type="password" value={draft.new_password} onChange={set('new_password')} placeholder={t('Leave blank to keep current')} />
          </Field>
          <Field label={t('Confirm new password')}><Input type="password" value={draft.confirm_password} onChange={set('confirm_password')} /></Field>
        </div>

        <div style={{ display: 'flex', gap: 8 }}>
          <Button variant="primary" onClick={save} disabled={saving}>{saving ? t('Saving…') : t('Save changes')}</Button>
          <Button onClick={onDone} disabled={saving}>{t('Close')}</Button>
        </div>
      </Card>
    </div>
  )
}
