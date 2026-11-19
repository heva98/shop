import { t } from '../../i18n/index.js'

/** Indeterminate progress ring (DESIGN.md › Loading).
 *
 * Announces itself as a polite status with `label` (default "Loading…").
 * Pass `label={null}` when the surrounding element already says what is
 * busy (e.g. a Button with aria-busy) so screen readers don't hear it twice.
 *
 * `size`: px diameter (default 20). `tone`: 'brand' | 'current' — 'current'
 * takes the text colour, for spinners on coloured buttons. */
export default function Spinner({ size = 20, label, tone = 'brand', className, style }) {
  const text = label === undefined ? t('Loading…') : label
  const ring = (
    <span
      className={['ds-spinner', tone, className].filter(Boolean).join(' ')}
      style={{ width: size, height: size, borderWidth: Math.max(2, Math.round(size / 10)), ...style }}
      aria-hidden="true"
    />
  )
  if (!text) return ring
  return (
    <span role="status" className="ds-spinner-wrap">
      {ring}
      <span className="sr-only">{text}</span>
    </span>
  )
}
