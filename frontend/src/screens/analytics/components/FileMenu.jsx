import { useState } from 'react'
import { Button, Icon, Menu, MenuDivider, MenuItem } from '../../../components/ds/index.js'
import { t, useT } from '../../../i18n/index.js'

/**
 * The top bar's File menu. `saved` is the open saved visualization (or null);
 * `onAction` receives 'new' | 'open' | 'save' | 'saveAs' | 'rename' | 'pin' |
 * 'delete'.
 */
export default function FileMenu({ saved, canSave, onAction }) {
  useT()
  const [open, setOpen] = useState(false)
  const owner = Boolean(saved?.is_owner)
  const pick = (action) => () => { setOpen(false); onAction(action) }

  return (
    <div className="viz-rel">
      <Button size="small" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <Icon name="folder" size={16} /> {t('File')}
      </Button>
      {open && (
        <>
          <div className="viz-scrim" onClick={() => setOpen(false)} />
          <div className="viz-popover">
            <Menu>
              <MenuItem label={t('New')} icon={<Icon name="add" size={16} />} onClick={pick('new')} />
              <MenuItem label={t('Open…')} icon={<Icon name="folder" size={16} />} onClick={pick('open')} />
              <MenuDivider />
              <MenuItem label={saved && !owner ? t('Save (only its creator can)') : t('Save')} icon={<Icon name="save" size={16} />}
                disabled={!canSave || (saved && !owner)} onClick={pick('save')} />
              <MenuItem label={t('Save as…')} disabled={!canSave} onClick={pick('saveAs')} />
              <MenuItem label={t('Rename…')} disabled={!owner} onClick={pick('rename')} />
              <MenuDivider />
              <MenuItem label={saved?.is_pinned ? t('Unpin from dashboard') : saved ? t('Pin to dashboard') : t('Pin to dashboard (save it first)')}
                icon={<Icon name={saved?.is_pinned ? 'pin-off' : 'pin'} size={16} />} disabled={!saved} onClick={pick('pin')} />
              <MenuDivider />
              <MenuItem label={t('Delete')} icon={<Icon name="delete" size={16} />} destructive disabled={!owner} onClick={pick('delete')} />
            </Menu>
          </div>
        </>
      )}
    </div>
  )
}
