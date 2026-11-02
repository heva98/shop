import { useState } from 'react'
import { Button, Checkbox, Field, Input, Modal, Select } from '../../../components/ds/index.js'
import { isChart } from '../visualizationConfig.js'
import { t, useT } from '../../../i18n/index.js'

export default function OptionsModal({ type, options, onApply, onClose }) {
  useT()
  const [draft, setDraft] = useState(options)
  // The target input is kept as typed and parsed on Apply.
  const [target, setTarget] = useState(options.targetValue ?? '')
  const set = (key, value) => setDraft((d) => ({ ...d, [key]: value }))
  const toggle = (key) => () => set(key, !draft[key])

  const chart = isChart(type)
  const hasTarget = chart && type !== 'PIE'
  const targetNumber = String(target).trim() === '' ? null : Number(target)
  const targetInvalid = targetNumber !== null && !Number.isFinite(targetNumber)

  const footer = (
    <>
      <Button onClick={onClose}>{t('Cancel')}</Button>
      <Button variant="primary" disabled={targetInvalid}
        onClick={() => onApply(hasTarget ? { ...draft, targetValue: targetNumber } : draft)}>
        {t('Apply')}
      </Button>
    </>
  )

  return (
    <Modal title={t('Options')} onClose={onClose} size="sm" footer={footer}>
      <div className="viz-options">
        <fieldset>
          <legend className="viz-overline">{t('Display')}</legend>
          {!chart && <Checkbox checked={draft.showDimensionLabels} onChange={toggle('showDimensionLabels')} label={t('Show dimension labels')} />}
          {chart && type !== 'SINGLE_VALUE' && <Checkbox checked={draft.showDataLabels} onChange={toggle('showDataLabels')} label={t('Show values on the chart')} />}
          {type !== 'SINGLE_VALUE' && (
            <>
              <Checkbox checked={draft.hideEmptyRows} onChange={toggle('hideEmptyRows')} label={chart ? t('Hide empty categories') : t('Hide empty rows')} />
              <Checkbox checked={draft.hideEmptyColumns} onChange={toggle('hideEmptyColumns')} label={chart ? t('Hide empty series') : t('Hide empty columns')} />
            </>
          )}
        </fieldset>

        {!chart && (
          <fieldset>
            <legend className="viz-overline">{t('Totals')}</legend>
            <Checkbox checked={draft.columnTotals} onChange={toggle('columnTotals')} label={t('Total row (adds up the rows)')} />
            <Checkbox checked={draft.rowTotals} onChange={toggle('rowTotals')} label={t('Total column (adds up the columns)')} />
            <p className="viz-help" style={{ marginTop: 4 }}>
              {t('Totals are worked out from the underlying sales, so averages and margins are right, and Data items are never added together.')}
            </p>
          </fieldset>
        )}

        <div className="viz-row2" style={{ marginBottom: 0 }}>
          <Field label={t('Decimal places')}>
            <Select value={String(draft.decimals)} onChange={(e) => set('decimals', e.target.value === 'auto' ? 'auto' : Number(e.target.value))}
              options={[{ value: 'auto', label: t('Automatic') }, '0', '1', '2']} />
          </Field>
          {chart && type !== 'SINGLE_VALUE' && (
            <Field label={t('Sort order')}>
              <Select value={draft.sortOrder} onChange={(e) => set('sortOrder', e.target.value)}
                options={[{ value: 'none', label: t('As selected') }, { value: 'asc', label: t('Low to high') }, { value: 'desc', label: t('High to low') }]} />
            </Field>
          )}
        </div>

        {hasTarget && (
          <fieldset>
            <legend className="viz-overline">{t('Target')}</legend>
            <div style={{ display: 'grid', gridTemplateColumns: '8rem 1fr', gap: 8 }}>
              <Input type="number" value={target} placeholder={t('e.g. 500000')} onChange={(e) => setTarget(e.target.value)} />
              <Input value={draft.targetLabel} placeholder={t('Target')} onChange={(e) => set('targetLabel', e.target.value.slice(0, 40))} />
            </div>
            <p className="viz-help" style={{ marginTop: 4 }}>
              {type === 'SINGLE_VALUE'
                ? t('Shows how far the value is above or below this number.')
                : t('Draws a dashed line at this value, e.g. a daily sales target. Leave empty for none.')}
            </p>
            {targetInvalid && <p className="ds-help error">{t('Enter a number.')}</p>}
          </fieldset>
        )}
      </div>
    </Modal>
  )
}
