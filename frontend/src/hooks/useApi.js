import { useCallback, useEffect, useRef, useState } from 'react'

/** Calls `fn()` whenever `deps` change and exposes {data, loading, error, refetch}.
 * `fn` returning `null` (e.g. "no store selected yet") skips the call. */
export function useApi(fn, deps) {
  const [state, setState] = useState({ data: null, loading: true, error: null })
  const fnRef = useRef(fn)
  fnRef.current = fn

  const run = useCallback(() => {
    const result = fnRef.current()
    if (result === null) {
      setState({ data: null, loading: false, error: null })
      return
    }
    let cancelled = false
    setState((s) => ({ ...s, loading: true, error: null }))
    result
      .then((data) => { if (!cancelled) setState({ data, loading: false, error: null }) })
      .catch((error) => { if (!cancelled) setState({ data: null, loading: false, error }) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(() => run(), [run])

  return { ...state, refetch: run }
}
