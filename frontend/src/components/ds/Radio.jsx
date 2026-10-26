export default function Radio({ checked, onChange, label, disabled, style }) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={!!checked}
      disabled={!!disabled}
      className={['ds-check', 'ds-radio', checked ? 'checked' : '', disabled ? 'disabled' : ''].filter(Boolean).join(' ')}
      onClick={() => { if (!disabled && !checked && onChange) onChange() }}
      style={style}
    >
      <span className="box" />
      {label && <span>{label}</span>}
    </button>
  )
}
