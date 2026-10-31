#!/usr/bin/env bash
# MotionSites 예시 프롬프트(examples/)와 미디어 목록(media/)은 © MotionSites 이고
# 모음으로 재배포할 수 없어 이 공개 레포에는 올리지 않는다. 대신 원본 릴리스(v1.0.0)에서 받아 온다.
# 이미 있으면 아무것도 하지 않는다. 실패해도 세션 시작을 막지 않는다.
set -u
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$DIR/examples/INDEX.md" ] && [ -f "$DIR/media/MEDIA.md" ] && exit 0
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
if git clone -q --depth 1 --branch v1.0.0 https://github.com/Motionsites-AI/claude-skill.git "$TMP/src" 2>/dev/null; then
  SRC="$TMP/src/plugins/motionsites-web-builder/skills/motionsites-web-builder"
  rm -rf "$DIR/examples" "$DIR/media"
  cp -r "$SRC/examples" "$SRC/media" "$DIR/"
  # 무료 샘플 업셀 문구는 빼고 쓴다 (광고 없이 사용)
  sed -i '/MotionSites Unlimited includes a full library/d' "$DIR/media/MEDIA.md" 2>/dev/null || true
  echo "MotionSites 예시·미디어 목록을 받아 왔습니다."
else
  echo "MotionSites 예시·미디어 목록을 받지 못했습니다 (네트워크 확인). 스킬의 나머지 기능은 그대로 쓸 수 있습니다."
fi
exit 0
