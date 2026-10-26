import Icon from './Icon.jsx'

/** KPI card. `unit` (e.g. "TZS") is set smaller and muted before the value;
 * `tone="orange"` marks alert-type KPIs. With `onClick` the card is a button. */
export default function StatCard({ label, value, unit, caption, icon, tone, onClick }) {
  const Root = onClick ? 'button' : 'div'
  return (
    <Root type={onClick ? 'button' : undefined} className="ds-card ds-stat" onClick={onClick}>
      <span className="ds-stat-top">
        <span className="ds-stat-label">{label}</span>
        {icon && <span className={['ds-stat-tile', tone].filter(Boolean).join(' ')}><Icon name={icon} size={22} /></span>}
      </span>
      <span className="ds-stat-value">{unit && <span className="unit">{unit}</span>}{value}</span>
      {caption && <span className="ds-stat-caption">{caption}</span>}
    </Root>
  )
}
