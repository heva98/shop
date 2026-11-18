import { useState } from 'react'
import { Button, Field, Icon, Input, NoticeBox } from '../components/ds/index.js'
import { useAuth } from '../auth/AuthContext.jsx'
import { requestResetCode, resetPassword } from '../api/signup.js'
import { apiErrorText } from '../lib/apiError.js'
import { useT } from '../i18n/index.js'

/** "Forgot password?": a code goes by SMS to the number on the account,
 * then the user picks a new password and is signed straight in. Staff
 * with no number on file are told to ask their shop's owner. */
export default function ForgotPassword({ initialUsername = '', onBack }) {
  const t = useT()
  const auth = useAuth()
  const [username, setUsername] = useState(initialUsername)
  const [sent, setSent] = useState(null) // { sent_to, minutes, username, debug_code? }
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function sendCode(e) {
    e?.preventDefault()
    if (!username.trim()) { setError(t('Enter your username or mobile number.')); return }
    setBusy(true)
    setError('')
    try {
      setSent(await requestResetCode(username.trim()))
    } catch (err) {
      setError(apiErrorText(err, t('Could not send the code.')))
    } finally { setBusy(false) }
  }

  async function submit(e) {
    e.preventDefault()
    if (!code.trim()) { setError(t('Enter the code from the SMS.')); return }
    if (password !== confirm) { setError(t('Passwords do not match.')); return }
    setBusy(true)
    setError('')
    try {
      const { token } = await resetPassword({ username: sent.username, code, new_password: password })
      auth.signInWithToken(token)
    } catch (err) {
      setError(apiErrorText(err, t('Could not change your password.')))
      setBusy(false)
    }
  }

  return (
    <form onSubmit={sent ? submit : sendCode} className="signin-form" noValidate>
      <h1 className="signin-title">{t('Reset your password')}</h1>
      <p className="signin-sub">
        {sent
          ? t('We sent a 6-digit code by SMS to {phone}. Enter it and choose a new password.', { phone: sent.sent_to })
          : t('Enter your username, or the mobile number you signed up with. We will send a code by SMS to the number on your account.')}
      </p>
      {error && <NoticeBox variant="error" style={{ marginBottom: 16 }}>{error}</NoticeBox>}
      <div className="signup-fields">
        {!sent && (
          <Field label={t('Username or mobile number')} required>
            <Input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="0712345678" prefixIcon="user" />
          </Field>
        )}
        {sent && (
          <>
            {sent.debug_code && <NoticeBox variant="info">{t('Test server: SMS is not sent. Your code is {code}.', { code: sent.debug_code })}</NoticeBox>}
            <Field label={t('Code')} required>
              <Input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))} placeholder="123456" inputMode="numeric" maxLength={6} prefixIcon="lock" />
            </Field>
            <Field label={t('New password')} required>
              <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder={t('At least 8 characters')} prefixIcon="lock" />
            </Field>
            <Field label={t('Type the password again')} required>
              <Input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} prefixIcon="lock" />
            </Field>
            <p className="signup-resend">
              <button type="button" className="login-link" onClick={() => sendCode()} disabled={busy}>{t('Send a new code')}</button>
            </p>
          </>
        )}
      </div>
      <div className="signup-actions">
        <Button type="button" size="large" onClick={onBack} disabled={busy}><Icon name="arrow-left" size={20} /> {t('Back to sign in')}</Button>
        <Button type="submit" variant="primary" size="large" disabled={busy}>
          {busy ? t('Please wait…') : sent ? t('Save and sign in') : t('Send code')}
        </Button>
      </div>
    </form>
  )
}
