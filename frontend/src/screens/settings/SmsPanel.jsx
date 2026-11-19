import { useState } from 'react'
import { Button, Card, DataTable, Field, Input, Modal, NoticeBox, Select, Switch, Tag } from '../../components/ds/index.js'
import { useApi } from '../../hooks/useApi.js'
import {
  getSmsBatch, getSmsConfig, listSmsBatches, listSmsTemplates, previewSms, resendFailedSms, sendSms,
  updateSmsConfig, updateSmsTemplate,
} from '../../api/sms.js'
import { apiErrorText } from '../../lib/apiError.js'
import { dateLocale, useT } from '../../i18n/index.js'

const KIND = 'DAILY_SALES_SUMMARY'
const STATUS_TAG = { COMPLETED: 'positive', SENT: 'positive', DELIVERED: 'positive', FAILED: 'negative', SKIPPED: 'warning' }
const rows = (data) => (Array.isArray(data) ? data : data?.results || [])

/** The owner's daily sales SMS: who gets it, its text, a send-now with
 * preview, and the delivery log (every recipient, skipped ones too). */
export default function SmsPanel() {
  const t = useT()
  const [logVersion, setLogVersion] = useState(0)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24, maxWidth: 760, marginTop: 32 }}>
      <h3 style={h3}>{t('Daily sales SMS to the owner')}</h3>
      <SmsSettings />
      <SmsTemplates />
      <SendNow onSent={() => setLogVersion((v) => v + 1)} />
      <DeliveryLog version={logVersion} />
    </div>
  )
}

function SmsSettings() {
  const t = useT()
  const { data, refetch } = useApi(() => getSmsConfig(), [])
  const [error, setError] = useState(null)
  if (!data) return null
  async function save(patch) {
    setError(null)
    try { await updateSmsConfig(patch); refetch() } catch (err) { setError(apiErrorText(err, t('Could not save.'))) }
  }
  return (
    <Card>
      {error && <NoticeBox variant="error" style={{ marginBottom: 12 }}>{error}</NoticeBox>}
      <p style={muted}>{t('Each owner gets one SMS per store after closing, at the mobile number under “Edit my details”.')}</p>
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <Field label={t('Language of the SMS')}>
          <Select value={data.language} onChange={(e) => save({ language: e.target.value })} style={{ width: 240 }} options={[
            { value: '', label: t('Each person’s own language') },
            { value: 'sw', label: 'Kiswahili' }, { value: 'en', label: 'English' },
          ]} />
        </Field>
        <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 14, paddingBottom: 8 }}>
          <Switch on={data.daily_sales_to_managers} onChange={() => save({ daily_sales_to_managers: !data.daily_sales_to_managers })} />
          {t('Also send to each store’s managers')}
        </label>
      </div>
      <p style={{ ...muted, marginTop: 12, marginBottom: 0 }}>
        {t('Provider: {name}. Messages longer than {n} SMS are not sent.', { name: data.sms_backend, n: data.effective_max_segments })}
      </p>
    </Card>
  )
}

function SmsTemplates() {
  const t = useT()
  const { data, refetch } = useApi(() => listSmsTemplates(), [])
  return (
    <div>
      <h4 style={h4}>{t('Message text')}</h4>
      <p style={muted}>{t('Words in {braces} are filled in from the day’s figures. If one has no value, that SMS is skipped rather than sent half-empty.')}</p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {rows(data).map((tpl) => <TemplateEditor key={tpl.id} template={tpl} onSaved={refetch} />)}
      </div>
    </div>
  )
}

function TemplateEditor({ template, onSaved }) {
  const t = useT()
  const [body, setBody] = useState(template.body)
  const [message, setMessage] = useState(null)
  const [busy, setBusy] = useState(false)
  async function save(patch) {
    setBusy(true); setMessage(null)
    try {
      await updateSmsTemplate(template.id, patch)
      setMessage({ variant: 'valid', text: t('Saved.') })
      onSaved()
    } catch (err) {
      setMessage({ variant: 'error', text: apiErrorText(err, t('Could not save.')) })
    } finally { setBusy(false) }
  }
  return (
    <Card>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <strong style={{ fontSize: 14 }}>{template.language === 'sw' ? 'Kiswahili' : 'English'}</strong>
        <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13 }}>
          {t('In use')}
          <Switch on={template.is_active} onChange={() => save({ is_active: !template.is_active })} />
        </label>
      </div>
      <textarea className="ds-input" rows={4} value={body} onChange={(e) => setBody(e.target.value)}
        style={{ width: '100%', fontFamily: 'inherit', resize: 'vertical', height: 'auto' }} />
      <div style={{ fontSize: 12, color: 'var(--fg-subtle)', margin: '6px 0' }}>
        {template.placeholders.map((p) => `{${p}}`).join('  ')}
      </div>
      {message && <NoticeBox variant={message.variant} style={{ marginBottom: 8 }}>{message.text}</NoticeBox>}
      <Button onClick={() => save({ body })} disabled={busy || body === template.body}>{t('Save')}</Button>
    </Card>
  )
}

