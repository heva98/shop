import { useEffect, useId, useRef } from 'react'
import Icon from './Icon.jsx'

/** Centred dialog over a dimmed page. Escape or a left click on the backdrop closes it.
 * `footer` renders in a bar under the body (buttons, right-aligned);
 * `size`: 'sm' | 'md' | 'lg' | 'xl'. */
export default function Modal({ title, onClose, size = 'md', footer, children }) {
  const titleId = useId()
  const ref = useRef(null)

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    // Focus the dialog unless something inside asked for it (autoFocus).
    if (!ref.current?.contains(document.activeElement)) ref.current?.focus()
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = overflow
    }
  }, [onClose])

  // Close only on a left click that both starts and ends on the backdrop, so a
  // right-click (context menu / inspect) or a text selection dragged out of the
  // dialog doesn't throw away what was typed.
  const pressedBackdrop = useRef(false)
  const onBackdropDown = (e) => { pressedBackdrop.current = e.button === 0 && e.target === e.currentTarget }
  const onBackdropClick = (e) => {
    if (pressedBackdrop.current && e.button === 0 && e.target === e.currentTarget) onClose()
    pressedBackdrop.current = false
  }

  return (
    <div className="ds-modal-backdrop" onMouseDown={onBackdropDown} onClick={onBackdropClick}>
      <div ref={ref} className={`ds-modal ${size}`} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
        <header className="ds-modal-head">
          <h2 id={titleId} className="ds-modal-title">{title}</h2>
          <button type="button" className="ds-icon-btn" aria-label="Close" onClick={onClose}><Icon name="cross" size={18} /></button>
        </header>
        <div className="ds-modal-body">{children}</div>
        {footer && <footer className="ds-modal-foot">{footer}</footer>}
      </div>
    </div>
  )
}
