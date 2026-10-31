import { useState } from 'react'
import { Button, Card, Field, Input, NoticeBox, Select } from '../components/ds/index.js'
import { useAuth } from '../auth/AuthContext.jsx'
import { GENDER_OPTIONS } from '../appData.js'

const PROFILE_FIELDS = ['first_name', 'middle_name', 'last_name', 'gender', 'date_of_birth', 'email', 'phone']
const FIELD_LABEL = {
  first_name: 'First name', last_name: 'Last name', gender: 'Gender', date_of_birth: 'Date of birth',
  email: 'Email', phone: 'Mobile number',
  current_password: 'Current password', new_password: 'New password',
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

function draftFrom(profile) {
  return {
    ...Object.fromEntries(PROFILE_FIELDS.map((f) => [f, profile?.[f] ?? ''])),
    current_password: '', new_password: '', confirm_password: '',
  }
}

export default function MyProfile({ onDone }) {
  const auth = useAuth()
  const [draft, setDraft] = useState(() => draftFrom(auth.profile))
  const [errors, setErrors] = useState([])
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  const set = (field) => (e) => setDraft((d) => ({ ...d, [field]: e.target.value }))

  async function save() {
    const problems = ['first_name', 'last_name']
      .filter((f) => !draft[f].trim()).map((f) => `${FIELD_LABEL[f]} is required.`)
    if (draft.new_password) {
      if (!draft.current_password) problems.push('Enter your current password to set a new one.')
      if (draft.new_password !== draft.confirm_password) problems.push('New passwords do not match.')
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
      <h1 className="page-title">My profile</h1>
      <p className="page-subtitle" style={{ marginBottom: 24 }}>
        Signed in as <strong>{auth.profile?.username}</strong>. Your username and roles are managed by an administrator.
      </p>

      {errors.length > 0 && (
        <NoticeBox variant="error" title="Could not save your details" style={{ marginBottom: 12 }}>
          {errors.map((e) => <div key={e}>{e}</div>)}
        </NoticeBox>
      )}
      {saved && <NoticeBox variant="valid" title="Your details were saved" style={{ marginBottom: 12 }} />}

      <Card>
        <p style={{ fontSize: 13, fontWeight: 500, color: 'var(--fg-subtle)', textTransform: 'uppercase', letterSpacing: 0.5, margin: '0 0 12px' }}>Personal details</p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 12, marginBottom: 20 }}>
          <Field label="First name" required><Input value={draft.first_name} onChange={set('first_name')} /></Field>
          <Field label="Middle name"><Input value={draft.middle_name} onChange={set('middle_name')} /></Field>
          <Field label="Last name" required><Input value={draft.last_name} onChange={set('last_name')} /></Field>
          <Field label="Gender"><Select value={draft.gender} onChange={set('gender')} options={GENDER_OPTIONS} /></Field>
          <Field label="Date of birth"><Input type="date" value={draft.date_of_birth} onChange={set('date_of_birth')} /></Field>
          <Field label="Email"><Input type="email" value={draft.email} onChange={set('email')} /></Field>
          <Field label="Mobile number (for SMS summaries)"><Input value={draft.phone} onChange={set('phone')} placeholder="e.g. 0712 345 678" /></Field>
        </div>

        <p style={{ fontSize: 13, fontWeight: 500, color: 'var(--fg-subtle)', textTransform: 'uppercase', letterSpacing: 0.5, margin: '0 0 12px' }}>Change password</p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 12, marginBottom: 16 }}>
          <Field label="Current password"><Input type="password" value={draft.current_password} onChange={set('current_password')} /></Field>
          <Field label="New password">
            <Input type="password" value={draft.new_password} onChange={set('new_password')} placeholder="Leave blank to keep current" />
          </Field>
          <Field label="Confirm new password"><Input type="password" value={draft.confirm_password} onChange={set('confirm_password')} /></Field>
        </div>

        <div style={{ display: 'flex', gap: 8 }}>
          <Button variant="primary" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save changes'}</Button>
          <Button onClick={onDone} disabled={saving}>Close</Button>
        </div>
      </Card>
    </div>
  )
}
