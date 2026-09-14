#!/bin/bash
# index.cgi —— 控制台静态文件服务器
# 访问路径: /cgi/ThirdParty/com.opencode.web/index.cgi/<path>
# 实际文件: app/www/<path>

APP_ID="com.opencode.web"
BASE_PATH="/var/apps/${APP_ID}/target/www"

URI_NO_QUERY="${REQUEST_URI%%\?*}"
REL_PATH="/"

case "$URI_NO_QUERY" in
*index.cgi*)
    REL_PATH="${URI_NO_QUERY#*index.cgi}"
    ;;
esac

if [ -z "$REL_PATH" ] || [ "$REL_PATH" = "/" ]; then
    REL_PATH="/index.html"
fi

TARGET_FILE="${BASE_PATH}${REL_PATH}"

# 禁止 .. 越级访问
if echo "$TARGET_FILE" | grep -q '\.\.'; then
    echo "Status: 400 Bad Request"
    echo "Content-Type: text/plain; charset=utf-8"
    echo ""
    echo "Bad Request"
    exit 0
fi

if [ ! -f "$TARGET_FILE" ]; then
    echo "Status: 404 Not Found"
    echo "Content-Type: text/plain; charset=utf-8"
    echo ""
    echo "404 Not Found: ${REL_PATH}"
    exit 0
fi

ext="${TARGET_FILE##*.}"
case "$ext" in
html | htm) mime="text/html; charset=utf-8" ;;
css) mime="text/css; charset=utf-8" ;;
js) mime="application/javascript; charset=utf-8" ;;
json) mime="application/json; charset=utf-8" ;;
jpg | jpeg) mime="image/jpeg" ;;
png) mime="image/png" ;;
gif) mime="image/gif" ;;
svg) mime="image/svg+xml" ;;
ico) mime="image/x-icon" ;;
txt | log) mime="text/plain; charset=utf-8" ;;
*) mime="application/octet-stream" ;;
esac

echo "Content-Type: $mime"
echo "Cache-Control: no-store"
echo ""

cat "$TARGET_FILE"
