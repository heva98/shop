import { PageHeader, SubNav } from '../components/ds/index.js'
import AdminShopProfile from './AdminShopProfile.jsx'
import AdminStores from './AdminStores.jsx'
import AdminUsers from './AdminUsers.jsx'
import ActivityLog from './ActivityLog.jsx'
import { useT } from '../i18n/index.js'

export default function Admin({ nav, tab }) {
  const t = useT()
  return (
    <div>
      <PageHeader title={t('Admin')} subtitle={t('Shop profile, branches, users and the activity log.')} />
      <div className="ds-subnav-layout">
        <SubNav label={t('Admin sections')} items={nav} />
        <div className="ds-subnav-content">
          {tab === 'stores' && <AdminStores />}
          {tab === 'users' && <AdminUsers />}
          {tab === 'profile' && <AdminShopProfile />}
          {tab === 'activity' && <ActivityLog />}
        </div>
      </div>
    </div>
  )
}
