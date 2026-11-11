#!/bin/sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
agent_dir="$HOME/Library/LaunchAgents"
log_dir="$HOME/Library/Logs/Mayfly Publish"
plist="$agent_dir/com.mayfly-publish.cleanup.plist"
mkdir -p "$agent_dir" "$log_dir"
cat > "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.mayfly-publish.cleanup</string>
<key>ProgramArguments</key><array>
  <string>$project_dir/.venv/bin/mayfly-publish</string>
  <string>cleanup</string>
</array>
<key>WorkingDirectory</key><string>$project_dir</string>
<key>StartInterval</key><integer>3600</integer>
<key>RunAtLoad</key><true/>
<key>StandardErrorPath</key><string>$log_dir/cleanup.stderr.log</string>
<key>StandardOutPath</key><string>$log_dir/cleanup.stdout.log</string>
</dict></plist>
EOF
chmod 600 "$plist"
launchctl bootout "gui/$(id -u)" "$plist" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$plist"
printf 'Installed %s\n' "$plist"
