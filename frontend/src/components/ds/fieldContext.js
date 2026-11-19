import { createContext, useContext } from 'react'

/** What a Field tells its control: {describedBy, invalid, required}.
 * Lives apart from Field.jsx so that file only exports a component. */
export const FieldContext = createContext(null)

/** The surrounding Field's context, or null outside a Field. Input and
 * Select read it; a custom control can too. */
export function useFieldContext() {
  return useContext(FieldContext)
}

/** Joins aria-describedby ids, dropping blanks. */
export function describedBy(...ids) {
  return ids.filter(Boolean).join(' ') || undefined
}
