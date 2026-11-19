import { useEffect, useState } from 'react'
import { Button, Checkbox, Field, Icon, Input, NoticeBox, Select } from '../components/ds/index.js'
import LocationFields, { TANZANIA } from '../components/LocationFields.jsx'
import { useAuth } from '../auth/AuthContext.jsx'
import { requestSignupCode, signup } from '../api/signup.js'
import { BUSINESS_TYPE_OPTIONS } from '../appData.js'
import { PHONE_DIGITS, phoneInput } from '../lib/phone.js'
import { t, tOptions, useT } from '../i18n/index.js'

// The kinds of business picked from a card; the rest are under "Other".
// `starter`: an example of the starter products (backend catalog/seed_data.py
// KITS), which every kind below has.
const KINDS = [
  { value: 'general', icon: 'store', label: 'General shop (duka)', hint: 'Everyday goods', starter: 'sugar, soda, flour, soap…' },
  { value: 'supermarket', icon: 'pos', label: 'Supermarket / minimarket', hint: 'Many products, barcodes', starter: 'sugar, soda, flour, soap…' },
  { value: 'grocery', icon: 'grocery', label: 'Grocery (fruits & vegetables)', hint: 'Sold by kg, bunch or piece', starter: 'tomatoes, onions, bananas, eggs…' },
  { value: 'hardware', icon: 'tools', label: 'Hardware', hint: 'Building materials and tools', starter: 'cement, iron sheets, nails, pipes…' },
  { value: 'automotive', icon: 'car', label: 'Automotive spare parts', hint: 'Parts, oils, tyres and batteries', starter: 'engine oil, oil filters, brake pads, spark plugs…' },
  { value: 'pharmacy', icon: 'pharmacy', label: 'Pharmacy / chemist', hint: 'Medicines, prescriptions, expiry', starter: 'paracetamol, amoxicillin, ORS…' },
  { value: 'bar', icon: 'bar', label: 'Bar / pub', hint: 'Drinks by bottle, crate or tot', starter: 'beer, spirits, soda, water…' },
]
const STARTER = { ...Object.fromEntries(KINDS.map((k) => [k.value, k.starter])), wholesale: 'sugar, soda, flour, soap…' }
const OTHER_KINDS = BUSINESS_TYPE_OPTIONS.filter((o) => !KINDS.some((k) => k.value === o.value))
const RESEND_SECONDS = 60

const LABEL = {
  name: 'Shop name', business_type: 'Type of shop', country: 'Country', region: 'Region', council: 'Council',
  address: 'Street / area', first_name: 'First name', last_name: 'Last name', phone: 'Mobile number',
  password: 'Password', code: 'Code',
}
const STEP_OF = {
  name: 1, business_type: 1, country: 1, region: 1, council: 1, address: 1,
  first_name: 2, last_name: 2, phone: 2, password: 2, username: 2,
}

/** The server's {field: [messages]} → readable lines, and the earliest
 * step holding one of the fields. */
function readErrors(err) {
  const body = err?.body
  if (!body || typeof body !== 'object') return { lines: [err?.message || t('Request failed')], step: null }
  const lines = []
  let step = null
  for (const [field, msgs] of Object.entries(body)) {
    const text = Array.isArray(msgs) ? msgs.join(' ') : String(msgs)
    lines.push(LABEL[field] ? `${t(LABEL[field])}: ${text}` : text)
    if (STEP_OF[field] && (step === null || STEP_OF[field] < step)) step = STEP_OF[field]
  }
  return { lines, step }
}

/** "Create an account for your shop": three short steps, then the owner is
 * signed straight in. Their mobile number is their username. */
