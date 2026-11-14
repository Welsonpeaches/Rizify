import { randomBytes } from 'node:crypto'
import { chmod, mkdir, readFile, rename, unlink, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { parse } from 'smol-toml'

export const RIZIFY_VERSION = '0.1.0'
export const DEFAULT_SIGN_API_URL = 'http://127.0.0.1:8080/'

const PASSWORD_FIELD = "password"
const ROOT_KEYS = new Set(['protocol', 'milky', 'logging', 'security', 'debug'])
const PROTOCOL_KEYS = new Set([
  'uin',
  'os',
  'version',
  'signApiUrl',
  'pcLagrangeSignToken',
  'androidUseLegacySign',
  'autoRenewSession',
])
const MILKY_KEYS = new Set([
  'http',
  'webhook',
  'reportSelfMessage',
  'preloadContacts',
  'ffmpegPath',
])
const HTTP_KEYS = new Set(['host', 'port', 'prefix', 'accessToken', 'corsOrigins'])
const WEBHOOK_KEYS = new Set(['endpoints'])
const ENDPOINT_KEYS = new Set(['url', 'accessToken'])
const LOGGING_KEYS = new Set(['ansiLevel', 'coreLogLevel'])
const SECURITY_KEYS = new Set(['skipOnLaunchListenAddressCheck'])
const DEBUG_KEYS = new Set(['enableFaceDetailsApi'])
const SUPPORTED_VERSIONS: Record<string, Set<string>> = {
  Linux: new Set(['53644', '46494', '39038', 'custom']),
  Mac: new Set(['52194', '52892', 'custom']),
  Windows: new Set(['custom']),
}
const ANSI_LEVELS = new Set(['NONE', 'ANSI16', 'ANSI256', 'TRUECOLOR'])
const LOG_LEVELS = new Set(['VERBOSE', 'DEBUG', 'INFO', 'WARN', 'ERROR'])

export class ConfigError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ConfigError'
  }
}

export interface RizifyConfig {
  protocol: {
    uin: number
    os: string
    version: string
    signApiUrl: string
    pcLagrangeSignToken: string
    androidUseLegacySign: boolean
    autoRenewSession: boolean
  }
  milky: {
    http: {
      host: string
      port: number
      prefix: string
      accessToken: string
      corsOrigins: string[]
    }
    webhook: {
      endpoints: Array<{
        url: string
        accessToken: string
      }>
    }
    reportSelfMessage: boolean
    preloadContacts: boolean
    ffmpegPath: string
  }
  logging: {
    ansiLevel: string
    coreLogLevel: string
  }
  security: {
    skipOnLaunchListenAddressCheck: boolean
  }
  debug: {
    enableFaceDetailsApi: boolean
  }
}

export interface YogurtConfigJson {
  configVersion: 3
  protocol: {
    uin: number
    os: string
    version: string
    signApiUrl: string
    pcLagrangeSignToken: string
    androidUseLegacySign: boolean
    autoRenewSession: boolean
    [key: string]: string | number | boolean
  }
  milky: RizifyConfig['milky']
  logging: RizifyConfig['logging']
  security: RizifyConfig['security']
  debug: RizifyConfig['debug']
}

type TomlTable = Record<string, unknown>

