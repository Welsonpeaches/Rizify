# Rizify

> 「7sRef」是一个白塔林立的白色世界。这里是所有色彩与人们的归宿之地。
>
> 七扇门、七个世界、七种法则、七种色彩在此折射变形，最终融合为一。

Rizify 是一个面向 Linux 的 Milky 协议服务端，基于 [Acidify](https://github.com/LagrangeDev/acidify) 与其 Yogurt 模块构建，内置 Linux 客户端 `3.2.34-53644` 的协议信息。

协议主体复用上游 Kotlin Multiplatform 模块：

- `acidify-core`：协议核心实现
- `acidify-milky`：Milky HTTP/WebSocket 适配层
- `yogurt`：协议端、登录、二维码、配置与会话存储

`rizify-cli` 是一个 TypeScript/Node.js 启动外壳，只负责读取 `rizify.toml`、展开环境变量、校验配置、生成 `config.json`、启动原生 `rizify.kexe` 和转发信号。Yogurt 本身不是 TypeScript 项目。

## 7sRef 与命名设定

项目命名与角色映射取自《maimai》的「7sRef」区域设定：

- **7sRef 与白塔**：白塔林立的白色世界，七扇门（7sGate）折射并融汇七个世界、七种法则与七种色彩。穿过门而来的人们被称为**流转者（流転者）**，手中持有记忆「碎片（Fragment）」。
- **Riz（Liz / リズ）→ Rizify**：在 7sRef 失去记忆后苏醒的白色少女（早期设定译作 Liz，后续区域写作 Riz）。她只记得自己的名字与守护这个世界的职责——将流转者持有的记忆「碎片」堆叠成白塔，化作庞大的记忆档案库。
- **Acid → Acidify**：随性出现在 7sRef 的黑衣少女，容貌与 Riz 相似而性格截然相反，自称开朗的珠宝设计师，常向 Riz 献上新作饰品，与 Riz 宛如「镜中倒影」。工程上，Rizify 正是基于上游 **Acidify** 衍生构建的镜像协议端。
- **流转者 → 登录设备名**：登录设备名不再沿用上游的 `Lagrange-*`，新会话统一使用：

  ```text
  流转者-<SHA-256(guid) 的 64 位小写十六进制>
  ```

  读取旧会话时，仅将以 `Lagrange-` 开头的设备名迁移为上述格式；其他自定义设备名保持不变。

设定参考：[Maimai Apocrypha：7sRef 区域](https://www.7sref.cc/areas/7sref.html)。

## 边界

- 仓库不包含签名服务端实现，签名统一调用外部 LagrangeSignServer V2：
  `POST /api/sign/sec-sign`
- Rizify 不实现签名算法，不包含 `wrapper.node`，也不依赖 `wrapper.node`。
- 默认签名服务根地址为 `http://127.0.0.1:8080/`。
- `signApiUrl` 必须是根地址。Yogurt 会自行追加 `/api/sign/sec-sign`，不要填写 `/api/` 或完整的 `/api/sign/sec-sign`。
- 本项目不修改、不启动、不打包 Python LagrangeSignServer。

## 支持的版本

| 系统 | 版本 | 默认 | 说明 |
| --- | --- | --- | --- |
| Linux | `53644` | 是 | Linux 客户端 `3.2.34-53644`，内置 |
| Linux | `46494` | 否 | Linux 客户端 `3.2.26-46494`，内置 |
| Linux | `39038` | 否 | Linux 客户端 `3.2.19-39038`，内置 |
| macOS | `52892` | 否 | macOS 客户端 `7.0.1-52892`，内置 |
| macOS | `52194` | 否 | macOS 客户端 `7.0.0-52194`，内置 |
| 任意 PC | `custom` | 否 | 读取数据目录下的 `app-info.json` |

Linux 默认 `AppInfo` 为 `AppInfo.Bundled.Linux_53644`，其 QUA 严格为：

```text
V1_LNX_NQ_3.2.34_53644_GW_B
```

`custom` 模式要求 `<data-dir>/app-info.json` 存在；不会退回内置版本。`fetched` 在 `rizify.toml` 中会被拒绝。原生 Yogurt 读取旧的 V3 `config.json` 时，只会把哨兵值 `fetched` 归一化为 `53644`，以兼容旧配置迁移。

## 构建

环境要求：

- JDK 25 或更新版本
- Node.js `>= 20`
- pnpm

默认 Gradle target 是 `jvm + linuxX64`，因此在 Linux 上可以直接执行：

```bash
JAVA_HOME=/usr/lib/jvm/java-27-openjdk ./gradlew build --console=plain --no-daemon
```

单独构建 Linux 原生产物：

```bash
JAVA_HOME=/usr/lib/jvm/java-27-openjdk \
GITHUB_ACTIONS_BUILD_TARGET=linuxX64 \
./gradlew :yogurt:linkReleaseExecutableLinuxX64 --console=plain --no-daemon
```

产物路径：

```text
yogurt/build/bin/linuxX64/releaseExecutable/rizify.kexe
```

构建 TypeScript 启动器和原生包：

```bash
pnpm install
pnpm build
```

验证版本：

```bash
node rizify-cli/dist/index.mjs --version
# Rizify 0.1.0
```

`GITHUB_ACTIONS_BUILD_TARGET` 可取 `all`、`jvm`、`mingwX64`、`macosArm64`、`linuxX64`、`linuxArm64`。不设置时只在 Linux 上构建 `jvm + linuxX64`。

## 配置

首次运行会在当前目录生成 `rizify.toml` 并退出。模板中的 `uin = 0` 不能启动，必须改成真实账号。Rizify 不支持 `uin = 0` 的二维码发现模式。

最小配置：

```toml
[protocol]
uin = 123456789
os = "Linux"
version = "53644"
signApiUrl = "http://127.0.0.1:8080/"
pcLagrangeSignToken = "$SIGN_TOKEN"

[milky.http]
host = "127.0.0.1"
port = 3000
```

设置 token：

```bash
export SIGN_TOKEN='你的 LagrangeSignServer token'
```

也支持 `${SIGN_TOKEN}`。变量未设置或为空时，启动器会在启动原生进程前报错，不会把 token 打印到日志。

完整配置模板：

```toml
[protocol]
uin = 123456789
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
```

启动器会校验未知字段、端口范围、协议版本、`signApiUrl`、`uin` 和 token 环境变量。Kotlin 实际读取的 `config.json` 会以 `0600` 权限原子写入数据目录，`configVersion = 3`。

## 启动

```bash
pnpm start
```

或指定配置文件和数据目录：

```bash
node rizify-cli/dist/index.mjs \
  --config /path/to/rizify.toml \
  --data-dir /path/to/data
```

数据目录默认是 `rizify.toml` 所在目录，原生进程以该目录为 cwd。启动后应看到：

```text
Rizify v0.1.0
使用协议 Linux 3.2.34-53644 (AppId: 537391664)
QUA: V1_LNX_NQ_3.2.34_53644_GW_B
```

数据目录中的主要文件：

- `config.json`：启动器生成的 V3 配置
- `session-store.json`：登录会话
- `qrcode.png`：二维码登录图片
- `app-info.json`：仅 `version = "custom"` 时使用

## 签名排查

服务端日志中的协议行和 QUA 行应分别是：

```text
使用协议 Linux 3.2.34-53644 (AppId: 537391664)
QUA: V1_LNX_NQ_3.2.34_53644_GW_B
```

签名请求应为：

```text
POST /api/sign/sec-sign
```

如果签名服务返回 `400`，先检查：

1. `protocol.os = "Linux"`、`protocol.version = "53644"`。
2. 日志中的 QUA 是否严格等于 `V1_LNX_NQ_3.2.34_53644_GW_B`。
3. `signApiUrl` 是否为 `http://127.0.0.1:8080/` 这样的根地址，没有 `/api/` 后缀。
4. 数据目录中是否误放了旧 `app-info.json` 并仍在使用 `custom`。
5. token 是否通过 `SIGN_TOKEN` 正确注入，但不要把 token 贴到日志或问题报告中。

不要通过修改 Python SignServer 来绕过 Rizify 的 AppInfo/QUA 问题。

## 53644 适配

与旧版 Linux 客户端相比，53644 的二维码 TLV `D1` 第 4 字段由旧的 `typeBuf = "3001"` 改为 `GenInfo`：

- `GenInfo.field 3 = appInfo.appId`
- `GenInfo.field 6 = 1`，使用 `@EncodeDefault` 保证 protobuf 不会省略

触发条件是 `appInfo.appClientVersion >= 53644`。Linux `39038`、`46494` 继续使用旧 `typeBuf` 分支，避免破坏旧版本登录。这里只做登录包字段适配，不包含任何签名算法。

## 构建适配

上游 Gradle 配置默认会尝试所有原生 target。Rizify 在 Linux 本地构建时默认只启用 `jvm + linuxX64`，并通过 `GITHUB_ACTIONS_BUILD_TARGET` 显式启用其他 target。`yogurt` 和 `acidify-core-runner` 中依赖特定 target 的依赖块与 Windows linker 配置已加 target 存在性保护，避免 reduced-target 的 KMP metadata 解析失败。这不改变协议实现。

当前仓库如果没有提交，`BuildKonfig.commitHash` 和 `coreVersion` 会回退显示 `unknown`；这是为了让空仓库仍可构建，不代表协议版本未知。

## 许可证与上游

Rizify 基于 [Acidify](https://github.com/LagrangeDev/acidify) 和其 Yogurt 模块，基线 commit：

```text
b8fc6b4fa9a1651d5687ad8bd02de2e3df64e00b
```

Rizify 以 GPL-3.0-only 发布，保留上游 `LICENSE`、源文件版权/许可证头和 attribution。详见 [NOTICE](NOTICE)。

上游相关项目：

- [Acidify](https://github.com/LagrangeDev/acidify)
- [Yogurt releases](https://github.com/SaltifyDev/yogurt-releases)
- [Lagrange.Core](https://github.com/LagrangeDev/Lagrange.Core)

## 特别致谢

- Acidify 提供项目基础架构、连接协议实现与 Milky 适配
- Yogurt 提供 PC/Android 协议端与登录流程
- Lagrange.Core 提供基础架构和大量协议包定义
- Konata.Core 提供最初的 PC 连接协议实现
- lagrange-kotlin 提供 TEA 与登录认证实现
- qrcode-kotlin 提供二维码矩阵生成
- LagrangeCodec 提供多媒体编解码
- [@Linwenxuan04](https://github.com/Linwenxuan04) 编写 crypto 和 math 部分
- 以及所有沿途贡献者

## 贡献者

### Acidify

![Contributors of Acidify](https://contributors-img.web.app/image?repo=LagrangeDev/Acidify)

### Lagrange.Core

![Contributors of Lagrange.Core](https://contributors-img.web.app/image?repo=LagrangeDev/Lagrange.Core)

### LagrangeV2

![Contributors of LagrangeV2](https://contributors-img.web.app/image?repo=LagrangeDev/LagrangeV2)

### Konata.Core

![Contributors of Konata.Core](https://contributors-img.web.app/image?repo=KonataDev/Konata.Core)
