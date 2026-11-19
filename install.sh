#!/usr/bin/env bash
# LinkTool 插件安装脚本（Linux / macOS）。
# 与 install.ps1 等价：校验前置依赖 → 安装锁定的 Node 依赖 → 安装到指定 profile。
# 用法：./install.sh [profile]        （默认 profile 为 web）
set -euo pipefail

PROFILE="${1:-web}"
PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

fail() { echo "错误：$*" >&2; exit 1; }

for cmd in node npm tar; do
  command -v "$cmd" >/dev/null 2>&1 || fail "缺少依赖：$cmd（见 README.md 的安装说明）"
done
# uv 管理 MCP server 自己的 Python 环境；缺失时 MCP 启动会失败。
command -v uv >/dev/null 2>&1 || fail "缺少依赖：uv（见 README.md 的安装说明：https://docs.astral.sh/uv/getting-started/installation/）"

NODE_MAJOR="$(node -p 'parseInt(process.versions.node)')"
[ "$NODE_MAJOR" -ge 22 ] || fail "需要 Node.js 22 或更高版本（当前 $NODE_MAJOR）"

cd "$PLUGIN_DIR"
echo "==> 安装 Node 依赖（npm ci）"
npm ci

echo "==> 安装插件到 profile: $PROFILE"
node scripts/install.mjs "$PROFILE"

cat <<'EOF'

安装完成。请使用 DSH >=0.2.1-rc.5 启动，例如：
  npx @deepseek-ai/dsh@latest --profile web
EOF
