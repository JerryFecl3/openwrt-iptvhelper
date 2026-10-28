# 开发与构建

[返回项目首页](../README.md)

## 源码结构

```text
openwrt-iptv/   OpenWrt 服务、LuCI、配置、打包与测试
iptv-client/    平台认证、业务发现、频道和 EPG 解析组件及测试
```

两部分源码均在本仓库中，不需要原始研究工作区或机顶盒备份。

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