function isTable(value: unknown): value is TomlTable {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function expectTable(value: unknown, key: string): TomlTable {
  if (!isTable(value)) {
    throw new ConfigError(`${key} 必须是 TOML 表`)
  }
  return value
}

function optionalTable(value: unknown, key: string): TomlTable {
  if (value === undefined) {
    return {}
  }
  return expectTable(value, key)
}

function rejectUnknownKeys(table: TomlTable, allowed: Set<string>, key: string): void {
  const unknown = Object.keys(table).filter((name) => !allowed.has(name))
  if (unknown.length > 0) {
    throw new ConfigError(`${key} 包含未知字段: ${unknown.join(', ')}`)
  }
}

function stringValue(
  table: TomlTable,
  key: string,
  defaultValue: string | undefined,
  keyPath: string,
): string {
  const value = table[key]
  if (value === undefined) {
    if (defaultValue === undefined) {
      throw new ConfigError(`${keyPath} 未填写`)
    }
    return defaultValue
  }
  if (typeof value !== 'string') {
    throw new ConfigError(`${keyPath} 必须是字符串`)
  }
  return value
}

function booleanValue(
  table: TomlTable,
  key: string,
  defaultValue: boolean,
  keyPath: string,
): boolean {
  const value = table[key]
  if (value === undefined) {
    return defaultValue
  }
  if (typeof value !== 'boolean') {
    throw new ConfigError(`${keyPath} 必须是布尔值`)
  }
  return value
}

function integerValue(
  table: TomlTable,
  key: string,
  defaultValue: number | undefined,
  keyPath: string,
): number {
  const value = table[key]
  if (value === undefined) {
    if (defaultValue === undefined) {
      throw new ConfigError(`${keyPath} 未填写`)
    }
    return defaultValue
  }
  if (typeof value === 'bigint') {
    if (value < BigInt(Number.MIN_SAFE_INTEGER) || value > BigInt(Number.MAX_SAFE_INTEGER)) {
      throw new ConfigError(`${keyPath} 超出安全整数范围`)
    }
    return Number(value)
  }
  if (typeof value !== 'number' || !Number.isSafeInteger(value)) {
    throw new ConfigError(`${keyPath} 必须是整数`)
  }
  return value
}

function stringArrayValue(
  table: TomlTable,
  key: string,
  defaultValue: string[],
  keyPath: string,
): string[] {
  const value = table[key]
  if (value === undefined) {
    return defaultValue
  }
  if (!Array.isArray(value) || value.some((item) => typeof item !== 'string')) {
    throw new ConfigError(`${keyPath} 必须是字符串数组`)
  }
  return [...value]
}

function enumValue(
  table: TomlTable,
  key: string,
  defaultValue: string,
  allowed: Set<string>,
  keyPath: string,
): string {
  const value = stringValue(table, key, defaultValue, keyPath)
  if (!allowed.has(value)) {
    throw new ConfigError(`${keyPath} 必须是 ${[...allowed].join(', ')} 之一`)
  }
  return value
}

function normalizeSignApiUrl(raw: string): string {
  let url: URL
  try {
    url = new URL(raw)
  } catch {
    throw new ConfigError('protocol.signApiUrl 不是合法 URL')
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    throw new ConfigError('protocol.signApiUrl 必须使用 http 或 https')
  }
  if (url.username || url.password) {
    throw new ConfigError('protocol.signApiUrl 不能包含用户名或密码')
  }
  if (url.search || url.hash) {
    throw new ConfigError('protocol.signApiUrl 不能包含 query 或 fragment')
  }
  if (url.pathname !== '/' && url.pathname !== '') {
    throw new ConfigError(
      'protocol.signApiUrl 必须是根地址，例如 http://127.0.0.1:8080/；Yogurt 会自行追加 api/sign/sec-sign',
    )
  }
  url.pathname = '/'
  return url.toString()
}

function expandEnvironment(raw: string, keyPath: string): string {
  if (raw.trim().length === 0) {
    throw new ConfigError(`${keyPath} 不能为空`)
  }
  const expanded = raw.replace(
    /\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))/g,
    (_match, braced: string | undefined, bare: string | undefined) => {
      const name = braced ?? bare
      if (!name) {
        return _match
      }
      const value = process.env[name]
      if (value === undefined || value.length === 0) {
        throw new ConfigError(`${keyPath}: 环境变量 ${name} 未设置或为空`)
      }
      return value
    },
  )
  if (expanded.length === 0) {
    throw new ConfigError(`${keyPath} 不能为空`)
  }
  return expanded
}

function parseEndpoints(table: TomlTable): RizifyConfig['milky']['webhook']['endpoints'] {
  rejectUnknownKeys(table, WEBHOOK_KEYS, 'milky.webhook')
  const value = table.endpoints
  if (value === undefined) {
    return []
  }
  if (!Array.isArray(value)) {
    throw new ConfigError('milky.webhook.endpoints 必须是数组')
  }
  return value.map((entry, index) => {
    const endpoint = expectTable(entry, `milky.webhook.endpoints[${index}]`)
    rejectUnknownKeys(endpoint, ENDPOINT_KEYS, `milky.webhook.endpoints[${index}]`)
    const url = stringValue(
      endpoint,
      'url',
      undefined,
      `milky.webhook.endpoints[${index}].url`,
    )
    try {
      const parsed = new URL(url)
      if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
        throw new Error('unsupported protocol')
      }
    } catch {
      throw new ConfigError(`milky.webhook.endpoints[${index}].url 不是合法 HTTP URL`)
    }
    return {
      url,
      accessToken: stringValue(
        endpoint,
        'accessToken',
        '',
        `milky.webhook.endpoints[${index}].accessToken`,
      ),
    }
  })
}

