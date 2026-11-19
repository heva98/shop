import Icon from './Icon.jsx'
import Spinner from './Spinner.jsx'

/** Button (DESIGN.md › Button).
 *
 * `variant`: default (outlined) | 'primary' | 'secondary' | 'destructive'.
 * `size`: default | 'small' | 'large'. `icon` puts a DS icon before the label.
 *
 * `loading` shows a spinner over the label and ignores clicks, but keeps
 * the button focusable and the same width: a disabled button would drop
 * keyboard focus to <body> mid-save, and a shrinking one makes the layout
 * jump. Screen readers hear it as busy (aria-busy) and unavailable
 * (aria-disabled). It also blocks a submit button's form submission.
 *
 * Every other native <button> prop (aria-*, form, ref, …) passes through. */
export default function Button({
  variant, size, disabled, loading = false, icon, onClick, children, className, type = 'button', ...rest
}) {
  const cls = ['ds-btn', variant, size, disabled && 'disabled', loading && 'loading', className].filter(Boolean).join(' ')

  function handleClick(e) {
    if (loading) { e.preventDefault(); return }
    onClick?.(e)
  }

  return (
    <button
      type={type}
      {...rest}
      className={cls}
      disabled={!!disabled}
      aria-disabled={loading || undefined}
      aria-busy={loading || undefined}
      onClick={handleClick}
    >
      {loading && <span className="ds-btn-spinner"><Spinner size={size === 'small' ? 14 : 16} tone="current" label={null} /></span>}
      {icon && <Icon name={icon} size={size === 'small' ? 16 : 18} />}
      {children}
    </button>
  )
}
