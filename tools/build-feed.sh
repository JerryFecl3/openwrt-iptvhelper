#!/bin/sh
set -eu
umask 022
cd "$(dirname "$0")/.."
: "${SIGNING_KEY:?Set SIGNING_KEY to the private PEM file}"
mkdir -p build/apk dist/openwrt-25.12/x86_64
curl -fsSL --retry 3 https://dl-cdn.alpinelinux.org/alpine/edge/main/x86_64/apk-tools-static-3.0.8-r0.apk -o build/apk-tools.apk
echo '673f1bfb22136fc42ca035321cf731a4ad0452c000928666cb39a138f0c277bf  build/apk-tools.apk' | sha256sum -c -
tar -xzf build/apk-tools.apk -C build/apk sbin/apk.static
python3 openwrt-iptv/build.py --archive
apk="$PWD/build/apk/sbin/apk.static"
out="$PWD/dist/openwrt-25.12/x86_64"
# Extract/build as root solely inside the packaging script's temporary root,
# preserving the archive's root ownership. No package hooks are executed.
sudo env APK_MKPKG="$apk" APK_OUTPUT="$out/luci-app-iptvhelper-0.4.1-r1.apk" sh openwrt-iptv/mkpkg.sh "$PWD/openwrt-iptv/build/root.tar.gz"
sudo chown "$(id -u):$(id -g)" "$out/luci-app-iptvhelper-0.4.1-r1.apk"
openssl pkey -in "$SIGNING_KEY" -pubout -out build/derived-public.pem
cmp keys/iptvhelper-public.pem build/derived-public.pem
for package in "$out"/*.apk; do
    "$apk" --allow-untrusted adbsign --sign-key "$SIGNING_KEY" "$package"
    "$apk" --keys-dir "$PWD/keys" verify "$package"
done
"$apk" --keys-dir "$PWD/keys" mkndx --sign-key "$SIGNING_KEY" --description 'IPTV Helper for OpenWrt 25.12' --pkgname-spec '${name}-${version}.apk' --output "$out/Packages.adb" "$out"/*.apk
"$apk" --keys-dir "$PWD/keys" verify "$out/Packages.adb"
mkdir -p build/no-keys
if "$apk" --keys-dir "$PWD/build/no-keys" verify "$out/Packages.adb"; then exit 1; fi
cp keys/iptvhelper-public.pem "$out/"
cp docs/feed.html dist/index.html
touch dist/.nojekyll
(cd "$out" && sha256sum *.apk Packages.adb iptvhelper-public.pem > SHA256SUMS)
