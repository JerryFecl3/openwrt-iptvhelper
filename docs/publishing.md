# 安装与发布

面向已验证的 OpenWrt 25.12 / x86_64 环境。助手本身为 noarch，其他架构尚未实测。

## 先准备 rtp2httpd

本软件源只提供 `luci-app-iptvhelper`，不重新分发或签名 rtp2httpd。请从 [上游 Releases](https://github.com/stackia/rtp2httpd/releases) 安装匹配架构的官方包，参考 [官方安装文档](https://rtp2httpd.com/guide/installation)。此前实测版本为 3.17.2。无需安装它的 LuCI 插件；助手使用独立实例，不覆盖其 UCI 配置。

其余依赖从 OpenWrt 官方软件源解析。DHCP+ 不是本插件的硬依赖，所选 IPTV 接口可使用任何已经可用的接入协议。

## 配置信任与软件源

以下公开地址在发布完成后才生效。核对公钥文件 SHA256 后再导入：

```sh
base='https://jerryfecl3.github.io/openwrt-iptvhelper/openwrt-25.12/x86_64'
wget -O /tmp/iptvhelper-public.pem "$base/iptvhelper-public.pem" &&
echo 'e61566add2ae7732f93edb1b79a01ae347854a3c2aa3cd73371a26ed2de67efe  /tmp/iptvhelper-public.pem' | sha256sum -c - &&
mkdir -p /etc/apk/keys /etc/apk/repositories.d &&
cp /tmp/iptvhelper-public.pem /etc/apk/keys/iptvhelper-public.pem &&
printf '%s\n' "$base/Packages.adb" > /etc/apk/repositories.d/iptvhelper.list
apk update
apk add luci-app-iptvhelper
```

正常安装不需要 `--allow-untrusted`。若先前通过本地 APK 安装产生哈希锁定，先模拟，再按包名升级解除锁定：

```sh
apk add --simulate --upgrade luci-app-iptvhelper
apk add --upgrade luci-app-iptvhelper
```

之后可用 `apk upgrade luci-app-iptvhelper` 更新。首次安装默认停用，需要填写平台配置后主动启用。升级会停止助手任务，并恢复原启停状态，可能短暂中断该助手的媒体转发；不会重启网络接口、WAN 或 Nikki。

## 发布流程

- Actions Secret `APK_SIGNING_KEY` 存放专用私钥，`keys/iptvhelper-public.pem` 为公钥。私钥不得进入源码或构建产物。
- 私有准备阶段：手动运行 Signed APK release，保持 publish 未勾选。执行测试、构建、签名和验签，仅上传私有 Actions artifact，不创建 Release 或部署 Pages。
- 准备就绪后公开仓库，将 Pages 设置为 GitHub Actions，再勾选 publish 运行，或推送与 VERSION 一致的版本标签。
- 修改版本时同步 VERSION、Makefile、mkpkg.sh、build-feed.sh 和发布说明。每个版本使用唯一标签，不覆盖已经发布的包。
- 发布流程对运行时行为不作变更；离线测试不能代替实际线路认证、播放与升级验收。

公开仓库仅保留源码、合成测试和文档，不上传现场配置、抓包、机顶盒 APK、数据库或会话。
