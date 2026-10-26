/** White sub-nav card beside Settings and Admin content. */
export default function SubNav({ items, label }) {
  return (
    <nav className="ds-subnav" aria-label={label}>
      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          className="ds-subnav-item"
          aria-current={item.active ? 'page' : undefined}
          onClick={item.select}
        >
          {item.label}
        </button>
      ))}
    </nav>
  )
}
