export default function Select({ value, onChange, options = [], style, ...rest }) {
  return (
    <select className="ds-input" value={value} onChange={onChange} style={style} {...rest}>
      {options.map((opt) => {
        const isObject = opt !== null && typeof opt === 'object'
        const optValue = isObject ? opt.value : opt
        const optLabel = isObject ? opt.label : opt
        return <option key={optValue} value={optValue}>{optLabel}</option>
      })}
    </select>
  )
}
