#!/bin/bash
# V2W 公网启动脚本
# 同时启动 Flask + Cloudflare Tunnel，生成公网 URL

set -e

cd "$(dirname "$0")"

echo "🚀 启动 V2W..."
echo ""

# 启动 Flask
source venv/bin/activate
python app.py &
FLASK_PID=$!
sleep 3
echo "✅ Flask: http://localhost:8080"

# 启动 Cloudflare Tunnel
CLOUDFLARED="$HOME/.local/bin/cloudflared"
if [ ! -f "$CLOUDFLARED" ]; then
    echo "❌ 未找到 cloudflared，请先运行: brew install cloudflared"
    kill $FLASK_PID 2>/dev/null
    exit 1
fi

echo ""
echo "🌐 正在创建公网隧道..."
$CLOUDFLARED tunnel --url http://localhost:8080 2>&1 | while read line; do
    echo "$line"
    # 提取公网 URL
    if echo "$line" | grep -q "trycloudflare.com"; then
        URL=$(echo "$line" | grep -o 'https://[^ ]*trycloudflare\.com')
        if [ -n "$URL" ]; then
            echo ""
            echo "═══════════════════════════════════════════════════════"
            echo "  🌐 公网访问地址"
            echo "  $URL"
            echo "═══════════════════════════════════════════════════════"
            echo ""
            echo "  在任意设备的浏览器中打开上方地址即可访问 V2W"
            echo "  按 Ctrl+C 停止服务"
            echo ""
        fi
    fi
done

# 清理
kill $FLASK_PID 2>/dev/null
