import { PageHeader, SubNav } from '../components/ds/index.js'
import AdminShopProfile from './AdminShopProfile.jsx'
import AdminStores from './AdminStores.jsx'
import AdminUsers from './AdminUsers.jsx'
import ActivityLog from './ActivityLog.jsx'

export default function Admin({ nav, tab }) {
  return (
    <div>
      <PageHeader title="Admin" subtitle="Shop profile, branches, users and the activity log." />
      <div className="ds-subnav-layout">
        <SubNav label="Admin sections" items={nav} />
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
