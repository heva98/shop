import { useState } from 'react'
import { Button, Checkbox, Field, Icon, Input, Modal, NoticeBox } from '../../../components/ds/index.js'
import { listVisualizations } from '../../../api/analytics.js'
import { useApi } from '../../../hooks/useApi.js'
import { unavailableMessage } from '../savedVisualizations.js'
import { VISUALIZATION_TYPES } from '../visualizationConfig.js'
import { t, useT } from '../../../i18n/index.js'

const typeLabel = (id) => VISUALIZATION_TYPES.find((type) => type.id === id)?.label

export function OpenVisualizationModal({ currentId, onOpen, onClose }) {
  useT()
  const [search, setSearch] = useState('')
  const list = useApi(() => listVisualizations(), [])

  const needle = search.trim().toLowerCase()
  const rows = (list.data ?? []).filter((v) => !needle || v.name.toLowerCase().includes(needle))

  let body
  if (list.loading) body = <p className="viz-empty-row">{t('Loading…')}</p>
  else if (list.error) body = <NoticeBox variant="error">{t('Saved visualizations could not be loaded.')}</NoticeBox>
  else if (!rows.length) {
    body = (
      <p className="viz-empty-row">
        {list.data.length ? t('No visualization matches that name.') : t('Nothing saved yet. Build a visualization and choose File → Save as.')}
      </p>
    )
  } else {
    body = (
      <ul className="viz-open-list" style={{ margin: '0 -20px -20px' }}>
        {rows.map((v) => {
          const problem = unavailableMessage(v.unavailable)
          return (
            <li key={v.id}>
              <button type="button" onClick={() => onOpen(v)} className={`viz-open-item${v.id === currentId ? ' current' : ''}`}>
                <span className="viz-open-name">
                  <span>{v.name}</span>
                  {v.is_pinned && <Icon name="pin" size={13} style={{ color: 'var(--muted)' }} />}
                  {v.shared && <span className="viz-muted">· Shared</span>}
                  <span className="viz-muted" style={{ marginLeft: 'auto' }}>{typeLabel(v.type) ?? v.type}</span>
                </span>
                {v.description && <p className="viz-open-meta">{v.description}</p>}
                {!v.is_owner && <p className="viz-open-meta">By {v.created_by_name}</p>}
                {problem && <p className="viz-open-meta" style={{ color: 'var(--orange-fg)' }}>{problem}</p>}
              </button>
            </li>
          )
        })}
      </ul>
    )
  }

  return (
    <Modal title={t('Open visualization')} onClose={onClose} size="md">
      <div style={{ marginBottom: 16 }}>
        <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t('Search by name')} prefixIcon="search" />
      </div>
      {body}
    </Modal>
  )
}

/**
 * Name, description and sharing for Save as / Rename. `onSubmit` returns a
 * promise; a rejection's message is shown in the dialog.
 */
export function SaveVisualizationModal({ title, submitLabel, initial, onSubmit, onClose }) {
  useT()
  const [name, setName] = useState(initial?.name ?? '')
  const [description, setDescription] = useState(initial?.description ?? '')
  const [shared, setShared] = useState(initial?.shared ?? false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function submit(e) {
    e?.preventDefault()
    if (!name.trim()) {
      setError(t('Give the visualization a name.'))
      return
    }
    setBusy(true)
    setError(null)
    try {
      await onSubmit({ name: name.trim(), description: description.trim(), shared })
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  const footer = (
    <>
      <Button onClick={onClose}>{t('Cancel')}</Button>
      <Button variant="primary" onClick={submit} disabled={busy}>{busy ? t('Saving…') : submitLabel}</Button>
    </>
  )

  return (
    <Modal title={title} onClose={onClose} size="sm" footer={footer}>
      <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <Field label={t('Name')} required>
          <Input value={name} onChange={(e) => setName(e.target.value.slice(0, 150))} placeholder={t('e.g. Monthly sales by store')} />
        </Field>
        <Field label={t('Description (optional)')}>
          <textarea className="ds-input" rows={3} value={description} onChange={(e) => setDescription(e.target.value)}
            style={{ height: 'auto', padding: '10px 14px', resize: 'vertical' }} />
        </Field>
        <div>
          <Checkbox checked={shared} onChange={() => setShared((s) => !s)} label={t('Share with colleagues')} />
          <p className="viz-help" style={{ marginTop: 0 }}>
            {t('Managers and admins in this shop can open and pin it. Each person only sees the stores they work at.')}
          </p>
        </div>
        {error && <NoticeBox variant="error">{error}</NoticeBox>}
        <button type="submit" hidden />
      </form>
    </Modal>
  )
}
