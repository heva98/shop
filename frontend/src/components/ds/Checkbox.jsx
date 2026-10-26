export default function Checkbox({ checked, onChange, label, disabled, style }) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={!!checked}
      disabled={!!disabled}
      className={['ds-check', checked ? 'checked' : '', disabled ? 'disabled' : ''].filter(Boolean).join(' ')}
      onClick={() => { if (!disabled && onChange) onChange() }}
      style={style}
    >
      <span className="box" />
      {label && <span>{label}</span>}
    </button>
  )
}
