/**
 * Maps the health views to real browser paths. The operations console keeps
 * its legacy hash navigation for shell-mounted event pages so existing
 * bookmarks such as `/#alarms` remain valid.
 */
const HEALTH_PATHS = new Set(['/health', '/health-detail'])

export function pageToPath(page) {
  return HEALTH_PATHS.has(`/${page}`) ? `/${page}` : '/'
}

export function pageFromRoute(pathname, hash = '') {
  if (HEALTH_PATHS.has(pathname)) return pathname.slice(1)
  const hashPage = String(hash).replace(/^#\/?/, '')
  return hashPage || 'monitor'
}

export function isHealthPath(pathname) {
  return HEALTH_PATHS.has(pathname)
}
