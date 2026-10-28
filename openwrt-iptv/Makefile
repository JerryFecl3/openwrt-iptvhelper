include $(TOPDIR)/rules.mk
PKG_NAME:=luci-app-iptvhelper
PKG_VERSION:=0.4.0
PKG_RELEASE:=6
PKG_LICENSE:=MIT
PKGARCH:=all
include $(INCLUDE_DIR)/package.mk
define Package/luci-app-iptvhelper
  SECTION:=luci
  CATEGORY:=LuCI
  SUBMENU:=3. Applications
  TITLE:=Liaoning IPTV platform and publisher
  DEPENDS:=+luci-base +rpcd +uhttpd +python3-light +python3-openssl +python3-codecs +python3-sqlite3 +python3-urllib +python3-xml +openssl-util +ip-full +rtp2httpd
endef
define Package/luci-app-iptvhelper/conffiles
/etc/config/iptvhelper
endef
define Build/Compile
endef
# Run build.py first; it vendors the existing tested client into build/root.
define Package/luci-app-iptvhelper/install
    $(CP) ./build/root/* $(1)/
    chmod 755 $(1)/etc/init.d/iptvhelper-relay $(1)/etc/init.d/iptvhelper-app $(1)/etc/init.d/iptvhelper-policy $(1)/etc/hotplug.d/iface/97-iptvhelper-policy $(1)/usr/libexec/rpcd/iptvhelper
    chmod 600 $(1)/etc/config/iptvhelper
    find $(1)/usr/lib/iptvhelper-app -type f -name '*.py' -exec chmod 644 {} \;
    chmod 644 $(1)/lib/upgrade/keep.d/iptvhelper
endef
define Package/luci-app-iptvhelper/postinst
#!/bin/sh
[ -n "$$IPKG_INSTROOT" ] && exit 0
exec /usr/bin/python3 /usr/lib/iptvhelper-app/lifecycle.py install
endef

define Package/luci-app-iptvhelper/prerm
#!/bin/sh
[ -n "$$IPKG_INSTROOT" ] && exit 0
if [ "$$PKG_UPGRADE" = 1 ] || [ "$$1" = upgrade ]; then
    exec /usr/bin/python3 /usr/lib/iptvhelper-app/lifecycle.py upgrade
fi
exec /usr/bin/python3 /usr/lib/iptvhelper-app/lifecycle.py remove
endef

$(eval $(call BuildPackage,luci-app-iptvhelper))
