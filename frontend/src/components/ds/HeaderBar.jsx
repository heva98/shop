import { useEffect, useRef, useState } from 'react'
import Icon from './Icon.jsx'
import { Menu, MenuDivider, MenuItem } from './Menu.jsx'

/** White 72px top bar (DESIGN.md › TopBar). Left: store picker + role text.
 * Right: online pill + navy avatar. `menuItems`: [{ label, onClick,
 * destructive? } | 'divider'] shown when the avatar is clicked; `menuHeader`
 * renders above them. `stores`: [{ value, label }] for the picker.
 * `unsyncedSales`: sales saved on this till that the cloud hasn't recorded yet. */
export default function HeaderBar({
  storeLabel, roleLabel, stores, activeStore, onStoreChange, isOnline, unsyncedSales = 0, avatarInitials, menuHeader, menuItems,
}) {
  const [open, setOpen] = useState(false)
  const [storeOpen, setStoreOpen] = useState(false)
  const ref = useRef(null)
  const storeRef = useRef(null)

  useEffect(() => {
    if (!open && !storeOpen) return
    const onDown = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
      if (storeRef.current && !storeRef.current.contains(e.target)) setStoreOpen(false)
    }
    const onKey = (e) => { if (e.key === 'Escape') { setOpen(false); setStoreOpen(false) } }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, storeOpen])

  const canSwitch = stores && stores.length > 1

  return (
    <header className="ds-topbar">
      <div className="ds-topbar-left">
        <div ref={storeRef} style={{ position: 'relative', minWidth: 0 }}>
          <button
            type="button"
            className="ds-store-picker"
            aria-haspopup={canSwitch ? 'menu' : undefined}
            aria-expanded={canSwitch ? storeOpen : undefined}
            disabled={!canSwitch}
            onClick={() => setStoreOpen((o) => !o)}
          >
            <Icon name="store" size={18} style={{ color: 'var(--blue-600)' }} />
            <span className="ds-store-picker-label">{storeLabel}</span>
            {canSwitch && <Icon name="chevron-down" size={16} />}
          </button>
          {storeOpen && canSwitch && (
            <Menu style={{ position: 'absolute', left: 0, top: 54, zIndex: 100, minWidth: 280 }}>
              {stores.map((s) => (
                <MenuItem
                  key={s.value}
                  label={s.value === activeStore ? <strong style={{ color: 'var(--navy-800)' }}>{s.label}</strong> : s.label}
                  icon={<Icon name={s.value === activeStore ? 'checkmark' : 'store'} size={16} style={{ color: 'var(--blue-600)' }} />}
                  onClick={() => { setStoreOpen(false); onStoreChange(s.value) }}
                />
              ))}
            </Menu>
          )}
        </div>
        {roleLabel && <span className="ds-topbar-role">{roleLabel}</span>}
      </div>

      <div className="ds-topbar-right">
        <span className={['ds-online', isOnline ? '' : 'offline'].filter(Boolean).join(' ')} role="status">
          <span className="dot" />
          {isOnline
            ? (unsyncedSales > 0 ? `Online · sending ${unsyncedSales} sale${unsyncedSales === 1 ? '' : 's'}` : 'Online')
            : `Offline — keep selling: sales are saved on this till${unsyncedSales > 0 ? ` (${unsyncedSales} waiting)` : ''} and sent when the connection returns`}
        </span>
        <div ref={ref} style={{ position: 'relative' }}>
          <button
            type="button"
            className="ds-avatar"
            aria-label="Account menu"
            aria-haspopup="menu"
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
          >
            {avatarInitials}
          </button>
          {open && menuItems && (
            <Menu style={{ position: 'absolute', right: 0, top: 54, zIndex: 100 }}>
              {menuHeader && (
                <>
                  <div style={{ padding: '8px 12px', color: 'var(--ink)' }}>{menuHeader}</div>
                  <MenuDivider />
                </>
              )}
              {menuItems.map((item, i) => (item === 'divider'
                ? <MenuDivider key={`d${i}`} />
                : (
                  <MenuItem
                    key={item.label}
                    label={item.label}
                    icon={item.icon && <Icon name={item.icon} size={16} />}
                    destructive={item.destructive}
                    onClick={() => { setOpen(false); item.onClick() }}
                  />
                )))}
            </Menu>
          )}
        </div>
      </div>
    </header>
  )
}
