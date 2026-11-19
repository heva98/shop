import { describedBy, useFieldContext } from './fieldContext.js'

/** Native <select> styled as a DS input. `options`: plain values or
 * {value, label, disabled}. `placeholder` adds a first, unselectable
 * "choose one" option for fields that start empty. Other props pass through. */
export default function Select({
  value, onChange, options = [], placeholder, invalid, className, style, 'aria-describedby': ownDescribedBy, ...rest
}) {
  const field = useFieldContext()
  const isInvalid = invalid ?? field?.invalid ?? false
  return (
    <select
      {...rest}
      className={['ds-input', isInvalid && 'error', className].filter(Boolean).join(' ')}
      value={value}
      onChange={onChange}
      style={style}
      aria-invalid={isInvalid || undefined}
      aria-required={rest.required || field?.required || undefined}
      aria-describedby={describedBy(ownDescribedBy, field?.describedBy)}
    >
      {placeholder != null && <option value="" disabled>{placeholder}</option>}
      {options.map((opt) => {
        const isObject = opt !== null && typeof opt === 'object'
        const optValue = isObject ? opt.value : opt
        const optLabel = isObject ? opt.label : opt
        return <option key={optValue} value={optValue} disabled={isObject ? opt.disabled : undefined}>{optLabel}</option>
      })}
    </select>
  )
}