function SendNow({ onSent }) {
  const t = useT()
  const today = new Date().toISOString().slice(0, 10)
  const [day, setDay] = useState(today)
  const [preview, setPreview] = useState(null)
  const [message, setMessage] = useState(null)
  const [busy, setBusy] = useState(false)
  async function showPreview() {
    setBusy(true); setMessage(null)
    try { setPreview(await previewSms({ kind: KIND, date: day })) } catch (err) {
      setMessage({ variant: 'error', text: apiErrorText(err, t('Could not prepare the SMS.')) })
    } finally { setBusy(false) }
  }
  async function send() {
    setBusy(true)
    try {
      const batch = await sendSms({ kind: KIND, date: day })
      setPreview(null)
      setMessage({
        variant: batch.failed_count ? 'warning' : 'valid',
        text: t('{sent} sent, {failed} failed, {skipped} skipped.', { sent: batch.sent_count, failed: batch.failed_count, skipped: batch.skipped_count }),
      })
      onSent()
    } catch (err) {
      setPreview(null)
      setMessage({ variant: 'error', text: apiErrorText(err, t('The SMS could not be sent.')) })
    } finally { setBusy(false) }
  }
  return (
    <div>
      <h4 style={h4}>{t('Send now')}</h4>
      <p style={muted}>{t('The summary goes out by itself every evening at 21:30. Send it now to check it, or to resend a past day.')}</p>
      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end' }}>
        <Field label={t('Day')}><Input type="date" value={day} max={today} onChange={(e) => setDay(e.target.value)} style={{ width: 170 }} /></Field>
        <Button onClick={showPreview} disabled={busy || !day}>{t('Preview and send…')}</Button>
      </div>
      {message && <NoticeBox variant={message.variant} style={{ marginTop: 12 }}>{message.text}</NoticeBox>}
      {preview && (
        <Modal title={t('Send the daily sales SMS?')} onClose={() => setPreview(null)} footer={<>
          <Button onClick={() => setPreview(null)}>{t('Cancel')}</Button>
          <Button variant="primary" onClick={send} disabled={busy || !preview.would_send}>
            {busy ? t('Sending…') : t('Send {n} SMS', { n: preview.would_send })}
          </Button>
        </>}>
          <p style={{ fontSize: 14, marginTop: 0 }}>
            {t('{n} will be sent ({segments} SMS parts), {skipped} skipped.', { n: preview.would_send, segments: preview.total_segments, skipped: preview.skipped })}
            {preview.total_cost != null && ' ' + t('About TZS {cost}.', { cost: Number(preview.total_cost).toLocaleString() })}
          </p>
          {preview.skip_breakdown.map((s) => <div key={s.reason} style={muted}>{s.label}: {s.count}</div>)}
          {preview.samples.map((s, i) => (
            <Card key={i} style={{ marginTop: 8 }}>
              <div style={{ fontSize: 12, color: 'var(--fg-subtle)' }}>{s.to} · {s.phone} · {s.store} · {t('{n} SMS', { n: s.segments })}</div>
              <div style={{ fontSize: 14, whiteSpace: 'pre-wrap', marginTop: 4 }}>{s.body}</div>
            </Card>
          ))}
        </Modal>
      )}
    </div>
  )
}

