// What every settings panel shares besides components: add/edit form
// state, the VAT choices and common styles.
import { useState } from 'react'
import { t } from '../../i18n/index.js'
import { useAsyncAction } from '../../hooks/useAsyncAction.js'

export const VAT_OPTIONS = [
  { value: 'exempt', label: 'Exempt' }, { value: 'zero_rated', label: 'Zero-rated' }, { value: 'standard', label: 'Standard (18%)' },
]

export const VAT_LABEL = Object.fromEntries(VAT_OPTIONS.map((o) => [o.value, o.label]))

/** Shared add/edit form state: `save` gets the draft and returns a promise. */
export function useForm(initial) {
  const [draft, setDraft] = useState(null)
  const { busy, error, setError, run } = useAsyncAction()
  return {
    draft, error, busy,
    open: (values) => { setDraft({ ...initial, ...values }); setError('') },
    close: () => setDraft(null),
    set: (field) => (e) => setDraft((d) => ({ ...d, [field]: e?.target ? (e.target.type === 'checkbox' ? e.target.checked : e.target.value) : e })),
    toggle: (field) => () => setDraft((d) => ({ ...d, [field]: !d[field] })),
    submit(save, onDone) {
      return run(async () => {
        await save(draft)
        setDraft(null)
        onDone?.()
      }, t('Could not save.'))
    },
  }
}

export const omit = (obj, key) => Object.fromEntries(Object.entries(obj).filter(([k]) => k !== key))

export const introStyle = { fontSize: 14, color: 'var(--fg-muted)', margin: '0 0 16px', maxWidth: 640 }

export const gridStyle = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 12 }
