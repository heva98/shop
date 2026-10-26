import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { getToken, isTransient, setRememberSession, setToken as persistToken } from '../api/client.js'
import { login as apiLogin, me as apiMe, updateMe as apiUpdateMe } from '../api/core.js'

const AuthContext = createContext(null)
const PROFILE_KEY = 'duka_erp_profile'

// The last /me payload, so a reload with no connection still signs in.
// Kept beside the token and removed with it.
function savedProfile() {
  try {
    const raw = localStorage.getItem(PROFILE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function saveProfile(data) {
  try {
    if (data) localStorage.setItem(PROFILE_KEY, JSON.stringify(data))
    else localStorage.removeItem(PROFILE_KEY)
  } catch { /* storage full or blocked: offline sign-in just won't be available */ }
}

export function AuthProvider({ children }) {
  const [token, setToken] = useState(getToken())
  const [profile, setProfile] = useState(null)
  const [activeStoreRoleId, setActiveStoreRoleId] = useState(null)
  const [status, setStatus] = useState(token ? 'loading' : 'signed-out')
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState('')

  const loadProfile = useCallback(async () => {
    setStatus('loading')
    const applyProfile = (data) => {
      setProfile(data)
      setActiveStoreRoleId((prev) => {
        if (prev && data.store_roles.some((sr) => sr.id === prev)) return prev
        return data.store_roles[0]?.id ?? null
      })
      setStatus('signed-in')
    }
    try {
      const data = await apiMe()
      saveProfile(data)
      applyProfile(data)
    } catch (err) {
      // No connection is not a rejected session: the till keeps working
      // offline on the profile saved at the last sign-in.
      const saved = isTransient(err) && err.status !== 401 ? savedProfile() : null
      if (saved) {
        applyProfile(saved)
        return
      }
      persistToken(null)
      saveProfile(null)
      setToken(null)
      setProfile(null)
      setStatus('signed-out')
      setError(err)
    }
  }, [])

  useEffect(() => {
    if (token) loadProfile()
  }, [token, loadProfile])

  useEffect(() => {
    const expired = () => {
      saveProfile(null)
      setToken(null)
      setProfile(null)
      setStatus('signed-out')
      setNotice('Your session has ended. Please sign in again.')
    }
    window.addEventListener('auth:expired', expired)
    return () => window.removeEventListener('auth:expired', expired)
  }, [])

  const login = useCallback(async (username, password, remember = true) => {
    setError(null)
    setNotice('')
    setRememberSession(remember)
    const newToken = await apiLogin(username, password)
    setToken(newToken)
  }, [])

  const logout = useCallback(() => {
    persistToken(null)
    saveProfile(null)
    setToken(null)
    setProfile(null)
    setStatus('signed-out')
  }, [])

  // Saves the signed-in user's own details; the response is the same
  // payload as GET /me, so it replaces the profile in place.
  const updateProfile = useCallback(async (data) => {
    const updated = await apiUpdateMe(data)
    saveProfile(updated)
    setProfile(updated)
    return updated
  }, [])

  const activeStoreRole = useMemo(
    () => profile?.store_roles.find((sr) => sr.id === activeStoreRoleId) ?? null,
    [profile, activeStoreRoleId],
  )

  const value = useMemo(() => ({
    status, error, notice, profile, token,
    entity: profile?.entity ?? null,
    storeRoles: profile?.store_roles ?? [],
    activeStoreRole,
    setActiveStoreRoleId,
    login, logout, updateProfile,
    // Re-pulls /me — call after an admin action that changes something
    // this context caches but doesn't own, e.g. the entity's own name/logo.
    refreshProfile: loadProfile,
  }), [status, error, notice, profile, token, activeStoreRole, login, logout, updateProfile, loadProfile])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider')
  return ctx
}
