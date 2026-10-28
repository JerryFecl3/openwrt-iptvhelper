#!/bin/sh
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
input=${1:-/tmp/iptvhelper-root.tar.gz}
apk=${APK_MKPKG:-/tmp/iptvhelper-apk.static}
[ -f "$input" ] && [ -f "$here/dependencies.txt" ]
for hook in post-install post-upgrade pre-upgrade pre-deinstall; do [ -f "$here/hooks/$hook" ]; done
work=$(mktemp -d /tmp/iptvhelper-build.XXXXXX)
trap 'rm -rf "$work"' EXIT
mkdir "$work/root"
tar xzf "$input" -C "$work/root"
meta="$work/root/lib/apk/packages"
mkdir -p "$meta"
printf '/etc/config/iptvhelper\n' > "$meta/luci-app-iptvhelper.conffiles"
checksum=$(sha256sum "$work/root/etc/config/iptvhelper" | cut -d ' ' -f 1)
printf '/etc/config/iptvhelper %s\n' "$checksum" > "$meta/luci-app-iptvhelper.conffiles_static"
(cd "$work/root" && find . -type f | sed 's,^\.,,' ) > "$meta/luci-app-iptvhelper.list"
"$apk" mkpkg --compat 3.0.0 --files "$work/root" \
 --info name:luci-app-iptvhelper --info version:0.4.0-r6 --info arch:noarch \
 --info license:MIT --info 'description:LuCI Liaoning IPTV platform and XMLTV publisher' \
 --info "depends:$(cat "$here/dependencies.txt")" \
 --script "post-install:$here/hooks/post-install" --script "post-upgrade:$here/hooks/post-upgrade" \
 --script "pre-upgrade:$here/hooks/pre-upgrade" --script "pre-deinstall:$here/hooks/pre-deinstall" \
 --output /tmp/luci-app-iptvhelper-0.4.0-r6.apk
