// Shared constants: navigation/role matrix, labels, and money formatting.

export const BRAND_NAME = 'Shoppy'

export const NAV_DEFS = [
  { id: 'dashboard', label: 'Dashboard', icon: 'dashboard', section: 'General', roles: ['cashier', 'storekeeper', 'store_manager', 'entity_admin'] },
  { id: 'pos', label: 'Point of sale', icon: 'pos', section: 'Store', roles: ['cashier', 'storekeeper', 'store_manager'], feature: 'pos_sale' },
  { id: 'stock', label: 'Stock', icon: 'stock', section: 'Store', roles: ['cashier', 'storekeeper', 'store_manager'] },
  { id: 'receiving', label: 'Receiving', icon: 'receiving', section: 'Store', roles: ['storekeeper', 'store_manager'], feature: 'receiving_invoice' },
  { id: 'enquiries', label: 'Enquiries & transfers', icon: 'transfer', section: 'Store', roles: ['store_manager', 'entity_admin'], feature: 'transfer' },
  { id: 'customers', label: 'Customers & credit', icon: 'customers', section: 'Store', roles: ['cashier', 'storekeeper', 'store_manager', 'entity_admin'] },
  { id: 'analytics', label: 'Analytics', icon: 'analytics', section: 'Analytics', roles: ['store_manager', 'entity_admin'], feature: 'analytics_dashboards' },
  { id: 'reports', label: 'Reports', icon: 'reports', section: 'Analytics', roles: ['cashier', 'storekeeper', 'store_manager', 'entity_admin'] },
  { id: 'settings', label: 'Settings', icon: 'settings', section: 'Administration', roles: ['entity_admin'] },
  { id: 'admin', label: 'Admin', icon: 'admin', section: 'Administration', roles: ['entity_admin'] },
]

// NAV_DEFS `feature`: hidden when that feature is switched off for the
// active store (Settings > Features; core/features.py on the backend).

export const ROLE_LABEL = { cashier: 'Cashier', storekeeper: 'Storekeeper', store_manager: 'Store manager', entity_admin: 'Owner' }

// Mirror core.Entity.BusinessType on the backend.
export const BUSINESS_TYPE_OPTIONS = [
  { value: 'general', label: 'General shop (duka)' },
  { value: 'supermarket', label: 'Supermarket / minimarket' },
  { value: 'wholesale', label: 'Wholesale' },
  { value: 'hardware', label: 'Hardware' },
  { value: 'pharmacy', label: 'Pharmacy / chemist' },
  { value: 'electronics', label: 'Electronics & phones' },
  { value: 'clothing', label: 'Clothing & textiles' },
  { value: 'cosmetics', label: 'Cosmetics & beauty' },
  { value: 'stationery', label: 'Stationery & books' },
  { value: 'other', label: 'Other' },
]

// Mirror core.User.Gender / core.User.Qualification on the backend.
export const GENDER_OPTIONS = [{ value: '', label: 'Select…' }, { value: 'male', label: 'Male' }, { value: 'female', label: 'Female' }]
export const QUALIFICATION_OPTIONS = [
  { value: '', label: 'Select…' },
  { value: 'primary', label: 'Primary education' },
  { value: 'o_level', label: 'Secondary (O-level)' },
  { value: 'a_level', label: 'Advanced secondary (A-level)' },
  { value: 'certificate', label: 'Certificate' },
  { value: 'diploma', label: 'Diploma' },
  { value: 'bachelor', label: 'Bachelor’s degree' },
  { value: 'master', label: 'Master’s degree' },
  { value: 'doctorate', label: 'Doctorate (PhD)' },
]
export const QUALIFICATION_LABEL = Object.fromEntries(QUALIFICATION_OPTIONS.map((o) => [o.value, o.label]))

export function fmt(n) {
  // `|| 0` turns -0 (e.g. a zero-cost shortfall) and NaN into a plain 0.
  return 'TZS ' + (Math.round(n) || 0).toLocaleString('en-US')
}
