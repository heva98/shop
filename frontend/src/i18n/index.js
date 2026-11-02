// Interface language (English / Kiswahili). Strings are written in English
// in the code and looked up in the Swahili dictionary (sw.js); anything
// missing from it falls back to the English. `{name}` placeholders are
// filled from `vars`: t('Sent {n} sales', { n: 3 }).
//
// Components call useT() so they re-render when the language changes
// (without remounting: a sale in progress keeps its cart). Plain helpers
// called while rendering can use the module-level t() directly.

import { useSyncExternalStore } from 'react'
import sw from './sw.js'

export const LANGUAGES = [
  { code: 'en', label: 'English', short: 'EN' },
  { code: 'sw', label: 'Kiswahili', short: 'SW' },
]

const DICTIONARIES = { sw }
const STORAGE_KEY = 'shop.language'

function initialLanguage() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (LANGUAGES.some((l) => l.code === saved)) return saved
  } catch { /* storage blocked: use the default */ }
  // Nothing chosen yet: follow the browser, so a Swahili phone opens in Swahili.
  return navigator.language?.toLowerCase().startsWith('sw') ? 'sw' : 'en'
}

let current = initialLanguage()
const listeners = new Set()
document.documentElement.lang = current

export function getLanguage() {
  return current
}

/** True once the user has picked a language on this device. */
export function hasChosenLanguage() {
  try { return localStorage.getItem(STORAGE_KEY) !== null } catch { return false }
}

export function setLanguage(code) {
  if (code === current || !LANGUAGES.some((l) => l.code === code)) return
  current = code
  document.documentElement.lang = code
  try { localStorage.setItem(STORAGE_KEY, code) } catch { /* not remembered */ }
  listeners.forEach((fn) => fn())
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
