import Icon from './Icon.jsx'

const ICON_BY_VARIANT = { info: 'info', valid: 'checkmark' }

/** Alert banner (DESIGN.md › Alert banner): coloured disc, title, body and an
 * optional `action` on the right. Without a title it renders as a compact row. */
export default function NoticeBox({ variant = 'info', title, children, action, style }) {
  const compact = !title
  const icon = ICON_BY_VARIANT[variant]
  return (
    <div
      className={['ds-notice', variant, compact ? 'compact' : ''].filter(Boolean).join(' ')}
      role={variant === 'warning' || variant === 'error' ? 'alert' : 'status'}
      style={style}
    >
      <span className="icon" aria-hidden="true">
        {icon
          ? <Icon name={icon} size={compact ? 16 : 20} strokeWidth={2.5} />
          : <span style={{ fontWeight: 700, fontSize: compact ? 15 : 20, lineHeight: 1 }}>!</span>}
      </span>
      <div className="body">
        {title && <p className="title">{title}</p>}
        {children && <div className="msg">{children}</div>}
      </div>
      {action && <div style={{ flex: '0 0 auto', alignSelf: 'center' }}>{action}</div>}
    </div>
  )
}
