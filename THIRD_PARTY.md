# 第三方组件

- OpenWrt / LuCI / netifd / rpcd / uhttpd：运行平台与集成接口，未随本仓库分发其完整源码或二进制。
- rtp2httpd：外部 APK 依赖，负责 UDP/RTSP 转发和网页播放器；不内置其二进制，不以本项目 MIT 许可证重新许可。
- Python、OpenSSL、iproute2：运行时依赖，由固件包管理器提供。
- PyCryptodome：开发测试可选密码实现，`requirements-dev.txt` 声明依赖；路由器可使用 OpenSSL 后端，未内置第三方 Python 库。

`iptv-client` 是本项目的平台协议实现，不包含提取的 Android APK、固件或厂商库。协议字段及适配器路径描述已验证的行为，不表示厂家授权或全国兼容。
