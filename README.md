# Rizify

> 「7sRef」是一个白塔林立的白色世界。这里是所有色彩与人们的归宿之地。
>
> 七扇门、七个世界、七种法则、七种色彩在此折射变形，最终融合为一。
> 这是一座为原本没有权限进入 7sRef 的人敞开的通道——由 **PRiSM** 伪造通行的「碎片」，借由 **Riz** 留存流转者的记录。

Rizify 是纯 Python 的 Milky 协议服务端。它不依赖 Yogurt，也不携带 JVM、Node.js 或原生二进制启动器。协议核心 `acidify-core` 已从 Acidify 的公开行为重写为 Python，Rizify 则在该核心之上实现登录、会话、配置、日志与 Milky HTTP / WebSocket / SSE 服务。

通行所需的「碎片」（报文签名）由外部 **PRiSM** 伪造。Rizify 只请求碎片，不实现、复制或逆向签名算法，也不依赖 `wrapper.node`。

## 设定

- **7sRef 与白塔**：白塔林立的白色世界，七扇门通向七个世界；每一座白塔都由「碎片」堆叠成的记忆档案。
- **Riz / Rizify**：失去记忆后苏醒的白色少女，把流转者的记忆碎片堆叠成塔。Rizify 以此为名，为没有权限进入 7sRef 的人提供通行实现。
- **Acid / Acidify**：与 Riz 互为镜中倒影的黑衣少女。Python 协议核心保留了 Acidify 的协议语义、版权与 GPL 归属。
- **PRiSM**：伪造通行「碎片」的外部签名服务。Rizify 只通过 HTTP 调用它，绝不把签名实现纳入本仓库。
- **流转者**：借 PRiSM 伪造的碎片穿过门扉的旅人。登录设备名统一为 `流转者-<SHA-256(guid) 前 8 位小写十六进制>`；旧 `Lagrange-*` 与旧 64 位摘要会在读取时迁移，自定义名称保持不变。

