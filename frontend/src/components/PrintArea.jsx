import { createPortal } from 'react-dom'

/** Content that is invisible on screen and is the only thing printed when
 * window.print() runs (see .print-area in app.css). kind="receipt" prints
 * on an 80mm thermal roll; kind="report" on a normal A4 page, which the
 * browser's print dialog can also "Save as PDF". */
export default function PrintArea({ kind = 'report', children }) {
  return createPortal(<div className={`print-area ${kind}`}>{children}</div>, document.body)
}
