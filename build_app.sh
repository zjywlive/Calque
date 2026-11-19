#!/bin/bash
# 生成 ~/Applications/本地翻译.app（双击即可启动界面）
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$HOME/Applications/本地翻译.app"
mkdir -p "$HOME/Applications" "$HOME/Library/Logs"
osacompile -o "$APP" -e "do shell script \"cd \" & quoted form of \"$DIR\" & \" && /usr/bin/nohup /usr/bin/python3 -E app.py --open >> \$HOME/Library/Logs/LocalTranslator.log 2>&1 &\""
echo "已生成 $APP"