function DeliveryLog({ version }) {
  const t = useT()
  const [filters, setFilters] = useState({ status: '', date_from: '', date_to: '' })
  const { data, loading, error, refetch } = useApi(() => listSmsBatches({ kind: KIND, ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v)) }), [filters, version])
  const [openId, setOpenId] = useState(null)
  const set = (key) => (e) => setFilters((f) => ({ ...f, [key]: e.target.value }))
  return (
    <div>
      <h4 style={h4}>{t('Delivery log')}</h4>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end', marginBottom: 12 }}>
        <Field label={t('Status')}><Select value={filters.status} onChange={set('status')} style={{ width: 160 }} options={[
          { value: '', label: t('All') }, { value: 'COMPLETED', label: t('Completed') }, { value: 'FAILED', label: t('Failed') },
        ]} /></Field>
        <Field label={t('From')}><Input type="date" value={filters.date_from} onChange={set('date_from')} style={{ width: 160 }} /></Field>
        <Field label={t('To')}><Input type="date" value={filters.date_to} onChange={set('date_to')} style={{ width: 160 }} /></Field>
      </div>
      <DataTable
        caption={t('Delivery log')}
        columns={[
          {
            key: 'created_at', header: t('When'), primary: true,
            cell: (b) => <span>{new Date(b.created_at).toLocaleString(dateLocale())}{b.dry_run && <> · <Tag variant="neutral">{t('Not sent (trial)')}</Tag></>}</span>,
          },
          { key: 'status', header: t('Status'), cell: (b) => <Tag variant={STATUS_TAG[b.status] || 'neutral'}>{b.status_label}</Tag> },
          { key: 'sent_count', header: t('Sent'), align: 'end' },
          { key: 'failed_count', header: t('Failed'), align: 'end' },
          { key: 'skipped_count', header: t('Skipped'), align: 'end' },
          { key: 'total_segments', header: t('SMS parts'), align: 'end' },
          { key: 'actions', header: t('Actions'), label: '', align: 'end', cell: (b) => <Button size="small" onClick={() => setOpenId(b.id)}>{t('Details')}</Button> },
        ]}
        rows={data ? rows(data) : null}
        loading={loading}
        error={error}
        onRetry={refetch}
        density="compact"
        minWidth={600}
        empty={Object.values(filters).some(Boolean) ? t('Nothing matches.') : t('No SMS sent yet.')}
      />
      {openId && <BatchDetail id={openId} onClose={() => { setOpenId(null); refetch() }} />}
    </div>
  )
}

function BatchDetail({ id, onClose }) {
  const t = useT()
  const { data, refetch } = useApi(() => getSmsBatch(id), [id])
  const [message, setMessage] = useState(null)
  const [busy, setBusy] = useState(false)
  async function resend() {
    setBusy(true); setMessage(null)
    try { await resendFailedSms(id); refetch() } catch (err) {
      setMessage({ variant: 'error', text: apiErrorText(err, t('Could not resend.')) })
    } finally { setBusy(false) }
  }
  return (
    <Modal title={t('SMS details')} size="lg" onClose={onClose} footer={<>
      {data?.failed_count > 0 && <Button variant="primary" onClick={resend} disabled={busy}>{busy ? t('Sending…') : t('Resend failed')}</Button>}
      <Button onClick={onClose}>{t('Close')}</Button>
    </>}>
      {message && <NoticeBox variant={message.variant} style={{ marginBottom: 12 }}>{message.text}</NoticeBox>}
      {data?.messages.map((m) => (
        <Card key={m.id} style={{ marginBottom: 8 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 13 }}>
            <span>{m.recipient_name} · {m.phone || '—'} · {m.store_name}</span>
            <Tag variant={STATUS_TAG[m.status] || 'neutral'}>{m.status_label}</Tag>
          </div>
          {m.skip_reason && <div style={{ ...muted, marginTop: 4 }}>{m.skip_reason_label}</div>}
          {m.error_detail && <div style={{ fontSize: 13, color: 'var(--status-error)', marginTop: 4 }}>{t('Provider said: {error}', { error: m.error_detail })}</div>}
          {m.body && <div style={{ fontSize: 13, whiteSpace: 'pre-wrap', marginTop: 6, color: 'var(--grey-700)' }}>{m.body}</div>}
        </Card>
      ))}
    </Modal>
  )
}

const h3 = { fontSize: 16, fontWeight: 600, margin: 0, color: 'var(--grey-900)' }
const h4 = { fontSize: 14, fontWeight: 600, margin: '0 0 4px', color: 'var(--grey-900)' }
const muted = { fontSize: 13, color: 'var(--fg-subtle)', margin: '0 0 12px' }