设定参考：[Maimai Apocrypha：7sRef 区域](https://www.7sref.cc/areas/7sref.html)。

## PRiSM 边界

- 本仓库没有签名服务端，没有签名算法，也没有 `wrapper.node`。
- 外部端点固定为：

  ```text
  POST /api/sign/sec-sign
  ```

- 默认 PRiSM 根地址为 `http://127.0.0.1:8080/`。
- `protocol.signApiUrl` 必须填写根地址。Rizify 会自行追加 `api/sign/sec-sign`，因此不要写 `/api/` 或完整路径，也不要附加 query 或 fragment。
- 推荐从环境变量展开令牌：`pcLagrangeSignToken = "$SIGN_TOKEN"` 或 `"${SIGN_TOKEN}"`。变量缺失或为空时直接拒绝启动，且不会输出令牌内容；为兼容旧配置，也接受非空字面值，但令牌会保存在配置文件中。
- 本仓库不修改、不启动、不打包外部 PRiSM 服务。

## 内置协议档案

| 系统 | 版本 | 默认 | 说明 |
| --- | --- | --- | --- |
| Linux | `53644` | 是 | 客户端 `3.2.34-53644` |
| Linux | `46494` | 否 | 客户端 `3.2.26-46494` |
| Linux | `39038` | 否 | 客户端 `3.2.19-39038` |
| macOS | `52892` | 否 | 客户端 `7.0.1-52892` |
| macOS | `52194` | 否 | 客户端 `7.0.0-52194` |
| 任意 PC | `custom` | 否 | 读取数据目录的 `app-info.json` |

Linux 默认使用 `3.2.34-53644`。在没有 `app-info.json` 的情况下也会直接以该档案启动，QUA 严格为：

```text
V1_LNX_NQ_3.2.34_53644_GW_B
```

`custom` 模式要求数据目录存在 `app-info.json`；缺失时会报出完整路径，不会回退到内置版本。`fetched` 已在配置层拒绝。

## 安装与启动

环境要求：

- Python `>= 3.12`
- [uv](https://docs.astral.sh/uv/)

同步依赖并检查入口：

```bash
uv sync --frozen
uv run rizify --version
```

首次在任意目录运行：

```bash
uv run rizify
```

首次运行会在**当前工作目录**生成 `rizify.toml`，返回码为 `2`，然后退出。配置文件默认与数据目录相同；可用 `--config` 和 `--data-dir` 分离二者。

最小配置：

```toml
[protocol]
uin = 123456789
os = "Linux"
version = "53644"
signApiUrl = "http://127.0.0.1:8080/"
pcLagrangeSignToken = "$SIGN_TOKEN"

[milky]
reportSelfMessage = true
preloadContacts = true
ffmpegPath = "ffmpeg"

[milky.http]
host = "127.0.0.1"
port = 3000
prefix = "/api"

[milky.webhook]
endpoints = []

[logging]
level = "INFO"

[security]
accessToken = ""
corsOrigins = ["*"]

[debug]
enabled = false
```

`protocol.uin` 必须显式填写且大于 `0`。当前实现不提供 `uin = 0` 的二维码账号发现模式。

设置令牌并启动：

```bash
export SIGN_TOKEN='由 PRiSM 提供的令牌'
uv run rizify --config /path/to/rizify.toml
```

指定独立数据目录：

```bash
uv run rizify \
  --config /path/to/rizify.toml \
  --data-dir /path/to/runtime-data
```

数据目录中的文件：

| 文件 | 用途 |
| --- | --- |
| `session.json` | 登录凭证与流转者设备名 |
| `qrcode.png` | 二维码登录图片 |
| `app-info.json` | 仅 `custom` 模式使用的协议档案 |
| `rizify.toml` | 默认配置与数据目录相同时出现 |

旧版 `session-store.json` 会在首次读取时迁移为 `session.json`。

启动日志包含：

```text
使用协议 Linux 3.2.34-53644 (AppId: 537391664)
QUA: V1_LNX_NQ_3.2.34_53644_GW_B
碎片签发端点: http://127.0.0.1:8080/api/sign/sec-sign
```

## Milky 服务

默认监听 `127.0.0.1:3000`。所有业务接口位于 `/api/*`，使用 JSON POST；事件流位于 `/event`，同时支持 WebSocket 与 SSE。

主要能力：

- 登录信息、自身资料、好友、群、群成员查询
- 私聊与群聊消息发送、撤回、历史、已读、转发、资源临时链接
- 好友请求、群通知、入群请求与邀请处理
- 群管理、公告、精华、表情回应、戳一戳、群文件浏览与操作
- 置顶、收藏表情、Cookie 与 CSRF 查询
- Webhook、Bearer 认证、CORS、统一响应结构

认证配置：

```toml
[security]
accessToken = "调用方令牌"
corsOrigins = ["https://example.com"]
```

设置后，业务接口需要：

```text
Authorization: Bearer 调用方令牌
```

事件流也接受 `?access_token=调用方令牌`。

## 53644 适配

`3.2.34-53644` 对登录包 D1 的第四字段有结构调整。Rizify 在 `appClientVersion >= 53644` 时写入 `GenInfo`：

- field 3：`clientAppid = appId`
- field 6：固定为 `1`
- 不再发送旧版本的 `typeBuf = "3001"`

较早版本继续使用旧 `typeBuf` 行为。该适配只影响登录包结构，不包含任何签名逻辑。53644 之外没有新增专属消息命令或 Linux 白名单分支；现有 Linux 登录与消息命令白名单继续复用。

## 检查与构建

```bash
uv sync --frozen
uv run ruff check .
uv run mypy acidify-core/src rizify/src tests
uv run pytest
uv build --package acidify-core
uv build --package rizify
```

产物位于 `dist/`。开发环境内直接运行使用 `uv run rizify`。

独立性检查会扫描 Python 源码，禁止 Yogurt 导入、子进程启动、`rizify.kexe`、`wrapper.node` 和本地签名算法实现。

## 当前限制

- 尚未完成头像与私有文件 / 群文件的 Highway 上传闭环；相关 Milky 接口会明确返回 `-501`，不会伪装成功。
- 入站消息、戳一戳、撤回、置顶、群禁言、群精华、表情回应、成员变化和管理员变化事件已解析；入群请求事件暂未补全通知序号与附言，LightApp 群邀请事件尚未解析，管理员变化的操作者字段暂为 `0`。
- 登录流程、二维码状态轮询与文本发送已接入协议层，但真实账号登录仍受账号风控、网络和扫码状态影响。
- 主要验收平台为 Linux x86_64；macOS 路径保留在协议档案中，未做实机验收。

## 许可证与归属

Rizify 以 **GPL-3.0-only** 发布，完整条款见 [LICENSE](LICENSE)。

Python 协议核心基于 [Acidify](https://github.com/LagrangeDev/acidify) 的公开行为重写，基线为 `b8fc6b4fa9a1651d5687ad8bd02de2e3df64e00b`。上游版权、许可证与归属说明保留在 [NOTICE](NOTICE)；Rizify 不删除、不替换上游的 GPL 许可与版权头。

外部 PRiSM 服务不属于本仓库，也不在 GPL-3.0-only 的授权范围内。
