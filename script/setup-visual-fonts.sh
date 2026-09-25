#!/usr/bin/env bash
# Install the exact Noto CJK files used when the approved Chromium baselines were captured.
set -euo pipefail

visual_font_root="${MIGU_VISUAL_FONT_ROOT:?set MIGU_VISUAL_FONT_ROOT to an isolated directory}"
visual_font_dir="$visual_font_root/data/fonts/noto-cjk"
visual_font_config_dir="$visual_font_root/config/fontconfig/conf.d"
export XDG_CONFIG_HOME="$visual_font_root/config"
export XDG_DATA_HOME="$visual_font_root/data"
visual_font_package_url="https://archive.ubuntu.com/ubuntu/pool/main/f/fonts-noto-cjk/fonts-noto-cjk_20220127+repack1-1_all.deb"
visual_font_package_sha="e804b3474a79bd70d5f03f590e2d06dbc5ce17f48be7cfaf6c48086471edd5be"
visual_font_regular_sha="b76b0433203017ca80401b2ee0dd69350349871c4b19d504c34dbdd80541690a"
visual_font_temp_dir="$(mktemp -d)"
trap 'rm -rf "$visual_font_temp_dir"' EXIT

curl --fail --location --connect-timeout 10 --max-time 120 --retry 2 --retry-max-time 180 \
  --silent --show-error \
  "$visual_font_package_url" --output "$visual_font_temp_dir/fonts-noto-cjk.deb"
printf '%s  %s\n' "$visual_font_package_sha" "$visual_font_temp_dir/fonts-noto-cjk.deb" | sha256sum --check --status
dpkg-deb --extract "$visual_font_temp_dir/fonts-noto-cjk.deb" "$visual_font_temp_dir/extracted"

visual_font_source="$visual_font_temp_dir/extracted/usr/share/fonts/opentype/noto"
mkdir -p "$visual_font_dir" "$visual_font_config_dir"
install -m 0644 "$visual_font_source"/*.ttc "$visual_font_dir/"
install -m 0644 "$(dirname "$0")/visual-fontconfig.conf" \
  "$visual_font_config_dir/99-migu-orca-visual.conf"
fc-cache --force "$visual_font_dir" >/dev/null

printf '%s  %s\n' "$visual_font_regular_sha" "$visual_font_dir/NotoSansCJK-Regular.ttc" | sha256sum --check --status
visual_font_match="$(fc-match -f '%{file}' Inter)"
if [[ "$visual_font_match" != "$visual_font_dir/NotoSansCJK-Regular.ttc" ]]; then
  echo "Visual font setup failed: Inter does not resolve to the pinned Noto Sans CJK font." >&2
  exit 1
fi
echo "Pinned visual test font installed and selected."
