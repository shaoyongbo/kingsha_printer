#!/usr/bin/env bash
# RICOH IPP 打印门户 一键启动脚本
set -euo pipefail

cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "错误：未找到 $PY，请先安装 Python 3.9 或以上版本。" >&2
  exit 1
fi

if ! "$PY" -c "import flask, PIL, pypdf" >/dev/null 2>&1; then
  echo "首次运行，正在安装依赖：flask pillow pypdf ..."
  "$PY" -m pip install --user flask pillow pypdf
fi

PORT="${PORT:-8090}"
HOST_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
HOST_IP="${HOST_IP:-127.0.0.1}"

echo "打印门户已启动：http://${HOST_IP}:${PORT}/"
echo "打印机：${PRINTER_HOST:-172.166.162.20}:${PRINTER_PORT:-631}${PRINTER_PATH:-/ipp/print}"
echo "按 Ctrl+C 停止。"
echo

exec "$PY" app.py
