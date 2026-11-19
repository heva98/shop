import { Component, lazy, Suspense, useEffect, useState } from 'react'
import { BRAND_NAME, NAV_DEFS, ROLE_LABEL, roleLabels } from './appData.js'
import { HeaderBar, MobileHeader, MobileMenu, MobileTabBar, NoticeBox, Sidebar } from './components/ds/index.js'
import { useAuth } from './auth/AuthContext.jsx'
import { useOutbox, useOutboxSync } from './hooks/useOutbox.js'
// Only signing in is in the first download, so the first page opens fast
// on a slow connection. The dashboard and till start downloading as soon as
// someone is signed in (see the effect in App); every other screen loads
// when first opened. The service worker keeps them all for offline use
// (public/sw.js).
import Login from './screens/Login.jsx'
import ChangePassword from './screens/ChangePassword.jsx'
import { t, useT } from './i18n/index.js'

const loadDashboard = () => import('./screens/Dashboard.jsx')
const loadPos = () => import('./screens/Pos.jsx')
const Dashboard = lazy(loadDashboard)
const Pos = lazy(loadPos)
const Stock = lazy(() => import('./screens/Stock.jsx'))
const Receiving = lazy(() => import('./screens/Receiving.jsx'))
const Enquiries = lazy(() => import('./screens/Enquiries.jsx'))
const Customers = lazy(() => import('./screens/Customers.jsx'))
const Analytics = lazy(() => import('./screens/Analytics.jsx'))
const Reports = lazy(() => import('./screens/Reports.jsx'))
const Settings = lazy(() => import('./screens/Settings.jsx'))
const Admin = lazy(() => import('./screens/Admin.jsx'))
const MyProfile = lazy(() => import('./screens/MyProfile.jsx'))
const PlatformShops = lazy(() => import('./screens/PlatformShops.jsx'))

/** A screen whose code could not be downloaded (no connection before the
 * service worker saved it): say so instead of a blank page. Rendered with
 * key={screen}, so choosing another screen starts afresh and tries again. */
class ScreenLoadBoundary extends Component {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  render() {
    return this.state.failed ? <NoticeBox variant="warning">{t('No connection to the server.')}</NoticeBox> : this.props.children
  }
}

const ADMIN_NAV = [
  { key: 'profile', label: 'Shop profile' }, { key: 'stores', label: 'Stores' }, { key: 'users', label: 'Users & roles' },
  { key: 'activity', label: 'Activity log' },
]
// A superuser with no shop of their own runs the server for every shop:
// they get the Shops console (core/platform.py), not a shop's screens.
const PLATFORM_NAV = [{ id: 'shops', label: 'Shops', icon: 'admin', section: 'System' }]
// Phone bottom tabs: the first three of these the role can see, then "More".
const MOBILE_TABS = ['dashboard', 'pos', 'analytics', 'reports', 'stock']
// "Owner · Cashier": every role held, most senior first.
const rolesLabel = (roles, labels = ROLE_LABEL) => Object.keys(labels).reverse().filter((r) => roles.includes(r)).map((r) => t(labels[r])).join(' · ')

