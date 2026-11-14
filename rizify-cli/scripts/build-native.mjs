import { chmodSync, copyFileSync, existsSync, mkdirSync, readdirSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repositoryRoot = path.resolve(packageRoot, '..')
const env = {
  ...process.env,
  GITHUB_ACTIONS_BUILD_TARGET: 'linuxX64',
}

if (!env.JAVA_HOME) {
  const candidates = [
    '/usr/lib/jvm/java-27-openjdk',
    '/usr/lib/jvm/java-25-openjdk',
  ]
  const javaHome = candidates.find((candidate) => existsSync(candidate))
  if (javaHome) {
    env.JAVA_HOME = javaHome
  }
}

const result = spawnSync(
  path.join(repositoryRoot, 'gradlew'),
  [':yogurt:linkReleaseExecutableLinuxX64', '--console=plain', '--no-daemon'],
  {
    cwd: repositoryRoot,
    env,
    stdio: 'inherit',
  },
)

if (result.error) {
  throw result.error
}
if (result.status !== 0) {
  process.exit(result.status ?? 1)
}

const releaseDirectory = path.join(
  repositoryRoot,
  'yogurt',
  'build',
  'bin',
  'linuxX64',
  'releaseExecutable',
)
const executable = ['rizify.kexe', 'rizify'].find((name) =>
  existsSync(path.join(releaseDirectory, name)),
)
if (!executable) {
  const entries = readdirSync(releaseDirectory).join(', ')
  throw new Error(`未找到 Linux 原生产物。${releaseDirectory} 内容: ${entries}`)
}

const destinationDirectory = path.join(packageRoot, 'dist', 'native')
const destination = path.join(destinationDirectory, 'rizify.kexe')
mkdirSync(destinationDirectory, { recursive: true })
copyFileSync(path.join(releaseDirectory, executable), destination)
chmodSync(destination, 0o755)
console.log(`Rizify native binary: ${destination}`)
