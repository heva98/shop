import { useEffect } from 'react'
import Icon from './Icon.jsx'

// Phone chrome (Mobile Mockups 1b–1d): shown below 640px in place of the
// sidebar and top bar, which app.css hides there.

function BrandMark({ logoUrl, brandName }) {
  return (
    <span className="m-brand">
      <span className="m-brand-tile">{logoUrl ? <img src={logoUrl} alt="" /> : <Icon name="brand" size={20} />}</span>
      <span className="m-brand-name">{brandName}</span>
    </span>
  )
}

/** Blue header: brand, connection dot, avatar, then a full-width store
 * button. `onOpenMenu` opens MobileMenu (which holds the store switcher). */
export function MobileHeader({ logoUrl, brandName, storeLabel, isOnline, unsyncedSales = 0, avatarInitials, onOpenMenu }) {
  const status = isOnline
    ? (unsyncedSales > 0 ? `Online · sending ${unsyncedSales} sale${unsyncedSales === 1 ? '' : 's'}` : 'Online')
    : 'Offline'
  return (
    <header className="m-header">
      <span className="m-circle" aria-hidden="true" />
      <div className="m-header-row">
        <BrandMark logoUrl={logoUrl} brandName={brandName} />
        <span className={['m-status', isOnline ? '' : 'offline'].filter(Boolean).join(' ')} role="status" title={status}>
          <span className="dot" />{isOnline ? (unsyncedSales > 0 ? unsyncedSales : '') : 'Offline'}
          <span className="sr-only">{status}</span>
        </span>
        <button type="button" className="m-avatar" aria-label="Open menu" onClick={onOpenMenu}>{avatarInitials}</button>
      </div>
      <button type="button" className="m-store" onClick={onOpenMenu}>
        <Icon name="store" size={18} />
        <span className="m-store-label">{storeLabel}</span>
        <Icon name="chevron-down" size={18} />
      </button>
      {!isOnline && (
        <p className="m-offline">
          Keep selling: sales are saved on this till{unsyncedSales > 0 ? ` (${unsyncedSales} waiting)` : ''} and sent when the connection returns.
        </p>
      )}
    </header>
  )
}

/** Bottom tab bar: up to three `tabs` ({ id, label, icon }) plus "More",
 * which is active whenever the current screen isn't one of the tabs. */
export function MobileTabBar({ tabs, active, onSelect, onMore }) {
  const onTab = tabs.some((t) => t.id === active)
  const all = [...tabs.map((t) => ({ ...t, on: t.id === active, click: () => onSelect(t.id) })), { id: 'more', label: 'More', icon: 'menu', on: !onTab, click: onMore }]
  return (
    <nav className="m-tabs" aria-label="Main" style={{ gridTemplateColumns: `repeat(${all.length},minmax(0,1fr))` }}>
      {all.map((t) => (
        <button key={t.id} type="button" className="m-tab" aria-current={t.on ? 'page' : undefined} onClick={t.click}>
          <span className="m-tab-pill"><Icon name={t.icon} size={20} /></span>
          {t.label}
        </button>
      ))}
    </nav>
  )
}

/** Full-screen blue menu: user card, store switcher, every nav section,
 * then account actions. `stores`: [{ value, label, entity? }]. */
export function MobileMenu({
  logoUrl, brandName, avatarInitials, userName, userRole, stores = [], activeStore, onStoreChange, items = [], active, onSelect,
  accountItems = [], onClose,
}) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = overflow
    }
  }, [onClose])

  const sections = []
  for (const item of items) {
    let section = sections.find((s) => s.name === item.section)
    if (!section) {
      section = { name: item.section, items: [] }
      sections.push(section)
    }
    section.items.push(item)
  }

  return (
    <div className="m-menu" role="dialog" aria-modal="true" aria-label="Menu">
      <span className="m-menu-circle a" aria-hidden="true" />
      <span className="m-menu-circle b" aria-hidden="true" />
      <div className="m-menu-scroll">
        <div className="m-header-row">
          <BrandMark logoUrl={logoUrl} brandName={brandName} />
          <button type="button" className="m-icon-btn" aria-label="Close menu" onClick={onClose} autoFocus><Icon name="cross" size={20} /></button>
        </div>
        <div className="m-user">
          <span className="m-avatar large">{avatarInitials}</span>
          <div style={{ minWidth: 0 }}>
            <div className="m-user-name">{userName}</div>
            {userRole && <div className="m-user-role">{userRole}</div>}
          </div>
        </div>
        {stores.length > 1 && (
          <div className="m-menu-group">
            <div className="m-menu-section overline">Store</div>
            {stores.map((s) => {
              const on = s.value === activeStore
              return (
                <button
                  key={s.value} type="button" className="m-store-opt" aria-pressed={on}
                  onClick={() => { onStoreChange(s.value); onClose() }}
                >
                  <Icon name={s.entity ? 'admin' : 'store'} size={18} />
                  <span className="m-store-label">{s.label}</span>
                  {on && <Icon name="checkmark" size={18} />}
                </button>
              )
            })}
          </div>
        )}
        {sections.map((section) => (
          <div key={section.name} className="m-menu-group">
            <div className="m-menu-section overline">{section.name}</div>
            {section.items.map((item) => (
              <button
                key={item.id} type="button" className="m-menu-item" aria-current={item.id === active ? 'page' : undefined}
                onClick={() => { onSelect(item.id); onClose() }}
              >
                <Icon name={item.icon} size={18} />{item.label}
              </button>
            ))}
          </div>
        ))}
        <div className="m-menu-group m-menu-account">
          {accountItems.map((item) => (
            <button key={item.label} type="button" className="m-menu-item" onClick={() => { onClose(); item.onClick() }}>
              <Icon name={item.icon} size={18} />{item.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
