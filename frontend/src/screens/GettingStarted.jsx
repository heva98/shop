import { useState } from 'react'
import { Button, Card, Icon } from '../components/ds/index.js'
import QuickAddProduct from '../components/QuickAddProduct.jsx'
import { useApi } from '../hooks/useApi.js'
import { getGettingStarted } from '../api/catalog.js'
import { useT } from '../i18n/index.js'

const HIDDEN_KEY = 'shop.gettingStarted.hidden'

function isHidden(entityId) {
  try { return localStorage.getItem(`${HIDDEN_KEY}.${entityId}`) === '1' } catch { return false }
}
function hide(entityId) {
  try { localStorage.setItem(`${HIDDEN_KEY}.${entityId}`, '1') } catch { /* storage blocked: it just shows again */ }
}

/** The owner's first-day checklist on the dashboard. Every step is ticked
 * from the shop's own data, has a button that does it, and the card goes
 * away once the shop has products ready to sell and a first sale. */
export default function GettingStarted({ entity, storeId, goTo, canGo, onChanged }) {
  const t = useT()
  const [hidden, setHidden] = useState(() => isHidden(entity?.id))
  const [dialog, setDialog] = useState(null) // { product? } while the quick-add form is open
  const { data: s, refetch } = useApi(() => (hidden ? null : getGettingStarted({ store: storeId || undefined })), [storeId, hidden])
  if (hidden || !s) return null

  const ready = s.products > 0 && s.without_price === 0 && s.without_stock === 0
  if (ready && s.sales > 0) return null
  const go = (screen, params) => (canGo(screen) ? () => goTo(screen, params) : null)
  const steps = [
    {
      key: 'products', done: s.products > 0, title: t('Add the products you sell'),
      text: s.products > 0
        ? t(s.products === 1 ? 'You have {n} product.' : 'You have {n} products.', { n: s.products })
        : t('Type them one by one with their price and how many you have, or load them all from an Excel sheet.'),
      actions: [
        { label: t('Add a product'), primary: s.products === 0, onClick: () => setDialog({}) },
        { label: t('Import from Excel'), onClick: go('settings', { tab: 'import' }) },
      ],
    },
    {
      key: 'ready', done: s.products > 0 && ready, title: t('Give each product a price and its stock'),
      text: s.products === 0
        ? t('A product can be sold once it has a selling price and stock on the shelf.')
        : ready ? t('Every product has a price and stock.')
          : t('{price} without a price, {stock} without stock. Finish them here:', {
            price: s.without_price, stock: s.without_stock,
          }),
      list: !ready && s.unready,
    },
    {
      key: 'sale', done: s.sales > 0, title: t('Make your first sale'),
      text: t('Open the till, count the cash in the drawer, then search or scan a product and take the payment.'),
      actions: [{ label: t('Open the till'), primary: ready, onClick: go('pos') }],
    },
    {
      key: 'staff', done: s.staff > 0, optional: true, title: t('Add the people who work with you'),
      text: t('Give each seller their own sign-in, so you can see who sold what. You can skip this if you work alone.'),
      actions: [{ label: t('Add a seller'), onClick: go('admin', { tab: 'users' }) }],
    },
  ]
  const doneCount = steps.filter((st) => st.done).length
  const saved = () => { refetch(); onChanged?.() }

  return (
    <Card
      className="gs-card"
      title={t('Get your shop ready')}
      meta={t('{done} of {total} done', { done: doneCount, total: steps.length })}
      action={<Button size="small" onClick={() => { hide(entity?.id); setHidden(true) }}>{t('Hide this list')}</Button>}
    >
      <ol className="gs-steps">
        {steps.map((st, i) => (
          <li key={st.key} className={st.done ? 'done' : ''}>
            <span className="gs-mark" aria-hidden="true">{st.done ? <Icon name="checkmark" size={16} /> : i + 1}</span>
            <div className="gs-body">
              <div className="gs-title">
                {st.title}
                {st.optional && <span className="gs-optional">{t('optional')}</span>}
                <span className="sr-only">{st.done ? t('Done') : t('Not done yet')}</span>
              </div>
              <p className="gs-text">{st.text}</p>
              {st.list && st.list.length > 0 && (
                <ul className="gs-list">
                  {st.list.map((p) => (
                    <li key={p.id}>
                      <span>
                        {p.name}
                        <span className="gs-missing">
                          {[!p.has_price && t('no price'), Number(p.qty) <= 0 && t('no stock')].filter(Boolean).join(' · ')}
                        </span>
                      </span>
                      <Button size="small" onClick={() => setDialog({ product: p })}>{t('Set price and stock')}</Button>
                    </li>
                  ))}
                </ul>
              )}
              {!st.done && st.actions && (
                <div className="gs-actions">
                  {st.actions.filter((a) => a.onClick).map((a) => (
                    <Button key={a.label} size="small" variant={a.primary ? 'primary' : undefined} onClick={a.onClick}>{a.label}</Button>
                  ))}
                </div>
              )}
            </div>
          </li>
        ))}
      </ol>
      {dialog && <QuickAddProduct product={dialog.product} storeId={storeId} onClose={() => setDialog(null)} onSaved={saved} />}
    </Card>
  )
}
