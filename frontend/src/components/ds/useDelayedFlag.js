import { useEffect, useState } from 'react'

/** `flag`, but only turns true after it has stayed true for `delay` ms.
 * Loading indicators use it so a response that arrives quickly (most of
 * them, on a good connection) doesn't flash a skeleton for one frame. */
export function useDelayedFlag(flag, delay = 200) {
  const [ready, setReady] = useState(false)
  useEffect(() => {
    if (!flag || delay <= 0) return undefined
    const timer = setTimeout(() => setReady(true), delay)
    return () => { clearTimeout(timer); setReady(false) }
  }, [flag, delay])
  return flag && (delay <= 0 || ready)
}
