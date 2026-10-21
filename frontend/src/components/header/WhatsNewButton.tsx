// Opens the changelog from the top-right corner. Carries a dot while this
// release's notes have not been ticked away.

import { useChangelogStore, hasUnseenChangelog } from '../../state/changelogStore'

export function WhatsNewButton() {
  const open = useChangelogStore((s) => s.open)
  const version = useChangelogStore((s) => s.doc?.latest_version)
  const unseen = useChangelogStore(hasUnseenChangelog)

  const title = version ? `What's new in UI ${version}` : 'Release notes'

  return (
    <button
      type="button"
      className={`changelog-btn${unseen ? ' unseen' : ''}`}
      onClick={open}
      title={title}
      aria-label={title}
    >
      Changelog
    </button>
  )
}
