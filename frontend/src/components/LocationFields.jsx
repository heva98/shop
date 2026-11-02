import { Field, Input, Select } from './ds/index.js'
import { useApi } from '../hooks/useApi.js'
import { listLocations } from '../api/core.js'
import { t, useLanguage, useT } from '../i18n/index.js'

export const TANZANIA = 'TZ'

/** A country's name in the app's language ("Tanzania" / "Tanzania"),
 * falling back to the server's English name. */
export function countryName(code, lang, fallback) {
  try {
    return new Intl.DisplayNames([lang], { type: 'region' }).of(code) || fallback || code
  } catch {
    return fallback || code
  }
}

/** Country, Region and Council. In Tanzania the region and council are
 * dropdowns, the councils being those of the chosen region; elsewhere they
 * are typed in. Changing the country or region clears what depends on it.
 * A Tanzanian value saved before the dropdowns existed is kept as an extra
 * option until it is changed. */
export default function LocationFields({ country, region, council, onChange }) {
  useT()
  const lang = useLanguage()
  const { data, loading } = useApi(() => listLocations(), [])
  const countries = (data?.countries ?? [])
    .map((c) => ({ value: c.code, label: countryName(c.code, lang, c.name) }))
    .sort((a, b) => (a.value === TANZANIA ? -1 : b.value === TANZANIA ? 1 : a.label.localeCompare(b.label, lang)))
  const regions = data?.regions ?? []
  const councils = regions.find((r) => r.region === region)?.councils ?? []
  const withCurrent = (names, current) => (current && !names.includes(current) ? [current, ...names] : names)
  const options = (placeholder, names) => [{ value: '', label: placeholder }, ...names.map((n) => ({ value: n, label: n }))]
  const inTanzania = country === TANZANIA

  return (
    <>
      <Field label={t('Country')}>
        <Select
          value={country}
          disabled={loading}
          onChange={(e) => onChange({ country: e.target.value, region: '', council: '' })}
          options={loading ? [{ value: country, label: t('Loading…') }] : countries}
        />
      </Field>
      {inTanzania ? (
        <>
          <Field label={t('Region')}>
            <Select
              value={region}
              disabled={loading}
              onChange={(e) => onChange({ country, region: e.target.value, council: '' })}
              options={options(loading ? t('Loading…') : t('Select region…'), withCurrent(regions.map((r) => r.region), region))}
            />
          </Field>
          <Field label={t('Council')}>
            <Select
              value={council}
              disabled={loading || !region}
              onChange={(e) => onChange({ country, region, council: e.target.value })}
              options={options(region ? t('Select council…') : t('Select a region first'), withCurrent(councils, council))}
            />
          </Field>
        </>
      ) : (
        <>
          <Field label={t('Region')}>
            <Input value={region} onChange={(e) => onChange({ country, region: e.target.value, council })} />
          </Field>
          <Field label={t('Council')}>
            <Input value={council} onChange={(e) => onChange({ country, region, council: e.target.value })} />
          </Field>
        </>
      )}
    </>
  )
}
