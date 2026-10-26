import { useState } from 'react'
import { Card, NoticeBox, Switch } from '../components/ds/index.js'
import { useApi } from '../hooks/useApi.js'
import { useAuth } from '../auth/AuthContext.jsx'
import { getFeatures, setFeature } from '../api/core.js'
import { apiErrorText } from '../lib/apiError.js'

/** Which parts of the system each store uses. A switched-off feature
 * disappears from that store's menu and the server refuses it. */
export default function FeaturesPanel() {
  const auth = useAuth()
  const { data, refetch } = useApi(() => getFeatures(), [])
  const [error, setError] = useState('')

  async function toggle(feature, store, current) {
    setError('')
    try {
      await setFeature(feature.key, store, !current)
      refetch()
      auth.refreshProfile()
    } catch (err) {
      setError(apiErrorText(err, 'Could not save.'))
    }
  }

  if (!data) return <NoticeBox variant="info">Loading…</NoticeBox>
  const stores = data.stores.filter((s) => s.is_active)
  return (
    <>
      <p style={{ fontSize: 14, color: 'var(--fg-muted)', margin: '0 0 16px', maxWidth: 640 }}>
        Switch parts of the system on or off. A switched-off feature disappears from the menu, and the system refuses it even if someone tries.
      </p>
      {error && <NoticeBox variant="error" style={{ marginBottom: 12 }}>{error}</NoticeBox>}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 760 }}>
        {data.features.map((f) => (
          <Card key={f.key}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16 }}>
              <div>
                <div style={{ fontSize: 14, color: 'var(--grey-900)' }}>{f.label}</div>
                <div style={{ fontSize: 13, color: 'var(--fg-subtle)', maxWidth: 520 }}>{f.description}</div>
                {f.unavailable && <div style={{ fontSize: 13, color: 'var(--fg-muted)', maxWidth: 520, marginTop: 4 }}>{f.unavailable}</div>}
              </div>
              {f.scope === 'entity' && <Switch on={f.firm} disabled={!!f.unavailable} onChange={() => toggle(f, null, f.firm)} />}
            </div>
            {f.scope === 'store' && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px 24px', marginTop: 12 }}>
                {stores.map((s) => (
                  <label key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--grey-800, var(--grey-900))' }}>
                    <Switch on={f.stores[s.id]} disabled={!!f.unavailable} onChange={() => toggle(f, s.id, f.stores[s.id])} />
                    {s.name}
                  </label>
                ))}
              </div>
            )}
          </Card>
        ))}
      </div>
    </>
  )
}
