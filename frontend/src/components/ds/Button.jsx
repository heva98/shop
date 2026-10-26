export default function Button({ variant, size, disabled, onClick, children, style, type = 'button', ...rest }) {
  const cls = ['ds-btn', variant, size, disabled ? 'disabled' : ''].filter(Boolean).join(' ')
  return (
    <button type={type} className={cls} disabled={!!disabled} onClick={onClick} style={style} {...rest}>
      {children}
    </button>
  )
}
