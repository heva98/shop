export default function Field({ label, required, children, style }) {
  return (
    <label style={{ display: 'block', ...style }}>
      {label && (
        <span className="ds-label">
          {label}
          {required && <span className="req" aria-hidden="true">*</span>}
        </span>
      )}
      {children}
    </label>
  )
}
