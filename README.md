# Rizify

> 「7sRef」是一个白塔林立的白色世界。这里是所有色彩与人们的归宿之地。
>
> 七扇门、七个世界、七种法则、七种色彩在此折射变形，最终融合为一。
> 这是一座为原本没有权限进入 7sRef 的人敞开的通道——由 **PRiSM** 伪造通行的「碎片」，借由 **Riz** 留存流转者的记录。

在 7sRef 的白色世界里，没有相应碎片的人会被挡在七扇门外。**Rizify** 正是为本身没有权限进入 7sRef 的人制作的实现端：它基于与 **Riz** 互为「镜中倒影」的 [Acidify](https://github.com/LagrangeDev/acidify) 与 Yogurt 模块构建，默认内置 Linux 客户端 `3.2.34-53644` 的协议档案，由外部 **PRiSM** 负责伪造通行的「碎片」（数据包签名），使流转者得以穿过门扉、以 Milky 接口接入并把记录堆叠进白塔。

白塔由以下模块共同支起：

- `acidify-core`：镜中倒影的另一半，承载底层协议核心实现
- `acidify-milky`：Milky HTTP / WebSocket 适配层，将碎片折射为标准事件与接口
- `yogurt`：协议端核心，负责登录、二维码、配置迁移与白塔会话存储
- `rizify-cli`：TypeScript / Node.js 启动外壳，负责读取 `rizify.toml`、展开环境变量、校验配置、生成 `config.json`、拉起原生 `rizify.kexe` 并转发进程信号（Yogurt 本身是 Kotlin Multiplatform 模块，并非 TypeScript 项目）

## 7sRef 与命名设定

Rizify 的命名与身份体系源自《maimai》的「7sRef」区域设定：

- **7sRef 与白塔**：白塔林立的白色世界，所有色彩与人们的归宿之地；七扇门（7sGate）通向七个世界，将七种法则与色彩折射融汇为一。每一座白塔都是由碎片组合而成的庞大记忆档案库。
- **Riz（Liz / リズ）→ Rizify**：在 7sRef 失去记忆后苏醒的白色少女（早期区域译作 Liz，后续区域写作 Riz），职责是将流转者持有的记忆「碎片（Fragment）」堆叠成塔。Rizify 即以此为名，作为帮助无权限者穿过门扉、并留存交互记录的协议端。
- **Acid → Acidify**：随性现身于 7sRef 的黑衣少女，容貌与 Riz 相似而性格截然相反，自称开朗的珠宝设计师，常把新作饰品送给 Riz，与 Riz 宛如「镜中倒影」。工程上，Rizify 正是基于上游 **Acidify** 衍生构建的镜像协议端。
- **PRiSM → 外部碎片伪造（签名服务）**：七扇门仅凭真正的碎片放行。为了让原本没有权限进入 7sRef 的人也能跨越门扉，必须由外部的 **PRiSM**（`LagrangeSignServer V2`）来**伪造通行的「碎片」（数据包签名）**；Rizify 本身只作为实现端向外请求伪造碎片，不在内部复制或实现伪造算法。
- **流转者（流転者）→ 登录设备名**：持着 PRiSM 伪造的碎片穿过七扇门、进入 7sRef 的旅人。Rizify 不再沿用上游的 `Lagrange-*`，新会话统一使用：

  ```text
  流转者-<SHA-256(guid) 的 64 位小写十六进制>
  ```

  读取旧会话时，仅将以 `Lagrange-` 开头的设备名迁移为上述格式；其他自定义设备名保持不变。

设定参考：[Maimai Apocrypha：7sRef 区域](https://www.7sref.cc/areas/7sref.html)。

## PRiSM 与碎片边界（外部签名约定）

通行的碎片由外部 **PRiSM** 伪造，Rizify 仅负责协议交互本身：

- 本仓库**不包含签名服务端**，不实现也不复制签名算法，不包含也不依赖 `wrapper.node`。
- 所有需要碎片的报文统一交由外部 **PRiSM（LagrangeSignServer V2）** 伪造并返回签名：
  `POST /api/sign/sec-sign`
- 默认签名服务根地址为 `http://127.0.0.1:8080/`。
- `signApiUrl` 必须填写根地址；Yogurt 会自行拼接 `/api/sign/sec-sign`，切勿写成 `/api/` 或完整路径。
- 本项目不修改、不内置、不启动、不打包 Python LagrangeSignServer。

## 门后折射的世界（支持的版本）

不同的门扉折射着不同版本的客户端法则，白塔默认以 Linux `53644` 作为主档案，同时保留历史与自定义折射路径：

| 系统 | 版本 | 默认 | 说明 |
| --- | --- | --- | --- |
| Linux | `53644` | 是 | Linux 客户端 `3.2.34-53644`，默认内置 |
| Linux | `46494` | 否 | Linux 客户端 `3.2.26-46494`，内置保留 |
| Linux | `39038` | 否 | Linux 客户端 `3.2.19-39038`，内置保留 |
| macOS | `52892` | 否 | macOS 客户端 `7.0.1-52892`，内置保留 |
| macOS | `52194` | 否 | macOS 客户端 `7.0.0-52194`，内置保留 |
| 任意 PC | `custom` | 否 | 显式读取数据目录下的 `app-info.json` |

Linux 默认 `AppInfo` 为 `AppInfo.Bundled.Linux_53644`，其 QUA 严格为：

```text
V1_LNX_NQ_3.2.34_53644_GW_B
```

`custom` 模式要求 `<data-dir>/app-info.json` 存在，缺失时会直接报错而不会回退到内置版本。`rizify.toml` 拒绝 `fetched`；原生 Yogurt 读取旧版 V3 `config.json` 时，则只会将哨兵值 `fetched` 归一化为 `53644`，以便旧档案迁移。

## 筑塔（构建）

环境要求：

- JDK 25 或更新版本
- Node.js `>= 20`
- pnpm

默认 Gradle target 为 `jvm + linuxX64`，在 Linux 上可直接完成编译与测试：

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

构建 TypeScript 启动器并打包原生产物：

```bash
pnpm install
pnpm build
```

验证版本：

```bash
node rizify-cli/dist/index.mjs --version
# Rizify 0.1.0
```

`GITHUB_ACTIONS_BUILD_TARGET` 支持 `all`、`jvm`、`mingwX64`、`macosArm64`、`linuxX64`、`linuxArm64`；未设置时在 Linux 上只构建 `jvm + linuxX64`。

## 门前契约（配置 `rizify.toml`）

首次运行会在当前目录生成 `rizify.toml` 模板并退出。模板中的 `uin = 0` 无法穿过门扉，必须填写真实账号；Rizify 不支持 `uin = 0` 的二维码发现模式。

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

注入向外部 PRiSM（`LagrangeSignServer V2`）请求伪造碎片时的凭证 token：

```bash
export SIGN_TOKEN='你的 LagrangeSignServer token'
```

支持 `$SIGN_TOKEN` 与 `${SIGN_TOKEN}`。变量未设置或为空时，启动器会在拉起原生进程前拦截报错，绝不把 token 写入日志。

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

启动器会在入门前校验未知字段、端口范围、协议版本、`signApiUrl`、`uin` 与 token 环境变量；校验通过后，将原生进程读取的 `config.json`（`configVersion = 3`）以 `0600` 权限原子写入数据目录。

## 启门与白塔档案（启动与运行目录）

```bash
pnpm start
```

或显式指定契约文件与白塔档案目录：

```bash
node rizify-cli/dist/index.mjs \
  --config /path/to/rizify.toml \
  --data-dir /path/to/data
```

数据目录默认为 `rizify.toml` 所在目录，原生进程会以该目录作为工作目录。顺利启门后，日志中应出现：

```text
Rizify v0.1.0
使用协议 Linux 3.2.34-53644 (AppId: 537391664)
QUA: V1_LNX_NQ_3.2.34_53644_GW_B
```

白塔档案目录中的主要文件：

- `config.json`：启动器生成的 V3 配置
- `session-store.json`：流转者的登录会话档案（设备名记录于此）
- `qrcode.png`：二维码登录图片
- `app-info.json`：仅 `version = "custom"` 时使用

## 杂讯消除与版本适配

当碎片失真或门后的法则更新时，流转通道会出现杂讯。Rizify 的排查准则与面向 `53644` 的必要适配如下：

### PRiSM 拒绝伪造碎片（签名 `400` 排查）

正常运行时，日志中的协议版本行与签名请求应严格符合：

```text
使用协议 Linux 3.2.34-53644 (AppId: 537391664)
QUA: V1_LNX_NQ_3.2.34_53644_GW_B
POST /api/sign/sec-sign
```

如果外部 PRiSM（`LagrangeSignServer V2`）返回 `400`，按顺序检查以下五项：

1. `protocol.os` 是否为 `"Linux"`、`protocol.version` 是否为 `"53644"`。
2. 日志中的 QUA 是否严格等于 `V1_LNX_NQ_3.2.34_53644_GW_B`。
3. `signApiUrl` 是否为 `http://127.0.0.1:8080/` 这类根地址，未多写 `/api/` 后缀。
4. 数据目录中是否误留了旧 `app-info.json` 并仍启用 `custom`。
5. `SIGN_TOKEN` 是否正确注入（切勿把 token 贴入日志或公开报告）。

请勿通过修改 Python LagrangeSignServer 来绕过 Rizify 自身的 AppInfo / QUA 问题。

### 53644 二维码 TLV `D1` 适配

相较于旧版 Linux 客户端，`53644` 将二维码登录 TLV `D1` 的第 4 字段由旧的 `typeBuf = "3001"` 变更为 `GenInfo`：

- `GenInfo.field 3 = appInfo.appId`
- `GenInfo.field 6 = 1`，使用 `@EncodeDefault` 保证 protobuf 不会省略

该适配仅在 `appInfo.appClientVersion >= 53644` 时生效；Linux `39038` 与 `46494` 仍保留原有 `typeBuf` 分支，避免影响旧版本登录。此处仅调整登录包字段，碎片伪造仍全部交由外部 PRiSM，不包含任何签名算法。

### 构建适配

上游 Gradle 配置默认尝试启用全部原生 target；Rizify 在 Linux 本地默认仅启用 `jvm + linuxX64`，并通过 `GITHUB_ACTIONS_BUILD_TARGET` 按需开启其他平台。`yogurt` 与 `acidify-core-runner` 中针对特定平台的依赖块及 Windows linker 配置均已加入 target 存在性保护，避免裁剪 target 时 KMP metadata 解析失败。该改动不改变协议行为。

在无 Git 提交信息的源码快照环境下，`BuildKonfig.commitHash` 与 `coreVersion` 会安全回退为 `unknown`。

## 归宿、许可证与上游

正如七个世界最终在 7sRef 交汇，Rizify 也建立在上游开源项目的基石之上，基线来自 [Acidify](https://github.com/LagrangeDev/acidify)：

```text
b8fc6b4fa9a1651d5687ad8bd02de2e3df64e00b
```

Rizify 延续 `GPL-3.0-only` 许可证发布，完整保留上游 `LICENSE`、源文件版权/许可证头与归属说明，详见 [NOTICE](NOTICE)。

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
