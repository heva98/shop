import Button from './Button.jsx'
import NoticeBox from './NoticeBox.jsx'
import Skeleton from './Skeleton.jsx'
import { useDelayedFlag } from './useDelayedFlag.js'
import { apiErrorText } from '../../lib/apiError.js'
import { t } from '../../i18n/index.js'

const defaultIsEmpty = (data) =>
  data == null || (Array.isArray(data) && data.length === 0) || (Array.isArray(data?.results) && data.results.length === 0)

/** Renders whichever of loading / error / empty / content applies to one
 * server call, so screens stop hand-writing the same four branches.
 * Takes useApi's result as-is:
 *
 *   const sales = useApi(() => listSales(), [])
 *   <AsyncContent state={sales} empty={<EmptyState title={t('No sales yet')} />}>
 *     {(rows) => <SalesList rows={rows} />}
 *   </AsyncContent>
 *
 * Order of precedence:
 *   1. data present            → children(data), even while a refetch runs
 *                                (kept on screen, marked aria-busy)
 *   2. error                   → error notice with a "Try again" button
 *   3. loading                 → `skeleton` (after `delay` ms, so fast replies don't flash)
 *   4. data empty              → `empty`
 *   5. nothing asked yet       → `idle` (useApi skipped the call)
 *
 * Props:
 *   state        {data, loading, error, refetch}
 *   children     (data) => node
 *   empty        node shown when isEmpty(data)
 *   isEmpty      (data) => bool; default: null, [] or {results: []}
 *   skeleton     node shown while loading; default: three text lines
 *   errorTitle   heading of the error notice; default "Could not load this."
 *   idle         node shown when there's nothing to load yet
 *   delay        ms before the skeleton appears (default 200; 0 = at once) */
export default function AsyncContent({
  state, children, empty = null, isEmpty = defaultIsEmpty, skeleton, errorTitle, idle = null, delay = 200,
}) {
  const { data, loading, error, refetch } = state
  const hasData = data != null
  const showSkeleton = useDelayedFlag(loading && !hasData, delay)

  if (hasData && !isEmpty(data)) {
    return (
      <div className="ds-async" aria-busy={loading || undefined} data-refreshing={loading || undefined}>
        {children(data)}
      </div>
    )
  }
  if (error && !loading) {
    return (
      <NoticeBox
        variant="error"
        title={errorTitle || t('Could not load this.')}
        action={refetch && <Button size="small" onClick={() => refetch()}>{t('Try again')}</Button>}
      >
        {/* NetworkError / ApiError messages are already translated by api/client.js. */}
        {apiErrorText(error, error?.message)}
      </NoticeBox>
    )
  }
  if (loading) {
    if (!showSkeleton) return <div className="ds-async" aria-busy="true" />
    return (
      <div className="ds-async" aria-busy="true">
        <span role="status" className="sr-only">{t('Loading…')}</span>
        {skeleton ?? <Skeleton.Text lines={3} />}
      </div>
    )
  }
  if (hasData) return empty
  return idle
}