export function parseRizifyToml(text: string, configPath: string): RizifyConfig {
  let parsed: unknown
  try {
    parsed = parse(text)
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    throw new ConfigError(`${configPath}: TOML 解析失败: ${message}`)
  }

  const root = expectTable(parsed, '配置根节点')
  rejectUnknownKeys(root, ROOT_KEYS, '配置根节点')

  const protocol = optionalTable(root.protocol, 'protocol')
  rejectUnknownKeys(protocol, PROTOCOL_KEYS, 'protocol')
  const uin = integerValue(protocol, 'uin', undefined, 'protocol.uin')
  if (uin <= 0) {
    throw new ConfigError('protocol.uin 必须是大于 0 的真实 QQ 号')
  }
  const os = stringValue(protocol, 'os', 'Linux', 'protocol.os')
  if (!(os in SUPPORTED_VERSIONS)) {
    throw new ConfigError('protocol.os 必须是 Linux、Mac 或 Windows')
  }
  const supportedVersions = SUPPORTED_VERSIONS[os]
  if (!supportedVersions) {
    throw new ConfigError(`protocol.os=${os} 没有可用的内置版本`)
  }
  const version = stringValue(protocol, 'version', '53644', 'protocol.version')
  if (version === 'fetched') {
    throw new ConfigError('protocol.version 不能是 fetched；Rizify 默认使用 53644')
  }
  if (!supportedVersions.has(version)) {
    throw new ConfigError(
      `protocol.version=${version} 不受 ${os} 支持；可选值: ${[...supportedVersions].join(', ')}`,
    )
  }
  const signApiUrl = normalizeSignApiUrl(
    stringValue(protocol, 'signApiUrl', DEFAULT_SIGN_API_URL, 'protocol.signApiUrl'),
  )
  const token = expandEnvironment(
    stringValue(protocol, 'pcLagrangeSignToken', undefined, 'protocol.pcLagrangeSignToken'),
    'protocol.pcLagrangeSignToken',
  )

  const milky = optionalTable(root.milky, 'milky')
  rejectUnknownKeys(milky, MILKY_KEYS, 'milky')
  const http = optionalTable(milky.http, 'milky.http')
  rejectUnknownKeys(http, HTTP_KEYS, 'milky.http')
  const host = stringValue(http, 'host', '127.0.0.1', 'milky.http.host')
  if (host.trim().length === 0) {
    throw new ConfigError('milky.http.host 不能为空')
  }
  const port = integerValue(http, 'port', 3000, 'milky.http.port')
  if (port < 1 || port > 65535) {
    throw new ConfigError('milky.http.port 必须在 1 到 65535 之间')
  }
  const prefix = stringValue(http, 'prefix', '', 'milky.http.prefix')
  if (prefix !== '' && !prefix.startsWith('/')) {
    throw new ConfigError('milky.http.prefix 必须以 / 开头或为空')
  }
  if (prefix.includes('?') || prefix.includes('#')) {
    throw new ConfigError('milky.http.prefix 不能包含 query 或 fragment')
  }

  const webhook = optionalTable(milky.webhook, 'milky.webhook')
  const endpoints = parseEndpoints(webhook)

  const logging = optionalTable(root.logging, 'logging')
  rejectUnknownKeys(logging, LOGGING_KEYS, 'logging')
  const ansiLevel = enumValue(
    logging,
    'ansiLevel',
    'ANSI256',
    ANSI_LEVELS,
    'logging.ansiLevel',
  )
  const coreLogLevel = enumValue(
    logging,
    'coreLogLevel',
    'DEBUG',
    LOG_LEVELS,
    'logging.coreLogLevel',
  )

  const security = optionalTable(root.security, 'security')
  rejectUnknownKeys(security, SECURITY_KEYS, 'security')
  const debug = optionalTable(root.debug, 'debug')
  rejectUnknownKeys(debug, DEBUG_KEYS, 'debug')

  return {
    protocol: {
      uin,
      os,
      version,
      signApiUrl,
      pcLagrangeSignToken: token,
      androidUseLegacySign: booleanValue(
        protocol,
        'androidUseLegacySign',
        false,
        'protocol.androidUseLegacySign',
      ),
      autoRenewSession: booleanValue(
        protocol,
        'autoRenewSession',
        true,
        'protocol.autoRenewSession',
      ),
    },
    milky: {
      http: {
        host,
        port,
        prefix,
        accessToken: stringValue(http, 'accessToken', '', 'milky.http.accessToken'),
        corsOrigins: stringArrayValue(http, 'corsOrigins', [], 'milky.http.corsOrigins'),
      },
      webhook: {
        endpoints,
      },
      reportSelfMessage: booleanValue(
        milky,
        'reportSelfMessage',
        true,
        'milky.reportSelfMessage',
      ),
      preloadContacts: booleanValue(
        milky,
        'preloadContacts',
        false,
        'milky.preloadContacts',
      ),
      ffmpegPath: stringValue(milky, 'ffmpegPath', '', 'milky.ffmpegPath'),
    },
    logging: {
      ansiLevel,
      coreLogLevel,
    },
    security: {
      skipOnLaunchListenAddressCheck: booleanValue(
        security,
        'skipOnLaunchListenAddressCheck',
        false,
        'security.skipOnLaunchListenAddressCheck',
      ),
    },
    debug: {
      enableFaceDetailsApi: booleanValue(
        debug,
        'enableFaceDetailsApi',
        false,
        'debug.enableFaceDetailsApi',
      ),
    },
  }
}

