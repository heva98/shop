/** One per screen: page-title plus a one-line muted subtitle (DESIGN.md › Voice). */
export default function PageHeader({ title, subtitle, actions }) {
  return (
    <div className="page-header">
      <div style={{ minWidth: 0 }}>
        <h1 className="page-title">{title}</h1>
        {subtitle && <p className="page-subtitle">{subtitle}</p>}
      </div>
      {actions && <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>{actions}</div>}
    </div>
  )
}
