import { useState } from 'react'
import { PageHeader, SubNav } from '../components/ds/index.js'
import { isPharmacy } from '../appData.js'
import { t, useT } from '../i18n/index.js'
import ProductsPanel from './settings/ProductsPanel.jsx'
import GenericsPanel from './settings/GenericsPanel.jsx'
import UomPanel from './settings/UomPanel.jsx'
import SuppliersPanel from './settings/SuppliersPanel.jsx'
import PricingPanel from './settings/PricingPanel.jsx'
import ReorderPanel from './settings/ReorderPanel.jsx'
import PaymentMethodsPanel from './settings/PaymentMethodsPanel.jsx'
import PromotionsPanel from './settings/PromotionsPanel.jsx'
import ImportPanel from './settings/ImportPanel.jsx'
import NotificationsPanel from './settings/NotificationsPanel.jsx'
import FeaturesPanel from './settings/FeaturesPanel.jsx'

const TABS = [
  { key: 'products', label: 'Products' },
  { key: 'uom', label: 'Units (piece, packet…)' },
  { key: 'suppliers', label: 'Suppliers' },
  { key: 'pricing', label: 'Selling prices' },
  { key: 'promotions', label: 'Promotions' },
  { key: 'reorder', label: 'Low-stock warnings' },
  { key: 'payment-methods', label: 'Payment methods' },
  { key: 'notifications', label: 'Notifications' },
  { key: 'import', label: 'Import from Excel' },
  { key: 'features', label: 'Features' },
]

export default function Settings({ entity, initialTab }) {
  useT()
  // Pharmacies also keep their generic medicines here.
  const tabs = isPharmacy(entity) ? [TABS[0], { key: 'generics', label: 'Generic medicines' }, ...TABS.slice(1)] : TABS
  const [tab, setTab] = useState(tabs.some((s) => s.key === initialTab) ? initialTab : 'products')
  return (
    <div>
      <PageHeader title={t('Settings')} subtitle={t('Your products, suppliers and prices, and how the system works for your shop.')} />
      <div className="ds-subnav-layout">
        <SubNav label={t('Settings sections')} items={tabs.map((s) => ({ ...s, label: t(s.label), active: tab === s.key, select: () => setTab(s.key) }))} />
        <div className="ds-subnav-content">
          {tab === 'products' && <ProductsPanel entity={entity} />}
          {tab === 'generics' && <GenericsPanel entity={entity} />}
          {tab === 'uom' && <UomPanel entity={entity} />}
          {tab === 'suppliers' && <SuppliersPanel entity={entity} />}
          {tab === 'pricing' && <PricingPanel entity={entity} />}
          {tab === 'reorder' && <ReorderPanel />}
          {tab === 'payment-methods' && <PaymentMethodsPanel />}
          {tab === 'notifications' && <NotificationsPanel />}
          {tab === 'import' && <ImportPanel entity={entity} />}
          {tab === 'promotions' && <PromotionsPanel entity={entity} />}
          {tab === 'features' && <FeaturesPanel />}
        </div>
      </div>
    </div>
  )
}
