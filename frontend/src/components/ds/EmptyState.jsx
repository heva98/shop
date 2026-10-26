import Icon from './Icon.jsx'

export default function EmptyState({ icon = 'search', title, hint }) {
  return (
    <div className="ds-empty">
      <span className="ds-empty-disc"><Icon name={icon} size={24} /></span>
      <span className="ds-empty-title">{title}</span>
      {hint && <span className="ds-empty-hint">{hint}</span>}
    </div>
  )
}
