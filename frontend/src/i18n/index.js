// Interface language (English / Kiswahili). Strings are written in English
// in the code and looked up in the Swahili dictionary (sw.js); anything
// missing from it falls back to the English. `{name}` placeholders are
// filled from `vars`: t('Sent {n} sales', { n: 3 }).
//
// Components call useT() so they re-render when the language changes
// (without remounting: a sale in progress keeps its cart). Plain helpers
// called while rendering can use the module-level t() directly.

import { useSyncExternalStore } from 'react'

export const LANGUAGES = [
  { code: 'en', label: 'English', short: 'EN' },
  { code: 'sw', label: 'Kiswahili', short: 'SW' },
]

// Dictionaries are downloaded only when their language is used (sw.js is
// ~110 KB, which English users should not pay for on first load). The
// service worker still saves the chunk, so switching works offline.
const LOADERS = { sw: () => import('./sw.js') }
const DICTIONARIES = {}
const STORAGE_KEY = 'shop.language'

function loadDictionary(code) {
  if (DICTIONARIES[code] || !LOADERS[code]) return Promise.resolve()
  return LOADERS[code]().then((m) => { DICTIONARIES[code] = m.default }, () => { /* offline and not saved: stays English */ })
}

function initialLanguage() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (LANGUAGES.some((l) => l.code === saved)) return saved
  } catch { /* storage blocked: use the default */ }
  // Nothing chosen yet: follow the browser, so a Swahili phone opens in Swahili.
  return navigator.language?.toLowerCase().startsWith('sw') ? 'sw' : 'en'
}

let current = initialLanguage()
let requested = current
const listeners = new Set()
document.documentElement.lang = current

/** Resolves once the starting language's dictionary is loaded; main.jsx
 * waits on it before the first render so a Swahili user never sees English
 * flash first. */
export const i18nReady = loadDictionary(current)

export function getLanguage() {
  return current
}

/** True once the user has picked a language on this device. */
export function hasChosenLanguage() {
  try { return localStorage.getItem(STORAGE_KEY) !== null } catch { return false }
}

export function setLanguage(code) {
  if (code === requested || !LANGUAGES.some((l) => l.code === code)) return
  requested = code
  try { localStorage.setItem(STORAGE_KEY, code) } catch { /* not remembered */ }
  loadDictionary(code).then(() => {
    if (requested !== code || current === code) return // switched again meanwhile
    current = code
    document.documentElement.lang = code
    listeners.forEach((fn) => fn())
  })
}

export function t(text, vars) {
  const out = DICTIONARIES[current]?.[text] ?? text
  if (!vars) return out
  return out.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m))
}

// Translates the labels of [{ value, label }] option lists.
export function tOptions(options) {
  return options.map((o) => ({ ...o, label: t(o.label) }))
}

// Locale for dates and times; undefined keeps the browser's own for English.
export function dateLocale() {
  return current === 'sw' ? 'sw-TZ' : undefined
}

export function subscribe(fn) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

/** Re-renders the caller when the language changes; returns t. */
export function useT() {
  useSyncExternalStore(subscribe, getLanguage)
  return t
}

export function useLanguage() {
  return useSyncExternalStore(subscribe, getLanguage)
}
