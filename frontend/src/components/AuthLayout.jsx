import { Icon } from './ds/index.js'
import { BRAND_NAME } from '../appData.js'

const DEFAULT_POINTS = [
  'Real-time inventory & low-stock alerts',
  'Point of sale & fiscal receipts',
  'Customer credit, promotions & reports',
]

/** Login-style page (DESIGN.md › circle motif): white card on blue-700. The
 * left side is a large blue-600 arc with layered circles; `children` is the
 * form on the right. */
export default function AuthLayout({ headline = 'Welcome', overline = 'Shop management system', text, points = DEFAULT_POINTS, children }) {
  return (
    <div className="login-page">
      <span className="login-page-circle a" aria-hidden="true" />
      <span className="login-page-circle b" aria-hidden="true" />
      <div className="login-card">
        <div className="login-art" aria-hidden="true">
          <span className="login-arc" />
          <span className="login-dot big" />
          <span className="login-dot left" />
          <span className="login-dot corner" />
        </div>
        <div className="login-panel">
          <div className="login-brand">
            <span className="login-brand-tile"><Icon name="brand" size={26} /></span>
            <span>{BRAND_NAME}</span>
          </div>
          <p className="login-display">{headline}</p>
          <p className="login-overline">{overline}</p>
          {text && <p className="login-text">{text}</p>}
          {points.length > 0 && (
            <ul className="login-points">
              {points.map((p) => (
                <li key={p}><Icon name="checkmark" size={18} /> {p}</li>
              ))}
            </ul>
          )}
        </div>
        <div className="login-form">{children}</div>
      </div>
    </div>
  )
}
