import { useState } from 'react'
import { apiErrorText } from '../lib/apiError.js'

/** The busy flag and error message every form and dialog keeps around one
 * server call:
 *
 *   const { busy, error, setError, run } = useAsyncAction()
 *   const save = () => run(() => saveThing(form), t('Could not save.'))
 *
 * `run(action, failure)` clears the error, sets busy while `action` runs,
 * and on failure shows `failure`: the fallback text for apiErrorText, or a
 * function from the error to the text to show. It resolves to true when
 * the action succeeded, false when it failed. */
export function useAsyncAction() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function run(action, failure) {
    setBusy(true); setError('')
    try {
      await action()
      return true
    } catch (err) {
      setError(typeof failure === 'function' ? failure(err) : apiErrorText(err, failure))
      return false
    } finally { setBusy(false) }
  }

  return { busy, error, setError, run }
}
