# 整理验收（2026-10-28）

此次以 0.4.0-r6 已部署源码为基线，仅整理目录、文档、测试引用和示例数据，未修改生产路由器。

- 在独立 Python 虚拟环境安装 requirements-dev.txt 后，99 项助手测试、22 项客户端测试通过。
- LuCI 渲染检查通过：网络就绪、停用、网络未就绪，以及各媒体服务组合。
- build.py --archive 成功生成包含客户端模块的归档；没有使用研究目录中的源码或私有配置。
- 原有测试对废弃兼容模块 router_network 的引用改为实际使用的 network_dns。
- 测试中的现场 MAC 与管理 IP 改为合成示例值。
- 未重新构建 APK，未在本次整理中执行 SDK 编译、真实播放或重启测试。

Windows 上的单元测试不覆盖真实 Linux flock、procd、netifd、nftables 行为。新固件/架构需补充运行验收。
# 签名发行验收（2026-10-28）

- v0.4.1 / luci-app-iptvhelper 0.4.1-r1，包架构 noarch；已验证部署目标仍为 OpenWrt 25.12 / x86_64。
- 私有准备阶段先通过 Linux 99 项助手测试、22 项平台客户端测试、三种 LuCI 状态渲染、APK 与索引验签，随后才公开发布。
- 正式签名发布和 Pages 部署成功，公开软件源通过 APK 按包名 fetch 以及验签；无公钥时正确拒绝索引。
- [私有准备阶段构建记录](https://github.com/JerryFecl3/openwrt-iptvhelper/actions/runs/40653349812)
- [正式发布记录](https://github.com/JerryFecl3/openwrt-iptvhelper/actions/runs/40653728174)
- [公开软件源验收](https://github.com/JerryFecl3/openwrt-iptvhelper/actions/runs/40653837980)
- 未在路由器安装或重启任何服务；此次是构建、签名和分发验证，不代表新增实际线路/播放/升级验收。

