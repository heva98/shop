import { useState } from 'react'
import { Button, Checkbox, Field, Icon, LanguageSwitch, NoticeBox } from '../components/ds/index.js'
import { useAuth } from '../auth/AuthContext.jsx'
import { BRAND_NAME } from '../appData.js'
import storesImg from '../assets/login/stores.webp'
import { useT } from '../i18n/index.js'

const FEATURES = [
  { icon: 'pos', label: 'Sales & POS' },
  { icon: 'stock', label: 'Inventory Management' },
  { icon: 'reports', label: 'Purchases & Suppliers' },
  { icon: 'analytics', label: 'Reporting & Analytics' },
]

const SEGMENTS = ['For Supermarkets', 'Malls', 'Hardware Stores', 'And More']

// Phone layout only: icon row under the brand.
const CATEGORIES = [
  { icon: 'pos', label: 'Supermarkets' },
  { icon: 'store', label: 'Malls' },
  { icon: 'tools', label: 'Hardware Stores' },
  { icon: 'store', label: 'And More' },
]

/** Sign-in page (shoppy.co.tz mockup): marketing panel on the blue page,
 * white form card on the right. Phones get the compact mobile mockup:
 * brand, category icons and a cart photo above the form card. */
export default function Login() {
  const t = useT()
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
      setError(err?.status === 429 ? err.body?.detail : t('Incorrect username or password.'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="signin-page">
      <span className="signin-glow a" aria-hidden="true" />
      <span className="signin-glow b" aria-hidden="true" />

      <section className="signin-intro">
        <div className="signin-brand">
          <span className="signin-brand-tile"><Icon name="pos" size={44} strokeWidth={2.4} /></span>
          <span>
            <span className="signin-brand-name">{BRAND_NAME}</span>
            <span className="signin-brand-tag">{t('Multi-store ERP system')}</span>
          </span>
        </div>
        <ul className="signin-cats">
          {CATEGORIES.map((c) => (
            <li key={c.label}>
              <span className="signin-cat-icon"><Icon name={c.icon} size={30} /></span>
              {t(c.label)}
            </li>
          ))}
        </ul>
        <span className="signin-cart" style={{ backgroundImage: `url(${storesImg})` }} aria-hidden="true" />
        <h2 className="signin-headline">
          {t('Manage Your Business,')}<br />
          <span>{t('All in One Place')}</span>
        </h2>
        <p className="signin-text">
          {t('{brand} helps supermarkets, malls, hardware stores and other retail businesses manage sales, inventory, purchases and more efficiently and securely.', { brand: BRAND_NAME })}
        </p>
        <ul className="signin-features">
          {FEATURES.map((f) => (
            <li key={f.label}>
              <span className="signin-feature-icon"><Icon name={f.icon} size={24} /></span>
              {t(f.label)}
            </li>
          ))}
        </ul>
        <img className="signin-stores" src={storesImg} alt="" aria-hidden="true" />
        <p className="signin-segments">
          <Icon name="store" size={26} />
          {SEGMENTS.map((s, i) => (
            <span key={s}>{i > 0 && <span className="sep" aria-hidden="true">&bull;</span>}{t(s)}</span>
          ))}
        </p>
      </section>

      <main className="signin-card">
        <form onSubmit={onSubmit} className="signin-form">
          <div className="signin-lang"><LanguageSwitch /></div>
          <h1 className="signin-title">{t('Welcome Back')}</h1>
          <p className="signin-sub">
            {t('Sign in to your {brand} account to manage your store, sales and inventory.', { brand: BRAND_NAME })}
          </p>
          {notice && !error && <NoticeBox variant="info" style={{ marginBottom: 16 }}>{notice}</NoticeBox>}
          {error && <NoticeBox variant="error" style={{ marginBottom: 16 }}>{error}</NoticeBox>}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
            <Field label={t('Username / Email')}>
              <div className="login-field">
                <Icon name="user" size={22} />
                <input
                  className="ds-input" value={username} onChange={(e) => setUsername(e.target.value)}
                  placeholder={t('e.g. manager@store.co.tz')} autoComplete="username" autoCapitalize="none" spellCheck={false}
                />
              </div>
            </Field>
            <Field label={t('Password')}>
              <div className="login-field">
                <Icon name="lock" size={22} />
                <input
                  className="ds-input" type={showPassword ? 'text' : 'password'} value={password}
                  onChange={(e) => setPassword(e.target.value)} placeholder={t('Enter your password')} autoComplete="current-password"
                />
                <button
                  type="button" className="login-show" onClick={() => setShowPassword((s) => !s)}
                  aria-label={showPassword ? t('Hide password') : t('Show password')} aria-pressed={showPassword}
                >
                  {showPassword ? t('Hide') : t('Show')}
                </button>
              </div>
            </Field>
            <div className="login-row">
              <Checkbox checked={remember} onChange={() => setRemember((r) => !r)} label={t('Remember me')} />
              <button type="button" className="login-link" onClick={() => setShowHelp(true)}>{t('Forgot password?')}</button>
            </div>
            {showHelp && (
              <NoticeBox variant="info">
                {t('Passwords are reset by your shop’s administrator. Ask them to set a new one; you will choose your own the next time you sign in.')}
              </NoticeBox>
            )}
            <Button type="submit" variant="primary" size="large" disabled={submitting} style={{ width: '100%' }}>
              {submitting ? t('Signing in…') : <>{t('Sign in')} <Icon name="arrow-right" size={22} /></>}
            </Button>
          </div>
          <div className="signin-or" aria-hidden="true"><span>{t('or')}</span></div>
          <p className="signin-help">
            <Icon name="shield" size={20} />
            {t('Need help?')}{' '}
            <button type="button" className="login-link" onClick={() => setShowHelp(true)}>{t('Contact support')}</button>
          </p>
        </form>
      </main>
    </div>
  )
}
