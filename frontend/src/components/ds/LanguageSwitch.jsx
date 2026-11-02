import { LANGUAGES, setLanguage, t, useLanguage } from '../../i18n/index.js'

/** EN | SW toggle. `tone`: 'light' on white surfaces, 'dark' on blue ones. */
export default function LanguageSwitch({ tone = 'light', style }) {
  const lang = useLanguage()
  return (
    <div className={`ds-lang ${tone}`} role="group" aria-label={t('Language')} style={style}>
      {LANGUAGES.map((l) => (
        <button
          key={l.code} type="button" lang={l.code} title={l.label} aria-label={l.label}
          aria-pressed={l.code === lang} onClick={() => setLanguage(l.code)}
        >
          {l.short}
        </button>
      ))}
    </div>
  )
}
