export default function Tag({ variant, bold, dot, children, style }) {
  const cls = ['ds-tag', variant, bold ? 'bold' : ''].filter(Boolean).join(' ')
  return <span className={cls} style={style}>{dot && <span className="dot" />}{children}</span>
}
