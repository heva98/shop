import Icon from './Icon.jsx'

/** `action`: a button (or a few) that does the first thing to fill the empty space. */
export default function EmptyState({ icon = 'search', title, hint, action }) {
  return (
    <div className="ds-empty">
      <span className="ds-empty-disc"><Icon name={icon} size={24} /></span>
      <span className="ds-empty-title">{title}</span>
      {hint && <span className="ds-empty-hint">{hint}</span>}
      {action && <span className="ds-empty-action">{action}</span>}
    </div>
  )
}
