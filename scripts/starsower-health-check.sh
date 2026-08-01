#!/bin/bash
# 经验传承 自动巡检脚本
# 用法: bash /opt/myapp/health_check.sh
# 安装: systemd timer 每5分钟运行 (starsower-health.timer)
set -e
NOW=$(date '+%Y-%m-%d %H:%M:%S')
LOG=/opt/myapp/logs/health_report.log
mkdir -p "$(dirname "$LOG")"
ERRORS=""

check() {
  local name="$1" result="$2"
  if [ "$result" = "OK" ]; then
    echo "  [+] $name"
  else
    echo "  [x] $name: $result"
    ERRORS="$ERRORS  [x] $name: $result\n"
  fi
}

echo "=== 经验平台巡检 $NOW ===" >> "$LOG"

# 1. 磁盘
DISK=$(df -h / | awk 'NR==2{print $5}' | tr -d '%')
if [ "$DISK" -gt 85 ]; then check "磁盘" "已用${DISK}%"; else check "磁盘" "OK (${DISK}%)"; fi

# 2. Starsower_v2
if curl -sf --max-time 3 http://127.0.0.1:8001/health >/dev/null 2>&1; then
  check "Starsower_v2" "OK"
else
  check "Starsower_v2" "端口不通"
fi

# 3. Dify 登录（密码base64）
DIFY_PWD=$(echo -n "[REDACTED]" | base64 -w0)
DIFY_LOGIN=$(curl -sf --max-time 5 -X POST http://127.0.0.1:8081/console/api/login \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"admin@hdnz.net\",\"password\":\"$DIFY_PWD\"}" 2>/dev/null)
if echo "$DIFY_LOGIN" | grep -q '"result":"success"'; then
  check "Dify 登录" "OK"
else
  check "Dify 登录" "登录失败"
fi

# 4. 知识库数量
TOKEN=$(echo "$DIFY_LOGIN" | python3 -c "import sys,json; print(json.load(sys.stdin).get('data',{}).get('access_token',''))" 2>/dev/null)
if [ -n "$TOKEN" ]; then
  KB=$(curl -sf --max-time 5 "http://127.0.0.1:8081/console/api/datasets?page=1&limit=20" \
    -H "Authorization: Bearer $TOKEN" 2>/dev/null | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('data',[])))" 2>/dev/null)
  check "Dify 知识库" "共 ${KB:-0} 个"
fi

# 5. Docker 容器
DEAD=$(docker ps --format '{{.Status}}' 2>/dev/null | grep -vc 'Up')
check "Docker 容器" "$([ "$DEAD" -eq 0 ] && echo '全部运行中' || echo "${DEAD}个异常")"

# 6. 前端 /gl 页面
CURL_GL=$(curl -sf --max-time 3 http://127.0.0.1:8001/gl >/dev/null 2>&1 && echo OK || echo FAIL)
check "前端页面(/gl)" "$CURL_GL"

# 7. Dashboard API
DASH=$(curl -sf --max-time 3 http://127.0.0.1:8001/api/admin >/dev/null 2>&1 && echo OK || echo FAIL)
check "Dashboard API" "$DASH"

echo "" >> "$LOG"
if [ -z "$ERRORS" ]; then
  echo "全部正常" >> "$LOG"
else
  echo -e "$ERRORS" >> "$LOG"
fi