export default function App() {
  const auth = useAuth()
  useT()
  const [state, setStateRaw] = useState({ screen: 'dashboard', sidebarCollapsed: false, adminTab: 'profile', profileReturnTo: null, menuOpen: false })
  const [isOnline, setIsOnline] = useState(navigator.onLine)
  const outbox = useOutbox()
  useOutboxSync(auth.status === 'signed-in' ? auth.profile?.id : null)

  useEffect(() => {
    const goOnline = () => setIsOnline(true)
    const goOffline = () => setIsOnline(false)
    window.addEventListener('online', goOnline)
    window.addEventListener('offline', goOffline)
    return () => {
      window.removeEventListener('online', goOnline)
      window.removeEventListener('offline', goOffline)
    }
  }, [])

  const signedIn = auth.status === 'signed-in'
  useEffect(() => {
    if (signedIn) { loadDashboard().catch(() => {}); loadPos().catch(() => {}) }
  }, [signedIn])

  if (auth.status === 'loading') return null
  if (auth.status === 'signed-out') return <Login />
  if (auth.profile?.must_change_password) return <ChangePassword />

  function setState(update) {
    setStateRaw((prev) => {
      const partial = typeof update === 'function' ? update(prev) : update
      return { ...prev, ...partial }
    })
  }

  // Roles: every one the signed-in user holds at the active workplace.
  const workplace = auth.activeWorkplace
  const roles = workplace?.roles ?? ['entity_admin']
  const features = workplace?.features ?? {}
  const isPlatform = Boolean(auth.profile?.is_superuser && !auth.entity)
  const navItems = (isPlatform
    ? PLATFORM_NAV
    : NAV_DEFS.filter((n) => n.roles.some((r) => roles.includes(r)) && (!n.feature || features[n.feature] !== false)))
    .map((n) => ({ id: n.id, label: t(n.label), icon: n.icon, section: t(n.section) }))
  // `params`: what to open on arrival, e.g. { viz } for Analytics.
  // Admin's sub-tab lives in App's state; other screens read screenParams.
  const goTo = (screen, params = null) => {
    if (!navItems.some((n) => n.id === screen)) return
    setState(screen === 'admin' && params?.tab ? { screen, screenParams: null, adminTab: params.tab } : { screen, screenParams: params })
  }
  // A screen hidden by switching store (or a feature) falls back to the dashboard.
  const screen = state.screen === 'profile' || navItems.some((n) => n.id === state.screen) ? state.screen : navItems[0].id
  const storeId = workplace?.store ?? null
  const storeName = workplace?.store_name ?? null
  const labels = roleLabels(auth.entity)
  const roleLabel = workplace ? rolesLabel(workplace.roles, labels) : null
  const storeLabel = isPlatform ? t('System administration') : workplace
    ? (workplace.store_name ?? `${t('All stores')} — ${auth.entity?.name ?? ''}`)
    : (auth.entity?.name ?? '')
  const workplaceOptions = auth.workplaces.map((w) => ({
    label: `${w.store_name ?? t('All stores')} — ${rolesLabel(w.roles, labels)}`, value: w.key, entity: !w.store,
  }))
  const profile = auth.profile
  const fullName = [profile?.first_name, profile?.last_name].filter(Boolean).join(' ')
  const avatarInitials = fullName
    ? fullName.split(' ').map((part) => part[0]).join('').toUpperCase()
    : (profile?.username?.slice(0, 2).toUpperCase() || '··')
  const openProfile = () => setState((s) => ({ screen: 'profile', profileReturnTo: s.screen === 'profile' ? s.profileReturnTo : s.screen }))
  const closeProfile = () => setState((s) => ({ screen: s.profileReturnTo || 'dashboard' }))
  // Sales on this till still to be sent, whoever rang them up (refused
  // ones are shown on the till instead).
  const unsyncedSales = outbox.filter((r) => r.status === 'pending').length
  const logout = () => {
    const mine = outbox.filter((r) => r.userId === profile?.id).length
    const warnings = [
      !isOnline && t('You are offline: you will not be able to sign in again until the connection returns.'),
      mine > 0 && t('{n} of your sales are still saved only on this till. They will be sent the next time you sign in here.', { n: mine }),
    ].filter(Boolean)
    if (warnings.length && !window.confirm(`${warnings.join('\n\n')}\n\n${t('Log out anyway?')}`)) return
    auth.logout()
  }
  const mobileTabs = MOBILE_TABS.map((id) => navItems.find((n) => n.id === id)).filter(Boolean).slice(0, 3)
  const openMenu = () => setState({ menuOpen: true })
  const closeMenu = () => setState({ menuOpen: false })
  const adminNav = ADMIN_NAV.map((n) => ({ ...n, label: t(n.label), active: state.adminTab === n.key, select: () => setState({ adminTab: n.key }) }))

  return (
    <div className="app-shell">
      <Sidebar
        items={navItems}
        active={screen}
        onSelect={goTo}
        collapsed={state.sidebarCollapsed}
        onToggle={() => setState((st) => ({ sidebarCollapsed: !st.sidebarCollapsed }))}
        logoUrl={auth.entity?.logo}
        brandName={BRAND_NAME}
      />
      <div className="app-column">
        <MobileHeader
          logoUrl={auth.entity?.logo}
          brandName={BRAND_NAME}
          storeLabel={storeLabel}
          isOnline={isOnline}
          unsyncedSales={unsyncedSales}
          avatarInitials={avatarInitials}
          onOpenMenu={openMenu}
        />
        <HeaderBar
          storeLabel={storeLabel}
          roleLabel={roleLabel}
          stores={workplaceOptions}
          activeStore={workplace?.key}
          onStoreChange={auth.setActiveWorkplaceKey}
          isOnline={isOnline}
          unsyncedSales={unsyncedSales}
          avatarInitials={avatarInitials}
          menuHeader={(
            <>
              <div style={{ fontWeight: 600, fontSize: 14 }}>{fullName || profile?.username}</div>
              <div style={{ fontSize: 12, color: 'var(--muted)' }}>{profile?.username}</div>
            </>
          )}
          menuItems={[
            { label: t('Edit my details'), icon: 'user', onClick: openProfile },
            'divider',
            { label: t('Log out'), icon: 'log-out', onClick: logout, destructive: true },
          ]}
        />

        <main className="app-main">
          <div className="app-main-inner">
            <ScreenLoadBoundary key={screen}>
            <Suspense fallback={<NoticeBox variant="info">{t('Loading…')}</NoticeBox>}>
            {screen === 'dashboard' && <Dashboard storeId={storeId} storeName={storeName} goTo={goTo} canGo={(id) => navItems.some((n) => n.id === id)} roles={roles} entity={auth.entity} />}
            {screen === 'pos' && <Pos storeId={storeId} userId={profile?.id} roles={roles} entity={auth.entity} features={features} goTo={goTo} canGo={(id) => navItems.some((n) => n.id === id)} />}
            {screen === 'stock' && <Stock storeId={storeId} storeName={storeName} roles={roles} goTo={goTo} canGo={(id) => navItems.some((n) => n.id === id)} />}
            {screen === 'receiving' && <Receiving storeId={storeId} roles={roles} />}
            {screen === 'enquiries' && <Enquiries storeId={storeId} entity={auth.entity} roles={roles} />}
            {screen === 'customers' && <Customers storeId={storeId} storeName={storeName} roles={roles} features={features} />}
            {screen === 'analytics' && <Analytics storeId={storeId} storeName={storeName} openVizId={state.screenParams?.viz ?? null} />}
            {screen === 'reports' && <Reports roles={roles} storeId={storeId} storeName={storeName} entity={auth.entity} features={features} />}
            {screen === 'settings' && <Settings key={state.screenParams?.tab ?? 'settings'} entity={auth.entity} initialTab={state.screenParams?.tab} />}
            {screen === 'admin' && <Admin nav={adminNav} tab={state.adminTab} />}
            {screen === 'shops' && <PlatformShops />}
            {screen === 'profile' && <MyProfile onDone={closeProfile} />}
            </Suspense>
            </ScreenLoadBoundary>
          </div>
        </main>
        <MobileTabBar tabs={mobileTabs} active={screen} onSelect={goTo} onMore={openMenu} />
      </div>
      {state.menuOpen && (
        <MobileMenu
          logoUrl={auth.entity?.logo}
          brandName={BRAND_NAME}
          avatarInitials={avatarInitials}
          userName={fullName || profile?.username}
          userRole={roleLabel}
          stores={workplaceOptions}
          activeStore={workplace?.key}
          onStoreChange={auth.setActiveWorkplaceKey}
          items={navItems}
          active={screen}
          onSelect={goTo}
          accountItems={[
            { label: t('Edit my details'), icon: 'user', onClick: openProfile },
            { label: t('Log out'), icon: 'log-out', onClick: logout },
          ]}
          onClose={closeMenu}
        />
      )}
    </div>
  )
}

