#!/bin/bash
# 双击启动本地翻译（打开浏览器界面）
cd "$(dirname "$0")"
exec /usr/bin/python3 -E app.py --open
