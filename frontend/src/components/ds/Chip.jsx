export default function Chip({ selected, dense, onClick, children, style }) {
  return (
    <button
      type="button"
      aria-pressed={!!selected}
      className={['ds-chip', selected ? 'selected' : '', dense ? 'dense' : ''].filter(Boolean).join(' ')}
      onClick={onClick}
      style={style}
    >
      {children}
    </button>
  )
}
