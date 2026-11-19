import Icon from './Icon.jsx'
import { describedBy, useFieldContext } from './fieldContext.js'

/** Text field (DESIGN.md › Input / Select).
 *
 * Every native <input> prop passes through (name, autoComplete, onBlur,
 * min/max, list, required, aria-*, and `ref` — a plain prop in React 19).
 * `prefixIcon` puts an 18px icon inside on the left. `invalid` draws the
 * error outline; inside a Field with an `error` that happens on its own.
 * `style` sizes the outer box, `inputStyle` the <input> itself. */
export default function Input({
  prefixIcon, disabled, invalid, style, inputStyle, className, 'aria-describedby': ownDescribedBy, ...rest
}) {
  const field = useFieldContext()
  const isInvalid = invalid ?? field?.invalid ?? false
  return (
    <div style={{ position: 'relative', width: '100%', ...style }}>
      {prefixIcon && <span className="ds-input-icon"><Icon name={prefixIcon} size={18} /></span>}
      <input
        type="text"
        {...rest}
        className={['ds-input', disabled && 'disabled', isInvalid && 'error', className].filter(Boolean).join(' ')}
        disabled={!!disabled}
        aria-invalid={isInvalid || undefined}
        aria-required={rest.required || field?.required || undefined}
        aria-describedby={describedBy(ownDescribedBy, field?.describedBy)}
        style={prefixIcon ? { paddingLeft: 42, ...inputStyle } : inputStyle}
      />
    </div>
  )
}
