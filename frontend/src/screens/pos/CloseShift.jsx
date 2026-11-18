import { useState } from 'react'
import { Button, Card, Field, Input, NoticeBox } from '../../components/ds/index.js'
import { isTransient } from '../../api/client.js'
import { closeShift } from '../../api/pos.js'
import { apiErrorText } from '../../lib/apiError.js'
import { t, useT } from '../../i18n/index.js'
import { parseAmount } from './format.js'
import { useAsyncAction } from '../../hooks/useAsyncAction.js'

/** Closing needs every sale of the shift recorded in the cloud first, or
 * the Z-report and the drawer count would leave them out. */
export default function CloseShift({ shift, unsent, onClosed }) {
  useT()
  const [counted, setCounted] = useState('')
  const [note, setNote] = useState('')
  const { busy, error, run } = useAsyncAction()

  function submit() {
    return run(async () => {
      onClosed(await closeShift(shift.id, parseAmount(counted), note))
    }, (err) => isTransient(err)
      ? t('No connection. Closing a shift needs the connection, so the Z-report includes every sale.')
      : apiErrorText(err, t('Could not close the shift.')))
  }

  return (
    <div style={{ maxWidth: 440 }}>
      <Card>
        <p style={{ fontSize: 14, color: 'var(--fg-muted)', margin: '0 0 16px' }}>
          {t('Count all the cash in the drawer, including the opening float and cash repayments from credit customers. Mobile money and bank payments are not in the drawer. The system compares your count with what it expects and prints the end-of-shift (Z) report.')}
        </p>
        {unsent.length > 0 && (
          <NoticeBox variant="warning" title={t(unsent.length === 1 ? '{n} sale has not been sent yet' : '{n} sales have not been sent yet', { n: unsent.length })} style={{ marginBottom: 12 }}>
            {t('The shift can be closed once every sale on this till has been recorded. Stay connected while they are sent, and deal with any that could not be recorded.')}
          </NoticeBox>
        )}
        <Field label={t('Cash counted in drawer')} required><Input value={counted} onChange={(e) => setCounted(e.target.value)} placeholder="0" /></Field>
        <Field label={t('Note (optional)')} style={{ marginTop: 12 }}><Input value={note} onChange={(e) => setNote(e.target.value)} placeholder={t('e.g. explanation for any difference')} /></Field>
        {error && <NoticeBox variant="error" style={{ marginTop: 12 }}>{error}</NoticeBox>}
        <Button variant="primary" onClick={submit} disabled={busy || counted.trim() === '' || unsent.length > 0} style={{ marginTop: 16, width: '100%', height: 43 }}>{t('Close shift')}</Button>
      </Card>
    </div>
  )
}
