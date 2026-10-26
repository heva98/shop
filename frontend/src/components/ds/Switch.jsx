export default function Switch({ on, onChange, disabled, label, style }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={!!on}
      disabled={!!disabled}
      className="ds-switch"
      onClick={() => { if (!disabled && onChange) onChange() }}
      style={style}
    >
      <span className="track"><span className="thumb" /></span>
      {label && <span>{label}</span>}
    </button>
  )
}
