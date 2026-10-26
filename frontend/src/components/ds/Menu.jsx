export function Menu({ children, style }) {
  return <div className="ds-menu" role="menu" style={style}>{children}</div>
}

export function MenuItem({ label, icon, destructive, disabled, onClick }) {
  return (
    <button
      type="button"
      role="menuitem"
      disabled={!!disabled}
      className={['ds-menu-item', destructive ? 'destructive' : '', disabled ? 'disabled' : ''].filter(Boolean).join(' ')}
      onClick={disabled ? undefined : onClick}
    >
      {icon}
      <span>{label}</span>
    </button>
  )
}

export function MenuDivider() {
  return <div className="ds-menu-divider" role="separator" />
}

export default Menu
