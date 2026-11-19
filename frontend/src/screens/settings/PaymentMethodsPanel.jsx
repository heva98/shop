import { useState } from 'react'
import { Card, NoticeBox, Switch } from '../../components/ds/index.js'
import { useApi } from '../../hooks/useApi.js'
import { listPaymentMethods, updatePaymentMethod } from '../../api/payments.js'
import { apiErrorText } from '../../lib/apiError.js'
import { t, useT } from '../../i18n/index.js'
import { introStyle } from './shared.js'

const PAYMENT_HELP = {
  cash: 'Always on. Counted in the drawer at shift close.',
  mobile_money: 'M-Pesa, Mixx by Yas, Airtel Money, HaloPesa. The cashier enters the transaction reference from the SMS.',
  bank_transfer: 'Direct bank payments. The cashier enters the bank reference.',
}

export default function PaymentMethodsPanel() {
  useT()
  const { data, refetch } = useApi(() => listPaymentMethods(), [])
  const [error, setError] = useState('')
  async function toggle(m) {
    setError('')
    try {
      await updatePaymentMethod(m.id, { is_active: !m.is_active })
      refetch()
    } catch (err) {
      setError(apiErrorText(err, t('Could not update the payment method.')))
    }
  }
  return (
    <>
      <p style={introStyle}>{t('Which payment methods the till offers.')}</p>
      {error && <NoticeBox variant="error" style={{ marginBottom: 12 }}>{error}</NoticeBox>}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 640 }}>
        {(data?.results ?? []).map((m) => (
          <Card key={m.id}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 16 }}>
              <div>
                <div style={{ fontSize: 14, color: 'var(--grey-900)' }}>{t(m.name)}</div>
                <div style={{ fontSize: 13, color: 'var(--fg-subtle)' }}>{PAYMENT_HELP[m.implementation] && t(PAYMENT_HELP[m.implementation])}</div>
              </div>
              <Switch on={m.is_active} onChange={() => toggle(m)} disabled={m.implementation === 'cash'} />
            </div>
          </Card>
        ))}
      </div>
    </>
  )
}