export default function Signup({ onBack }) {
  useT()
  const auth = useAuth()
  const [step, setStep] = useState(1)
  const [shop, setShop] = useState({ name: '', business_type: 'general', country: TANZANIA, region: '', council: '', address: '' })
  const [owner, setOwner] = useState({ first_name: '', last_name: '', phone: '', password: '', confirm: '' })
  const [starter, setStarter] = useState(true)
  const [code, setCode] = useState('')
  const [sent, setSent] = useState(null) // { sent_to, minutes, debug_code? }
  const [wait, setWait] = useState(0)
  const [errors, setErrors] = useState([])
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (wait <= 0) return undefined
    const timer = setTimeout(() => setWait((w) => w - 1), 1000)
    return () => clearTimeout(timer)
  }, [wait])

  const setShopField = (field) => (e) => setShop((s) => ({ ...s, [field]: e.target.value }))
  const setOwnerField = (field) => (e) => setOwner((o) => ({ ...o, [field]: field === 'phone' ? phoneInput(e.target.value) : e.target.value }))
  const offersStarter = Boolean(STARTER[shop.business_type])
  const [otherKind, setOtherKind] = useState(false)

  function shopProblems() {
    const problems = []
    if (!shop.name.trim()) problems.push(t('{field} is required.', { field: t('Shop name') }))
    if (shop.country === TANZANIA && (!shop.region || !shop.council)) problems.push(t('Choose the region and council where the shop is.'))
    return problems
  }

  function ownerProblems() {
    const problems = ['first_name', 'last_name'].filter((f) => !owner[f].trim()).map((f) => t('{field} is required.', { field: t(LABEL[f]) }))
    if (owner.phone.length !== PHONE_DIGITS || !owner.phone.startsWith('0')) problems.push(t('Enter a full mobile number, e.g. 0712 345 678.'))
    if (owner.password.length < 8) problems.push(t('The password must have at least 8 characters.'))
    else if (owner.password !== owner.confirm) problems.push(t('Passwords do not match.'))
    return problems
  }

  async function sendCode() {
    setBusy(true)
    setErrors([])
    try {
      setSent(await requestSignupCode(owner.phone))
      setWait(RESEND_SECONDS)
      setStep(3)
    } catch (err) {
      setErrors(readErrors(err).lines)
    } finally { setBusy(false) }
  }

  async function next(e) {
    e.preventDefault()
    if (step === 1) {
      const problems = shopProblems()
      setErrors(problems)
      if (!problems.length) setStep(2)
      return
    }
    if (step === 2) {
      const problems = ownerProblems()
      setErrors(problems)
      if (!problems.length) await sendCode()
      return
    }
    if (!code.trim()) { setErrors([t('Enter the code from the SMS.')]); return }
    setBusy(true)
    setErrors([])
    try {
      const { token } = await signup({
        code, phone: owner.phone, password: owner.password, first_name: owner.first_name, last_name: owner.last_name,
        shop, starter_products: offersStarter && starter,
      })
      auth.signInWithToken(token)
    } catch (err) {
      const { lines, step: back } = readErrors(err)
      setErrors(lines)
      if (back) setStep(back)
      setBusy(false)
    }
  }

  const back = () => { setErrors([]); if (step === 1) onBack(); else setStep(step - 1) }

  return (
    <form onSubmit={next} className="signin-form" noValidate>
      <p className="signup-step">{t('Step {n} of {total}', { n: step, total: 3 })}</p>
      <h1 className="signin-title">
        {step === 1 && t('Your shop')}
        {step === 2 && t('About you')}
        {step === 3 && t('Confirm your number')}
      </h1>
      <p className="signin-sub">
        {step === 1 && t('Create a free account for your shop in about two minutes. No need to call anyone.')}
        {step === 2 && t('You are the owner. Your mobile number will be your username for signing in.')}
        {step === 3 && t('We sent a 6-digit code by SMS to {phone}. Enter it below. It expires in {n} minutes.', { phone: sent?.sent_to ?? '', n: sent?.minutes ?? 10 })}
      </p>
      {errors.length > 0 && (
        <NoticeBox variant="error" style={{ marginBottom: 16 }}>
          {errors.map((line) => <div key={line}>{line}</div>)}
        </NoticeBox>
      )}

      <div className="signup-fields">
        {step === 1 && (
          <>
            <Field label={t('Shop name')} required><Input value={shop.name} onChange={setShopField('name')} placeholder={t('e.g. Neema General Store')} prefixIcon="store" /></Field>
            <fieldset className="kind-picker">
              <legend className="ds-label">{t('What kind of business is it?')}</legend>
              <div className="kind-grid">
                {KINDS.map((k) => (
                  <button
                    key={k.value} type="button" className="kind-card" aria-pressed={!otherKind && shop.business_type === k.value}
                    onClick={() => { setOtherKind(false); setShop((s) => ({ ...s, business_type: k.value })) }}
                  >
                    <Icon name={k.icon} size={24} />
                    <span className="kind-name">{t(k.label)}</span>
                    <span className="kind-hint">{t(k.hint)}</span>
                  </button>
                ))}
                <button
                  type="button" className="kind-card" aria-pressed={otherKind}
                  onClick={() => { setOtherKind(true); setShop((s) => ({ ...s, business_type: OTHER_KINDS[0].value })) }}
                >
                  <Icon name="apps" size={24} />
                  <span className="kind-name">{t('Other')}</span>
                  <span className="kind-hint">{t('Wholesale, electronics, clothing…')}</span>
                </button>
              </div>
              {otherKind && (
                <Select value={shop.business_type} onChange={setShopField('business_type')} options={tOptions(OTHER_KINDS)} aria-label={t('Type of shop')} />
              )}
              {shop.business_type === 'pharmacy' && (
                <p className="kind-note">{t('Pharmacies also get prescriptions, the controlled-drugs register and insurance claims.')}</p>
              )}
            </fieldset>
            <LocationFields
              country={shop.country} region={shop.region} council={shop.council}
              onChange={(loc) => setShop((s) => ({ ...s, ...loc }))}
            />
            <Field label={t('Street / area')}><Input value={shop.address} onChange={setShopField('address')} placeholder={t('e.g. Sinza, near the market')} /></Field>
          </>
        )}
        {step === 2 && (
          <>
            <Field label={t('First name')} required><Input value={owner.first_name} onChange={setOwnerField('first_name')} prefixIcon="user" /></Field>
            <Field label={t('Last name')} required><Input value={owner.last_name} onChange={setOwnerField('last_name')} /></Field>
            <Field label={t('Mobile number')} required>
              <Input value={owner.phone} onChange={setOwnerField('phone')} placeholder="0712345678" inputMode="numeric" maxLength={PHONE_DIGITS} prefixIcon="phone" />
            </Field>
            <Field label={t('Password')} required>
              <Input type="password" value={owner.password} onChange={setOwnerField('password')} placeholder={t('At least 8 characters')} prefixIcon="lock" />
            </Field>
            <Field label={t('Type the password again')} required>
              <Input type="password" value={owner.confirm} onChange={setOwnerField('confirm')} prefixIcon="lock" />
            </Field>
          </>
        )}
        {step === 3 && (
          <>
            {sent?.debug_code && (
              <NoticeBox variant="info">{t('Test server: SMS is not sent. Your code is {code}.', { code: sent.debug_code })}</NoticeBox>
            )}
            <Field label={t('Code')} required>
              <Input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))} placeholder="123456" inputMode="numeric" maxLength={6} prefixIcon="lock" />
            </Field>
            {offersStarter && (
              <Checkbox
                checked={starter} onChange={() => setStarter((s) => !s)}
                label={t('Add a few common products to start with ({examples}). You can edit or delete them.', { examples: t(STARTER[shop.business_type]) })}
              />
            )}
            <p className="signup-resend">
              {wait > 0
                ? t('Did not get it? You can ask for a new code in {n} seconds.', { n: wait })
                : <button type="button" className="login-link" onClick={sendCode} disabled={busy}>{t('Send a new code')}</button>}
            </p>
          </>
        )}
      </div>

      <div className="signup-actions">
        <Button type="button" size="large" onClick={back} disabled={busy}>
          <Icon name="arrow-left" size={20} /> {step === 1 ? t('Back to sign in') : t('Back')}
        </Button>
        <Button type="submit" variant="primary" size="large" disabled={busy}>
          {busy ? t('Please wait…') : step === 3 ? t('Create my shop') : t('Continue')} {!busy && <Icon name="arrow-right" size={20} />}
        </Button>
      </div>
    </form>
  )
}
