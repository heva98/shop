import { useState } from 'react'
import { Button, Checkbox, Field, Icon, NoticeBox } from '../components/ds/index.js'
import AuthLayout from '../components/AuthLayout.jsx'
import { useAuth } from '../auth/AuthContext.jsx'

export default function Login() {
  const { login, notice } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [remember, setRemember] = useState(true)
  const [showHelp, setShowHelp] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  async function onSubmit(e) {
    e.preventDefault()
    if (!username.trim() || !password) return
    setSubmitting(true)
    setError(null)
    try {
      await login(username.trim(), password, remember)
    } catch (err) {
      setError(err?.status === 429 ? err.body?.detail : 'Incorrect username or password.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthLayout text="Manage stock, record sales, receive invoices and track expiry dates, all from one dashboard.">
      <form onSubmit={onSubmit} className="login-form-inner">
        <h1 className="login-title">Sign in</h1>
        <p className="page-subtitle" style={{ margin: '8px 0 28px' }}>Use your staff credentials to access the shop dashboard.</p>
        {notice && !error && <NoticeBox variant="info" style={{ marginBottom: 16 }}>{notice}</NoticeBox>}
        {error && <NoticeBox variant="error" style={{ marginBottom: 16 }}>{error}</NoticeBox>}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          <Field label="Username">
            <div className="login-field">
              <Icon name="user" size={20} />
              <input
                className="ds-input" value={username} onChange={(e) => setUsername(e.target.value)}
                placeholder="e.g. manager1" autoComplete="username" autoCapitalize="none" spellCheck={false}
              />
            </div>
          </Field>
          <Field label="Password">
            <div className="login-field">
              <Icon name="lock" size={20} />
              <input
                className="ds-input" type={showPassword ? 'text' : 'password'} value={password}
                onChange={(e) => setPassword(e.target.value)} placeholder="Enter your password" autoComplete="current-password"
              />
              <button
                type="button" className="login-show" onClick={() => setShowPassword((s) => !s)}
                aria-label={showPassword ? 'Hide password' : 'Show password'} aria-pressed={showPassword}
              >
                {showPassword ? 'Hide' : 'Show'}
              </button>
            </div>
          </Field>
          <div className="login-row">
            <Checkbox checked={remember} onChange={() => setRemember((r) => !r)} label="Remember me" />
            <button type="button" className="login-link" onClick={() => setShowHelp(true)}>Forgot password?</button>
          </div>
          {showHelp && (
            <NoticeBox variant="info">
              Passwords are reset by your shop&rsquo;s administrator. Ask them to set a new one; you will choose your own the next time you sign in.
            </NoticeBox>
          )}
          <Button type="submit" variant="primary" size="large" disabled={submitting} style={{ width: '100%' }}>
            {submitting ? 'Signing in…' : 'Sign in'}
          </Button>
        </div>
        <p className="login-foot">
          Don&rsquo;t have an account?{' '}
          <button type="button" className="login-link" onClick={() => setShowHelp(true)}>Contact your administrator</button>
        </p>
      </form>
    </AuthLayout>
  )
}
