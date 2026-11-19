import { useEffect, useId, useRef, useState } from 'react'
import Icon from './Icon.jsx'
import { t } from '../../i18n/index.js'

// Open dialogs, innermost last: only the top one answers Escape and keeps
// Tab inside itself, and the page scroll lock is lifted when the last closes.
const stack = []
let savedOverflow = ''

const FOCUSABLE = [
  'a[href]', 'area[href]', 'button:not([disabled])', 'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])', 'textarea:not([disabled])', 'iframe', '[contenteditable="true"]',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

function focusableIn(root) {
  return [...root.querySelectorAll(FOCUSABLE)].filter((el) => el.getClientRects().length > 0)
}

/** Centred dialog over a dimmed page (DESIGN.md › Modal).
 *
 * `title` names the dialog; `footer` renders in a bar under the body
 * (buttons, right-aligned); `size`: 'sm' | 'md' | 'lg' | 'xl'.
 * `initialFocus`: a ref to focus on open (else an autoFocus child, else
 * the dialog itself). `dismissible={false}` hides the close button and
 * ignores Escape / backdrop clicks, for a save that must not be cut short.
 *
 * Accessibility: role="dialog" + aria-modal, labelled by the title; Tab and
 * Shift+Tab stay inside; focus goes back to whatever opened it on close;
 * nested dialogs close one at a time. */
export default function Modal({ title, onClose, size = 'md', footer, children, initialFocus, dismissible = true }) {
  const titleId = useId()
  const ref = useRef(null)
  // Read during the first render, before an autoFocus child inside the
  // dialog takes focus, so this is the button that opened it.
  const [opener] = useState(() => (typeof document === 'undefined' ? null : document.activeElement))
  // Latest props in refs so the open/close effect runs once, not on every
  // parent render that passes a fresh `onClose` arrow.
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose
  const dismissibleRef = useRef(dismissible)
  dismissibleRef.current = dismissible

  useEffect(() => {
    const node = ref.current
    stack.push(node)
    if (stack.length === 1) {
      savedOverflow = document.body.style.overflow
      document.body.style.overflow = 'hidden'
    }

    if (initialFocus?.current) initialFocus.current.focus()
    else if (!node.contains(document.activeElement)) node.focus()

    const onKey = (e) => {
      if (stack[stack.length - 1] !== node) return
      if (e.key === 'Escape' && dismissibleRef.current) {
        e.stopPropagation()
        onCloseRef.current?.()
      } else if (e.key === 'Tab') {
        const items = focusableIn(node)
        if (items.length === 0) { e.preventDefault(); node.focus(); return }
        const first = items[0]
        const last = items[items.length - 1]
        if (e.shiftKey && (document.activeElement === first || document.activeElement === node)) {
          e.preventDefault(); last.focus()
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault(); first.focus()
        }
      }
    }
    document.addEventListener('keydown', onKey)

    return () => {
      document.removeEventListener('keydown', onKey)
      stack.splice(stack.indexOf(node), 1)
      if (stack.length === 0) document.body.style.overflow = savedOverflow
      // Hand focus back to the opener if it's still on the page.
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus({ preventScroll: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Close only on a left click that both starts and ends on the backdrop, so a
  // right-click (context menu / inspect) or a text selection dragged out of the
  // dialog doesn't throw away what was typed.
  const pressedBackdrop = useRef(false)
  const onBackdropDown = (e) => { pressedBackdrop.current = e.button === 0 && e.target === e.currentTarget }
  const onBackdropClick = (e) => {
    if (dismissible && pressedBackdrop.current && e.button === 0 && e.target === e.currentTarget) onClose()
    pressedBackdrop.current = false
  }

  return (
    <div className="ds-modal-backdrop" onMouseDown={onBackdropDown} onClick={onBackdropClick}>
      <div ref={ref} className={`ds-modal ${size}`} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
        <header className="ds-modal-head">
          <h2 id={titleId} className="ds-modal-title">{title}</h2>
          {dismissible && (
            <button type="button" className="ds-icon-btn" aria-label={t('Close')} onClick={onClose}><Icon name="cross" size={18} /></button>
          )}
        </header>
        <div className="ds-modal-body">{children}</div>
        {footer && <footer className="ds-modal-foot">{footer}</footer>}
      </div>
    </div>
  )
}
