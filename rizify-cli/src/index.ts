#!/usr/bin/env node

import { existsSync } from 'node:fs'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import {
  ConfigError,
  DEFAULT_SIGN_API_URL,
  RIZIFY_VERSION,
  parseRizifyToml,
  readConfigText,
  toYogurtConfig,
  writeConfigTemplate,
  writeYogurtConfig,
} from './config.js'

const DEFAULT_CONFIG_NAME = 'rizify.toml'
const FORWARDED_SIGNALS: NodeJS.Signals[] = ['SIGINT', 'SIGTERM', 'SIGHUP']

interface CliOptions {
  configPath: string
  dataDirectory?: string
}

function usage(): string {
  return `Rizify ${RIZIFY_VERSION}

用法:
  rizify [--config <rizify.toml>] [--data-dir <目录>]
  rizify --version
  rizify --help

配置:
  默认读取当前目录的 ${DEFAULT_CONFIG_NAME}。
  首次缺少配置时会生成模板并退出，需填写 [protocol].uin。
  数据目录默认是配置文件所在目录，原生进程在该目录中运行。

签名:
  protocol.signApiUrl 必须是根地址（默认 ${DEFAULT_SIGN_API_URL}）。
  Yogurt 会自行追加 /api/sign/sec-sign。
  protocol.pcLagrangeSignToken 支持 $SIGN_TOKEN / \${SIGN_TOKEN}。

环境变量:
  SIGN_TOKEN          签名服务 token，配置中引用时展开。
  RIZIFY_NATIVE_BIN   覆盖原生 rizify.kexe 路径（测试用）。

构建:
  pnpm build
  pnpm start`
}

function parseArguments(argv: string[]): CliOptions | 'help' | 'version' {
  let configPath: string | undefined
  let dataDirectory: string | undefined

  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index]
    if (argument === undefined) {
      continue
    }
    if (argument === '--help' || argument === '-h') {
      return 'help'
    }
    if (argument === '--version' || argument === '-V') {
      return 'version'
    }
    if (argument === '--config') {
      const value = argv[++index]
      if (!value) {
        throw new ConfigError('--config 需要一个文件路径')
      }
      configPath = value
      continue
    }
    if (argument.startsWith('--config=')) {
      configPath = argument.slice('--config='.length)
      if (!configPath) {
        throw new ConfigError('--config 需要一个文件路径')
      }
      continue
    }
    if (argument === '--data-dir') {
      const value = argv[++index]
      if (!value) {
        throw new ConfigError('--data-dir 需要一个目录路径')
      }
      dataDirectory = value
      continue
    }
    if (argument.startsWith('--data-dir=')) {
      dataDirectory = argument.slice('--data-dir='.length)
      if (!dataDirectory) {
        throw new ConfigError('--data-dir 需要一个目录路径')
      }
      continue
    }
    throw new ConfigError(`未知参数: ${argument}`)
  }

  return {
    configPath: path.resolve(process.cwd(), configPath ?? DEFAULT_CONFIG_NAME),
    dataDirectory: dataDirectory
      ? path.resolve(process.cwd(), dataDirectory)
      : undefined,
  }
}

function nativeBinaryPath(): string {
  const override = process.env.RIZIFY_NATIVE_BIN
  if (override) {
    return path.resolve(process.cwd(), override)
  }
  return fileURLToPath(new URL('./native/rizify.kexe', import.meta.url))
}

async function run(options: CliOptions): Promise<void> {
  const configText = await readConfigText(options.configPath)
  if (configText === null) {
    await writeConfigTemplate(options.configPath)
    console.error(`Rizify 配置模板已生成: ${options.configPath}`)
    console.error('请填写 [protocol].uin 并设置 SIGN_TOKEN 后重新运行。')
    process.exitCode = 2
    return
  }

  const config = parseRizifyToml(configText, options.configPath)
  const dataDirectory = path.resolve(
    options.dataDirectory ?? path.dirname(options.configPath),
  )
  await mkdir(dataDirectory, { recursive: true })

  if (config.protocol.version === 'custom') {
    const appInfoPath = path.join(dataDirectory, 'app-info.json')
    if (!existsSync(appInfoPath)) {
      throw new ConfigError(
        `protocol.version=custom 需要自定义 AppInfo 文件: ${appInfoPath}`,
      )
    }
  }

  const yogurtConfigPath = await writeYogurtConfig(dataDirectory, toYogurtConfig(config))
  const binary = nativeBinaryPath()
  if (!existsSync(binary)) {
    throw new ConfigError(
      `未找到原生可执行文件: ${binary}\n请先运行 pnpm build，或设置 RIZIFY_NATIVE_BIN。`,
    )
  }

  console.error(`Rizify 数据目录: ${dataDirectory}`)
  console.error(`Rizify 配置: ${yogurtConfigPath}`)

  const child = spawn(binary, [], {
    cwd: dataDirectory,
    env: process.env,
    stdio: 'inherit',
  })

  const signalHandlers = new Map<NodeJS.Signals, () => void>()
  for (const signal of FORWARDED_SIGNALS) {
    const handler = (): void => {
      child.kill(signal)
    }
    signalHandlers.set(signal, handler)
    process.on(signal, handler)
  }

  const removeSignalHandlers = (): void => {
    for (const [signal, handler] of signalHandlers) {
      process.removeListener(signal, handler)
    }
  }

  child.on('error', (error) => {
    removeSignalHandlers()
    console.error(`无法启动 Rizify 原生进程: ${String(error)}`)
    process.exitCode = 1
  })

  child.on('exit', (code, signal) => {
    removeSignalHandlers()
    if (signal) {
      process.kill(process.pid, signal)
      return
    }
    process.exitCode = code ?? 1
  })
}

async function main(): Promise<void> {
  const parsed = parseArguments(process.argv.slice(2))
  if (parsed === 'help') {
    console.log(usage())
    return
  }
  if (parsed === 'version') {
    console.log(`Rizify ${RIZIFY_VERSION}`)
    return
  }
  await run(parsed)
}

main().catch((error: unknown) => {
  if (error instanceof ConfigError) {
    console.error(`Rizify 配置错误: ${error.message}`)
  } else {
    console.error(`Rizify 启动失败: ${error instanceof Error ? error.message : String(error)}`)
  }
  process.exitCode = 1
})
