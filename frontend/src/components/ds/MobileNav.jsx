import { useEffect } from 'react'
import Icon from './Icon.jsx'
import LanguageSwitch from './LanguageSwitch.jsx'
import { t, useT } from '../../i18n/index.js'

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
  useT()
  const status = isOnline
    ? (unsyncedSales > 0 ? t(unsyncedSales === 1 ? 'Online · sending {n} sale' : 'Online · sending {n} sales', { n: unsyncedSales }) : t('Online'))
    : t('Offline')
  return (
    <header className="m-header">
      <span className="m-circle" aria-hidden="true" />
      <div className="m-header-row">
        <BrandMark logoUrl={logoUrl} brandName={brandName} />
        <span className={['m-status', isOnline ? '' : 'offline'].filter(Boolean).join(' ')} role="status" title={status}>
          <span className="dot" />{isOnline ? (unsyncedSales > 0 ? unsyncedSales : '') : t('Offline')}
          <span className="sr-only">{status}</span>
        </span>
        <button type="button" className="m-avatar" aria-label={t('Open menu')} onClick={onOpenMenu}>{avatarInitials}</button>
      </div>
      <button type="button" className="m-store" onClick={onOpenMenu}>
        <Icon name="store" size={18} />
        <span className="m-store-label">{storeLabel}</span>
        <Icon name="chevron-down" size={18} />
      </button>
      {!isOnline && (
        <p className="m-offline">
          {unsyncedSales > 0
            ? t('Keep selling: sales are saved on this till ({n} waiting) and sent when the connection returns.', { n: unsyncedSales })
            : t('Keep selling: sales are saved on this till and sent when the connection returns.')}
        </p>
      )}
    </header>
  )
}

/** Bottom tab bar: up to three `tabs` ({ id, label, icon }) plus "More",
 * which is active whenever the current screen isn't one of the tabs. */
export function MobileTabBar({ tabs, active, onSelect, onMore }) {
  useT()
  const onTab = tabs.some((tab) => tab.id === active)
  const all = [...tabs.map((tab) => ({ ...tab, on: tab.id === active, click: () => onSelect(tab.id) })), { id: 'more', label: t('More'), icon: 'menu', on: !onTab, click: onMore }]
  return (
    <nav className="m-tabs" aria-label={t('Main')} style={{ gridTemplateColumns: `repeat(${all.length},minmax(0,1fr))` }}>
      {all.map((tab) => (
        <button key={tab.id} type="button" className="m-tab" aria-current={tab.on ? 'page' : undefined} onClick={tab.click}>
          <span className="m-tab-pill"><Icon name={tab.icon} size={20} /></span>
          {tab.label}
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
  useT()
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
    <div className="m-menu" role="dialog" aria-modal="true" aria-label={t('Menu')}>
      <span className="m-menu-circle a" aria-hidden="true" />
      <span className="m-menu-circle b" aria-hidden="true" />
      <div className="m-menu-scroll">
        <div className="m-header-row">
          <BrandMark logoUrl={logoUrl} brandName={brandName} />
          <button type="button" className="m-icon-btn" aria-label={t('Close menu')} onClick={onClose} autoFocus><Icon name="cross" size={20} /></button>
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
            <div className="m-menu-section overline">{t('Store')}</div>
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
          <div className="m-menu-item" style={{ justifyContent: 'space-between', cursor: 'default' }}>
            {t('Language')}
            <LanguageSwitch tone="dark" />
          </div>
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
