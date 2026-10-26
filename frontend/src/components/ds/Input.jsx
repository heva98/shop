import Icon from './Icon.jsx'

export default function Input({ value, onChange, placeholder, prefixIcon, type = 'text', disabled, style }) {
  return (
    <div style={{ position: 'relative', width: '100%', ...style }}>
      {prefixIcon && <span className="ds-input-icon"><Icon name={prefixIcon} size={18} /></span>}
      <input
        className={['ds-input', disabled ? 'disabled' : ''].filter(Boolean).join(' ')}
        type={type}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        disabled={!!disabled}
        style={prefixIcon ? { paddingLeft: 42 } : undefined}
      />
    </div>
  )
}
