import { useState } from 'react'
import { Button, Card, NoticeBox, Switch } from '../components/ds/index.js'
import { useApi } from '../hooks/useApi.js'
import { client } from '../api/client.js'
import { apiErrorText } from '../lib/apiError.js'

/** The end-of-day summary each store's managers and the firm's admins get
 * after closing: sales by payment method, voids, missing EFD numbers, cash
 * differences, purchases, low stock and expiring batches. */
export default function NotificationsPanel() {
  const { data, refetch } = useApi(() => client.get('/api/notifications/settings/'), [])
  const [message, setMessage] = useState(null) // {variant, text}
  const [busy, setBusy] = useState(false)

  async function toggle(field) {
    setMessage(null)
    try {
      await client.patch('/api/notifications/settings/', { [field]: !data[field] })
      refetch()
    } catch (err) {
      setMessage({ variant: 'error', text: apiErrorText(err, 'Could not save.') })
    }
  }
  async function testSms() {
    setBusy(true); setMessage(null)
    try {
      const res = await client.post('/api/notifications/test-sms/')
      setMessage({ variant: 'valid', text: res.detail })
    } catch (err) {
      setMessage({ variant: 'error', text: apiErrorText(err, 'The test SMS failed.') })
    } finally { setBusy(false) }
  }

  if (!data) return <NoticeBox variant="info">Loading…</NoticeBox>
  const rows = [
    {
      field: 'sms_enabled', title: 'SMS', configured: data.sms_configured,
      help: 'A short text to each manager\'s mobile number (set under "Edit my details").',
      missing: 'SMS is not set up on the server yet (Beem Africa keys in .env — see deploy/README.md).',
    },
    {
      field: 'email_enabled', title: 'Email', configured: data.email_configured,
      help: 'A fuller summary to each manager\'s email address.',
      missing: 'Email sending is not set up on the server yet (EMAIL_* settings in .env).',
    },
  ]
  return (
    <>
      <p style={{ fontSize: 14, color: 'var(--fg-muted)', margin: '0 0 16px', maxWidth: 640 }}>
        After closing each day, store managers and admins get a summary: sales by payment method, voids, sales missing an
        EFD receipt number, cash differences, purchases, low stock and batches about to expire.
      </p>
      {message && <NoticeBox variant={message.variant} style={{ marginBottom: 12, maxWidth: 640 }}>{message.text}</NoticeBox>}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 640 }}>
        {rows.map((r) => (
          <Card key={r.field}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 16 }}>
              <div>
                <div style={{ fontSize: 14, color: 'var(--grey-900)' }}>End-of-day summary by {r.title}</div>
                <div style={{ fontSize: 13, color: 'var(--fg-subtle)' }}>{r.help}</div>
                {!r.configured && <div style={{ fontSize: 13, color: 'var(--status-warning, var(--grey-700))', marginTop: 4 }}>{r.missing}</div>}
              </div>
              <Switch on={data[r.field]} onChange={() => toggle(r.field)} />
            </div>
          </Card>
        ))}
      </div>
      <Button onClick={testSms} disabled={busy || !data.sms_configured} style={{ marginTop: 16 }}>
        {busy ? 'Sending…' : 'Send me a test SMS'}
      </Button>
    </>
  )
}
