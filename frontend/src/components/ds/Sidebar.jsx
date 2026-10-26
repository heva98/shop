import Icon from './Icon.jsx'

/** Blue app sidebar (DESIGN.md › AppShell / Sidebar): brand row, overline
 * section labels, 44px items with a white active pill, circle motif below. */
export default function Sidebar({ items = [], active, onSelect, collapsed, onToggle, logoUrl, brandName }) {
  const sections = []
  for (const item of items) {
    let section = sections.find((s) => s.name === item.section)
    if (!section) {
      section = { name: item.section, items: [] }
      sections.push(section)
    }
    section.items.push(item)
  }
  const toggleLabel = collapsed ? 'Expand menu' : 'Collapse menu'
  return (
    <aside className={['ds-sb', collapsed ? 'collapsed' : ''].filter(Boolean).join(' ')}>
      <span className="ds-sb-circle c1" aria-hidden="true" />
      <span className="ds-sb-circle c2" aria-hidden="true" />
      <span className="ds-sb-circle c3" aria-hidden="true" />
      <div className="ds-sb-brand">
        <span className="ds-sb-logo">
          {logoUrl ? <img src={logoUrl} alt="" /> : <Icon name="brand" size={22} />}
        </span>
        <span className="ds-sb-name">{brandName}</span>
        <button type="button" className="ds-sb-toggle" onClick={onToggle} title={toggleLabel} aria-label={toggleLabel} aria-expanded={!collapsed}>
          <Icon name={collapsed ? 'panel-open' : 'panel-close'} size={18} />
        </button>
      </div>
      <nav className="ds-sb-nav" aria-label="Main">
        {sections.map((section) => (
          <div key={section.name} className="ds-sb-group">
            <div className="ds-sb-section overline">{section.name}</div>
            {section.items.map((item) => (
              <button
                key={item.id}
                type="button"
                className="ds-sb-item"
                aria-current={item.id === active ? 'page' : undefined}
                title={collapsed ? item.label : undefined}
                onClick={() => onSelect(item.id)}
              >
                <Icon name={item.icon} size={18} />
                <span className="ds-sb-label">{item.label}</span>
              </button>
            ))}
          </div>
        ))}
      </nav>
    </aside>
  )
}
