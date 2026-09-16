export function displayValue(value) {
  return value === null || value === undefined || value === '' ? '--' : value
}

export function personLabel(value) {
  return displayValue(value)
}

/** Stable state labels used by event pages for loading/error/empty handling. */
export function eventViewState({ loading = false, error = '', items = [] } = {}) {
  if (loading) return 'loading'
  if (error) return 'error'
  return Array.isArray(items) && items.length ? 'ready' : 'empty'
}

export function commandStatusLabel(status) {
  return {
    pending: '待发送',
    claimed: '已领取，等待发送',
    sent: '已发送，等待设备回执',
    acknowledged: '已确认',
    failed: '下发失败',
    expired: '已过期',
  }[status] || displayValue(status)
}

export function commandExecutionLabel(command) {
  return command?.status === 'acknowledged' && command?.executed === true
    ? '设备已执行'
    : '尚未执行'
}

export function commandIntervalBounds(commandType) {
  return commandType === 'health_frequency'
    ? { min: 2, max: 255 }
    : { min: 1, max: 1440 }
}

export function isCommandIntervalValid(value, commandType) {
  const number = Number(value)
  const { min, max } = commandIntervalBounds(commandType)
  return Number.isInteger(number) && number >= min && number <= max
}

export function isMissingHealthError(error) {
  return Number(error?.status) === 404 && /no health records found/i.test(String(error?.message || ''))
}

/**
 * Return whether a device has reported recently.
 *
 * The preferred API accepts a device response object and reads its
 * `last_seen_at` field.  The timestamp form is retained for the existing
 * shell callers while they migrate to the object form.
 */
export function isOnline(deviceOrLastSeenAt, now = Date.now(), timeoutSeconds = 180) {
  const isLegacyTimestamp = typeof deviceOrLastSeenAt === 'string'
    || typeof deviceOrLastSeenAt === 'number'
    || deviceOrLastSeenAt instanceof Date
  const lastSeenAt = isLegacyTimestamp
    ? deviceOrLastSeenAt
    : deviceOrLastSeenAt?.last_seen_at

  if (lastSeenAt === null || lastSeenAt === undefined || lastSeenAt === '') return null

  const timestamp = lastSeenAt instanceof Date
    ? lastSeenAt.getTime()
    : new Date(lastSeenAt).getTime()
  const nowTimestamp = now instanceof Date ? now.getTime() : new Date(now).getTime()
  if (!Number.isFinite(timestamp) || !Number.isFinite(nowTimestamp)) return null

  // A malformed/negative timeout should not make a device appear offline by
  // accident.  Keep the documented three-minute default in that case.
  const timeout = Number(timeoutSeconds)
  const timeoutMs = Number.isFinite(timeout) && timeout >= 0 ? timeout * 1000 : 180 * 1000
  return nowTimestamp - timestamp <= timeoutMs
}

/** Convert actual history rows into SVG polyline coordinates. Missing values are skipped. */
export function trendPoints(rows, field, width = 150, height = 30) {
  const values = (Array.isArray(rows) ? rows : [])
    .filter((row) => row?.[field] !== null && row?.[field] !== undefined && row?.[field] !== '')
    .map((row) => Number(row?.[field]))
    .filter((value) => Number.isFinite(value))
  if (!values.length) return ''
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  return values.map((value, index) => {
    // A single real sample is deliberately represented by one point at the
    // left edge.  The default chart height places it at y=10, matching the
    // baseline contract while avoiding any synthetic second point.
    const x = values.length === 1 ? 0 : (index / (values.length - 1)) * width
    const y = values.length === 1 ? height / 3 : height - ((value - min) / span) * (height - 2) - 1
    return `${Number(x.toFixed(2))},${Number(y.toFixed(2))}`
  }).join(' ')
}
