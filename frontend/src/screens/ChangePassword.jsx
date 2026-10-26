import { useState } from 'react'
import { Button, Field, Input, NoticeBox } from '../components/ds/index.js'
import AuthLayout from '../components/AuthLayout.jsx'
import { useAuth } from '../auth/AuthContext.jsx'
import { apiErrorText } from '../lib/apiError.js'

/** Shown instead of the app when an admin set this user's password: the
 * admin knows it, so the user picks their own before doing anything. */
export default function ChangePassword() {
  const auth = useAuth()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setError('')
    if (next !== confirm) { setError('The new passwords do not match.'); return }
    setBusy(true)
    try {
      await auth.updateProfile({ current_password: current, new_password: next })
    } catch (err) {
      setError(apiErrorText(err, 'Could not change your password.'))
    } finally { setBusy(false) }
  }

  return (
    <AuthLayout headline="One more step" overline="Secure your account" text="Set a password only you know. You will use it every time you sign in." points={[]}>
      <form onSubmit={submit} className="login-form-inner">
        <h1 className="login-title">Choose your password</h1>
        <p className="page-subtitle" style={{ marginBottom: 24 }}>
          Your password was set by an administrator. Pick a new one that only you know before continuing.
        </p>
        {error && <NoticeBox variant="error" style={{ marginBottom: 16 }}>{error}</NoticeBox>}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Field label="Password you were given" required><Input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} prefixIcon="lock" /></Field>
          <Field label="New password" required><Input type="password" value={next} onChange={(e) => setNext(e.target.value)} prefixIcon="lock" /></Field>
          <Field label="New password again" required><Input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} prefixIcon="lock" /></Field>
          <Button type="submit" variant="primary" size="large" disabled={busy || !current || !next} style={{ width: '100%', marginTop: 8 }}>
            {busy ? 'Saving…' : 'Set password and continue'}
          </Button>
          <Button onClick={auth.logout} style={{ width: '100%' }}>Sign out</Button>
        </div>
      </form>
    </AuthLayout>
  )
}
