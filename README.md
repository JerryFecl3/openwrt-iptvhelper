# OpenWrt IPTV Helper

IPTV 助手：平台认证与会话管理、频道及节目单采集、SQLite 存储、M3U/XMLTV 发布，以及 LuCI 状态与配置页面。

当前源码对应 `luci-app-iptvhelper 0.4.1-r1`。适配器已在辽宁联通华为平台及 OpenWrt 25.12 系列 x86_64 环境验证；不是通用的所有运营商客户端。

## 界面预览

以下图片经过脱敏处理，账号、专网 IP、MAC、平台地址及主机名已遮盖；媒体服务地址保留，用于展示访问入口。

### 状态总览

![IPTV 助手状态总览](docs/screenshots/overview.png)

### 网络状态

![IPTV 专网接入与专用路由](docs/screenshots/network.png)

### 平台状态

![平台认证与业务会话](docs/screenshots/platform.png)

### 媒体状态

![媒体采集与服务](docs/screenshots/media.png)

### 网页播放器（rtp2httpd）

下图为 [rtp2httpd](https://github.com/stackia/rtp2httpd) 提供的网页播放器，使用本助手采集整理的频道与节目单；播放器界面及播放能力来自 rtp2httpd。

![rtp2httpd 网页播放器](docs/screenshots/player.png)

## 两个独立项目

网络接入可使用另一个仓库 `openwrt-dhcpplus`。本项目只依赖已经可用的 IPTV 逻辑接口，不要求必须使用 DHCP+。

```text
openwrt-iptv/   OpenWrt 服务、LuCI、配置、打包与测试
iptv-client/    平台认证、业务发现、频道和 EPG 解析组件及测试
```

两部分源码在本仓库中完整保留；不需要研究工作区、机顶盒备份或相邻的外部仓库。

## rtp2httpd 与致谢

感谢 [rtp2httpd](https://github.com/stackia/rtp2httpd) 的作者及贡献者。本项目的流媒体转发、网页播放器，以及播放列表和节目单的 HTTP 服务，基于 rtp2httpd 提供的能力实现。

IPTV 助手负责平台认证、业务发现、频道与节目单采集及数据整理；rtp2httpd 负责实际播放流量和媒体服务。网页播放器与流媒体转发能力来自 rtp2httpd，并非本项目自行实现。

可根据使用需求前往 [rtp2httpd 项目](https://github.com/stackia/rtp2httpd) 查看功能与安装说明，并从其 [Releases](https://github.com/stackia/rtp2httpd/releases) 选择匹配固件版本、架构和包管理器的安装包。需要独立使用流媒体转发或网页播放器时，也可以直接使用 rtp2httpd。

## 安装与配置

当前发布的 IPTV 助手安装包将 rtp2httpd 声明为必需依赖；使用本插件时需先安装上游提供的匹配版本。助手只依赖其可执行文件，不内置第三方二进制；rtp2httpd 的 LuCI 插件可按需安装，不是本助手的必需依赖。

签名包、公钥和软件源配置见 [安装与发布说明](docs/publishing.md)。配置后运行：

```sh
apk update
apk add luci-app-iptvhelper
```

其余依赖见 `openwrt-iptv/dependencies.txt`。发布软件源不包含 rtp2httpd，需先安装上游包。升级会停止助手任务并恢复原启停状态，可能短暂中断媒体转发；不重启网络接口。

首次安装整体停用。进入 LuCI 的 **IPTV 助手**：

1. 网络：选择已经取得地址的 IPTV 接口，默认 `iptv`；专用路由表默认 `42420`，DNS 默认读取 DHCP 数据，也可覆盖。
2. 平台：填写平台地址、业务账号和密码。IP、MAC、发送主机名来自所选接口，主机名未配置时使用系统主机名。
3. 媒体采集：默认计划为每日 `08:00`；自动更新需启用。过去/未来天数留空分别按 7/3 天处理。
4. 媒体服务：监听留空按 `0.0.0.0:5141` 处理。启用助手后可手动点击“更新”。

端口上的 `/playlist.m3u`、`/epg.xml`、`/player`、`/status` 由 rtp2httpd 提供。实际播放流量由 rtp2httpd 处理，Python 不处理媒体流。助手单独运行 rtp2httpd 实例，不接管官方服务实例或覆盖 `/etc/config/rtp2httpd`。

## 行为与边界

- 平台认证/业务发现与采集/发布分层；仅采集任务触发会话验证，必要时重新登录。
- 每两分钟检查每日时间集合；手动任务立即尝试启动，与定时任务共用锁。重试在单次任务内部完成。
- 频道新结果非空才替换旧频道；节目单按频道和日期存入 SQLite，按检查时间跳过尚未到期记录，空结果不覆盖已有非空节目。
- 发布物从数据库生成；内容不同才原子替换。网络短暂不可用时保留已有媒体数据。
- 专用路由表由策略服务维护，平台连接绑定所选设备，避免改变普通上网默认路由。是否与其他网络插件兼容仍取决于实际规则。
- 第一次完整 EPG 采集为串行请求，可能耗时数十分钟；当前未做并发优化。
- 平台认证目前支持已验证的六位数字密码格式与 HTTP 平台地址；不是 TLS 平台适配器。

## 存储与服务

| 用途 | 位置 |
| --- | --- |
| 用户配置 | `/etc/config/iptvhelper` |
| SQLite 与媒体数据 | `/etc/iptvhelper-data/` |
| 临时会话/运行状态 | `/var/lib/iptvhelper-app/` |
| 服务 | `iptvhelper-app`、`iptvhelper-policy`、`iptvhelper-relay` |

配置和会话包含敏感信息，不要上传到问题报告。媒体端口的公开范围由部署者的防火墙/反向代理控制。

## 本地测试与构建

开发机安装 Python 3、Node.js，执行：

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover -s openwrt-iptv/tests
python -m unittest discover -s iptv-client/tests
node openwrt-iptv/tests/readiness-render-check.cjs
python openwrt-iptv/build.py --archive
```

生成的 `openwrt-iptv/build/root.tar.gz` 已包含客户端模块。Linux/OpenWrt 构建环境中，使用支持 `mkpkg` 的 APK 工具：

```sh
APK_MKPKG=/path/to/apk sh openwrt-iptv/mkpkg.sh openwrt-iptv/build/root.tar.gz
```

输出 `/tmp/luci-app-iptvhelper-0.4.1-r1.apk`。也提供 SDK Makefile：先生成 `build/root`，再将完整 `openwrt-iptv` 包目录放入 SDK 并编译。SDK 路径尚需独立构建验收。

测试不能替代 OpenWrt 上的锁、服务生命周期、真实认证、播放和重启验收。Windows 测试对部分 Linux 能力使用模拟。

## 发布说明

本仓库从已部署源码整理，移除了真实配置、抓包、固件、部署截图和机器专用维护脚本，不导入研究历史。首次整理不修改运行逻辑。MIT 许可证见 LICENSE；第三方依赖仍遵循各自许可证，详见 THIRD_PARTY.md。
