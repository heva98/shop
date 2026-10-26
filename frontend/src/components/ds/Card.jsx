/** `title`/`meta`/`action` render the chart-card style header (DESIGN.md ›
 * Charts) above a padded body; without them the card is a plain padded box. */
export default function Card({ children, style, title, meta, action, flush, className, bodyStyle }) {
  if (title) {
    return (
      <section className={['ds-card', 'flush', className].filter(Boolean).join(' ')} style={style}>
        <header className="ds-card-head">
          <div style={{ minWidth: 0 }}>
            <h3 className="card-title">{title}</h3>
            {meta && <p style={{ margin: 0, fontSize: 13, lineHeight: '20px', color: 'var(--muted)' }}>{meta}</p>}
          </div>
          {action}
        </header>
        <div className="ds-card-body" style={bodyStyle}>{children}</div>
      </section>
    )
  }
  return <div className={['ds-card', flush ? 'flush' : '', className].filter(Boolean).join(' ')} style={style}>{children}</div>
}
