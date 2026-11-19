import { useId, useMemo } from 'react'
import { FieldContext, describedBy } from './fieldContext.js'

/** Label above a form control (DESIGN.md › Input / Select), with an
 * optional hint under it and an error that replaces the hint.
 *
 *   <Field label={t('Selling price')} required hint={t('Per piece, in TZS')} error={errors.price}>
 *     <Input inputMode="decimal" value={price} onChange={…} />
 *   </Field>
 *
 * The control is wrapped in the <label>, so any child is labelled without
 * ids. Input/Select inside also get aria-describedby (hint + error),
 * aria-invalid and aria-required automatically. The error line is a polite
 * live region, so screen readers hear it when it appears.
 *
 * The DOM shape never changes with `error`, so showing an error while the
 * user types doesn't remount the input and steal focus. */
export default function Field({ label, required, hint, error, children, style, className }) {
  const id = useId()
  // The error replaces the hint, so only point at the hint while it's shown.
  const hintId = hint && !error ? `${id}-hint` : undefined
  const errorId = error ? `${id}-error` : undefined
  const invalid = Boolean(error)

  const context = useMemo(
    () => ({ describedBy: describedBy(errorId, hintId), invalid, required: Boolean(required) }),
    [errorId, hintId, invalid, required],
  )

  return (
    <div className={['ds-field', className].filter(Boolean).join(' ')} style={style}>
      <label style={{ display: 'block' }}>
        {label && (
          <span className="ds-label">
            {label}
            {required && <span className="req" aria-hidden="true">*</span>}
          </span>
        )}
        <FieldContext.Provider value={context}>{children}</FieldContext.Provider>
      </label>
      {hintId && <p id={hintId} className="ds-field-hint">{hint}</p>}
      <p id={errorId} className="ds-field-error" aria-live="polite">{error || null}</p>
    </div>
  )
}
