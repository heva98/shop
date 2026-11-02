import { useState } from 'react'
import { Button, Card, NoticeBox, Switch } from '../components/ds/index.js'
import { useApi } from '../hooks/useApi.js'
import { client } from '../api/client.js'
import { apiErrorText } from '../lib/apiError.js'
import { useT } from '../i18n/index.js'
import SmsPanel from './SettingsSms.jsx'

/** The end-of-day summary after closing: sales by payment method, voids,
 * missing EFD numbers, cash differences, purchases, low stock and expiring
 * batches — by email to managers and admins, by SMS to the owner. */
export default function NotificationsPanel() {
  const t = useT()
  const { data, refetch } = useApi(() => client.get('/api/notifications/settings/'), [])
  const [message, setMessage] = useState(null) // {variant, text}
  const [busy, setBusy] = useState(false)

  async function toggle(field) {
    setMessage(null)
    try {
      await client.patch('/api/notifications/settings/', { [field]: !data[field] })
      refetch()
    } catch (err) {
      setMessage({ variant: 'error', text: apiErrorText(err, t('Could not save.')) })
    }
  }
  async function testSms() {
    setBusy(true); setMessage(null)
    try {
      const res = await client.post('/api/notifications/test-sms/')
      setMessage({ variant: 'valid', text: res.detail })
    } catch (err) {
      setMessage({ variant: 'error', text: apiErrorText(err, t('The test SMS failed.')) })
    } finally { setBusy(false) }
  }

  if (!data) return <NoticeBox variant="info">{t('Loading…')}</NoticeBox>
  const rows = [
    {
      field: 'sms_enabled', title: t('End-of-day summary by SMS'), configured: data.sms_configured,
      help: t('A short text to the owner’s mobile number (set under “Edit my details”).'),
      missing: t('SMS is not set up on the server yet (SMS_BACKEND and the Notify Africa keys in .env — see deploy/README.md). Messages are only saved in the delivery log.'),
    },
    {
      field: 'email_enabled', title: t('End-of-day summary by email'), configured: data.email_configured,
      help: t('A fuller summary to each manager’s email address.'),
      missing: t('Email sending is not set up on the server yet (EMAIL_* settings in .env).'),
    },
  ]
  return (
    <>
      <p style={{ fontSize: 14, color: 'var(--fg-muted)', margin: '0 0 16px', maxWidth: 640 }}>
        {t('After closing each day the owner gets a summary by SMS, and store managers and admins by email: sales by payment method, voids, sales missing an EFD receipt number, cash differences, purchases, low stock and batches about to expire.')}
      </p>
      {message && <NoticeBox variant={message.variant} style={{ marginBottom: 12, maxWidth: 640 }}>{message.text}</NoticeBox>}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 640 }}>
        {rows.map((r) => (
          <Card key={r.field}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 16 }}>
              <div>
                <div style={{ fontSize: 14, color: 'var(--grey-900)' }}>{r.title}</div>
                <div style={{ fontSize: 13, color: 'var(--fg-subtle)' }}>{r.help}</div>
                {!r.configured && <div style={{ fontSize: 13, color: 'var(--status-warning, var(--grey-700))', marginTop: 4 }}>{r.missing}</div>}
              </div>
              <Switch on={data[r.field]} onChange={() => toggle(r.field)} />
            </div>
          </Card>
        ))}
      </div>
      <Button onClick={testSms} disabled={busy || !data.sms_configured} style={{ marginTop: 16 }}>
        {busy ? t('Sending…') : t('Send me a test SMS')}
      </Button>
      <SmsPanel />
    </>
  )
}