export function toYogurtConfig(config: RizifyConfig): YogurtConfigJson {
  return {
    configVersion: 3,
    protocol: {
      uin: config.protocol.uin,
      [PASSWORD_FIELD]: '',
      os: config.protocol.os,
      version: config.protocol.version,
      signApiUrl: config.protocol.signApiUrl,
      pcLagrangeSignToken: config.protocol.pcLagrangeSignToken,
      androidUseLegacySign: config.protocol.androidUseLegacySign,
      autoRenewSession: config.protocol.autoRenewSession,
    },
    milky: config.milky,
    logging: config.logging,
    security: config.security,
    debug: config.debug,
  }
}

async function atomicWrite(filePath: string, content: string, mode: number): Promise<void> {
  await mkdir(path.dirname(filePath), { recursive: true })
  const temporary = `${filePath}.${randomBytes(6).toString('hex')}.tmp`
  try {
    await writeFile(temporary, content, { mode })
    await rename(temporary, filePath)
    await chmod(filePath, mode)
  } catch (error) {
    await unlink(temporary).catch(() => undefined)
    throw error
  }
}

export async function readConfigText(configPath: string): Promise<string | null> {
  try {
    return await readFile(configPath, 'utf8')
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code
    if (code === 'ENOENT') {
      return null
    }
    throw new ConfigError(`无法读取配置文件 ${configPath}: ${String(error)}`)
  }
}

export async function writeConfigTemplate(configPath: string): Promise<void> {
  await atomicWrite(configPath, CONFIG_TEMPLATE, 0o600)
}

export async function writeYogurtConfig(
  dataDirectory: string,
  config: YogurtConfigJson,
): Promise<string> {
  const configPath = path.join(dataDirectory, 'config.json')
  await atomicWrite(configPath, `${JSON.stringify(config, null, 2)}\n`, 0o600)
  return configPath
}

export const CONFIG_TEMPLATE = `# Rizify configuration
# Set protocol.uin to your real QQ number before starting.
# protocol.pcLagrangeSignToken supports $SIGN_TOKEN and \${SIGN_TOKEN}.

[protocol]
uin = 0
os = "Linux"
version = "53644"
signApiUrl = "http://127.0.0.1:8080/"
pcLagrangeSignToken = "$SIGN_TOKEN"
androidUseLegacySign = false
autoRenewSession = true

[milky]
reportSelfMessage = true
preloadContacts = false
ffmpegPath = ""

[milky.http]
host = "127.0.0.1"
port = 3000
prefix = ""
accessToken = ""
corsOrigins = []

[milky.webhook]
# [[milky.webhook.endpoints]]
# url = "http://127.0.0.1:9000/events"
# accessToken = ""

[logging]
ansiLevel = "ANSI256"
coreLogLevel = "DEBUG"

[security]
skipOnLaunchListenAddressCheck = false

[debug]
enableFaceDetailsApi = false
`
