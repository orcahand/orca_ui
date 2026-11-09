// The one place the guide turns a media path into an address. Published media
// is read from the public bucket that storedMedia.json names; anything the
// catalog doesn't list (unpublished media, JSON, SVG) loads from the app itself.
import stored from './storedMedia.json'

const BUCKET_URL = `https://firebasestorage.googleapis.com/v0/b/${stored.bucket}/o/`
const STORED: Record<string, { object: string }> = stored.files
const GUIDE_ROOT = /^\.?\/?assembly\//

export function mediaUrl(path: string): string
export function mediaUrl(path: string | undefined): string | undefined
export function mediaUrl(path: string | undefined) {
  if (!path) return path
  const entry = STORED[path.replace(GUIDE_ROOT, '')]
  return entry ? `${BUCKET_URL}${encodeURIComponent(entry.object)}?alt=media` : path
}

// Props for an <img>: data-media keeps the guide path, which the stylesheets match on.
export const mediaImage = (path: string | undefined) => ({
  src: mediaUrl(path),
  'data-media': path,
})

// A download link's `download` attribute is ignored for files on another site, so fetch and save.
export async function downloadMedia(path: string) {
  const url = mediaUrl(path)
  try {
    const response = await fetch(url)
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const saved = URL.createObjectURL(await response.blob())
    const link = document.createElement('a')
    link.href = saved
    link.download = path.split('/').pop() ?? 'download'
    link.click()
    setTimeout(() => URL.revokeObjectURL(saved), 1000)
  } catch {
    window.open(url, '_blank', 'noopener')
  }
}
