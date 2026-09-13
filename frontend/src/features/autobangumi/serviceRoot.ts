/**
 * Normalize and validate the request-scoped Auto Bangumi service root.
 *
 * The server intentionally requires an explicit HTTP(S) scheme.  The UI may
 * accept the convenient LAN form `host:port`, but it must turn it into an
 * explicit origin before any generated request body is built.
 */
export const AUTO_BANGUMI_SERVICE_ROOT_HELP =
  '可填写 http(s)://主机:端口，或局域网主机:端口；只能填写服务根地址。'

const HTTP_PROTOCOLS = new Set(['http:', 'https:'])
const NON_HTTP_SCHEMES = new Set([
  'about', 'blob', 'chrome', 'content', 'data', 'file', 'ftp', 'gopher', 'imap',
  'javascript', 'ldap', 'mailto', 'ms-appx', 'ms-appx-web', 'rtsp', 'sftp',
  'smtp', 'ssh', 'tel', 'urn', 'vbscript', 'ws', 'wss',
])

export interface ServiceRootValidation {
  value: string | null
  message: string | null
}

function invalid(): ServiceRootValidation {
  return { value: null, message: '请填写合法的 Auto Bangumi 服务根地址（支持 http(s)://主机:端口 或局域网主机:端口）。' }
}

/** Return a scheme-qualified origin, or null for an ambiguous/unsafe value. */
export function normalizeAutoBangumiServiceRoot(input: string): string | null {
  if (/[\u0000-\u001f\u007f]/.test(input)) return null
  const raw = input.trim()
  if (!raw || /[\s\u0000-\u001f\u007f]/.test(raw)) return null

  const schemeWithAuthority = raw.match(/^([a-z][a-z\d+.-]*):\/\//i)
  const schemePrefix = raw.match(/^([a-z][a-z\d+.-]*):/i)
  const scheme = (schemeWithAuthority?.[1] ?? schemePrefix?.[1])?.toLowerCase()
  // A scheme-qualified value must use the unambiguous `scheme://authority`
  // spelling.  Bare `host:port` remains valid, but known non-HTTP schemes
  // must not be reinterpreted as a hostname merely because their suffix is
  // numeric (for example, `javascript:7892`).
  if (schemeWithAuthority && (!scheme || !HTTP_PROTOCOLS.has(`${scheme}:`))) return null
  if (schemePrefix && !schemeWithAuthority
    && (scheme === 'http' || scheme === 'https' || (scheme && NON_HTTP_SCHEMES.has(scheme)))) return null
  const authorityPrefixLength = schemeWithAuthority?.[0].length ?? 0
  const authorityAndTail = raw.slice(authorityPrefixLength)
  const pathStart = authorityAndTail.search(/[/?#]/)
  const authority = pathStart === -1 ? authorityAndTail : authorityAndTail.slice(0, pathStart)
  const tail = pathStart === -1 ? '' : authorityAndTail.slice(pathStart)
  // URL parsing normalizes dot segments and backslashes.  Validate the raw
  // spelling first so only an absent path or exactly one root slash survives.
  if (!authority || (tail !== '' && tail !== '/') || raw.includes('\\')) return null
  const candidate = schemeWithAuthority ? raw : `http://${raw}`
  let parsed: URL
  try {
    parsed = new URL(candidate)
  } catch {
    return null
  }
  if (!HTTP_PROTOCOLS.has(parsed.protocol.toLowerCase())) return null
  if (parsed.username || parsed.password || raw.includes('@')) return null
  if (raw.includes('?') || raw.includes('#')) return null
  if (!parsed.hostname || parsed.hostname === '.') return null
  const hostname = parsed.hostname.toLowerCase()
  if (hostname.startsWith('[')) {
    if (!hostname.endsWith(']')) return null
  } else if (!/^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$/i.test(hostname)
    || hostname.split('.').some((label) => !label || label.startsWith('-') || label.endsWith('-'))) {
    return null
  }
  if (parsed.pathname !== '/') return null

  // URL accepts port 0 and normalizes some spellings.  Require an explicit
  // decimal port, when present, to be within the TCP range.
  const portMarker = authority.lastIndexOf(':')
  const bracketed = authority.startsWith('[')
  const explicitPort = bracketed
    ? authority.slice(authority.indexOf(']') + 1)
    : (portMarker > -1 && authority.slice(0, portMarker).indexOf(':') === -1 ? authority.slice(portMarker) : '')
  if (explicitPort) {
    if (!/^:\d+$/.test(explicitPort)) return null
    const port = Number(explicitPort.slice(1))
    if (!Number.isInteger(port) || port < 1 || port > 65535) return null
  }
  return parsed.origin
}

export function validateAutoBangumiServiceRoot(input: string): ServiceRootValidation {
  const value = normalizeAutoBangumiServiceRoot(input)
  if (!input.trim()) return { value: null, message: '请填写服务地址。' }
  return value ? { value, message: null } : invalid()
}
