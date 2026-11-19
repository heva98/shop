/** Grey placeholder shaped like content that is still loading.
 *
 * Skeletons are decorative (aria-hidden): the container that holds them
 * should carry aria-busy and a "Loading…" status (AsyncContent and
 * DataTable do this for you). Shimmer stops under prefers-reduced-motion.
 *
 *   <Skeleton width={120} height={16} />
 *   <Skeleton.Text lines={3} />
 *   <Skeleton circle width={40} /> */
export default function Skeleton({ width = '100%', height = 14, circle, radius, className, style }) {
  return (
    <span
      className={['ds-skeleton', className].filter(Boolean).join(' ')}
      aria-hidden="true"
      style={{
        width,
        height: circle ? width : height,
        borderRadius: circle ? '50%' : radius ?? 6,
        ...style,
      }}
    />
  )
}

/** A paragraph of `lines` bars; the last one is shorter so it reads as text. */
function SkeletonText({ lines = 3, lineHeight = 14, gap = 10, style }) {
  return (
    <span className="ds-skeleton-text" aria-hidden="true" style={{ gap, ...style }}>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} height={lineHeight} width={i === lines - 1 && lines > 1 ? '60%' : '100%'} />
      ))}
    </span>
  )
}

Skeleton.Text = SkeletonText
