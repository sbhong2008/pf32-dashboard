#!/bin/bash
# 매일 07:00(로컬) update.py 자동 실행 — launchd 등록. 해제: ./install_daily.sh remove
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
PL="$HOME/Library/LaunchAgents/com.pf32.update.plist"
if [ "$1" = "remove" ]; then launchctl unload "$PL" 2>/dev/null || true; rm -f "$PL"; echo "removed"; exit 0; fi
cat > "$PL" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.pf32.update</string>
  <key>ProgramArguments</key><array><string>$(command -v python3)</string><string>-I</string><string>$DIR/update.py</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>7</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>$DIR/data/update.log</string>
  <key>StandardErrorPath</key><string>$DIR/data/update.log</string>
</dict></plist>
EOF
launchctl unload "$PL" 2>/dev/null || true
launchctl load "$PL"
echo "등록 완료: 매일 07:00 자동 업데이트 ($PL)"
