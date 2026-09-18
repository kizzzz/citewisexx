#!/usr/bin/env bash
# DNS 生效守望：解析出来之后自动确认 Caddy 的证书是否签发成功。
#
# Caddy 本身会持续重试 ACME，这个脚本不做任何签发动作，只做可观测：
# 每 60s 探一次，解析成功后再探 HTTPS，最终把结论写进日志，避免人肉盯着。
#
# 用法：nohup bash deploy/wait-dns-then-tls.sh > /dev/null 2>&1 &
# 日志：/var/log/citewise-tls.log
set -uo pipefail

DOMAIN="${DOMAIN:-xx27.xyz}"
EXPECT_IP="${EXPECT_IP:-43.134.136.29}"
LOG="${LOG:-/var/log/citewise-tls.log}"
MAX_MINUTES="${MAX_MINUTES:-180}"

log() { echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] $*" | sudo tee -a "$LOG" > /dev/null; }

log "开始守望 ${DOMAIN} → ${EXPECT_IP}（最长 ${MAX_MINUTES} 分钟）"

for ((i = 0; i < MAX_MINUTES; i++)); do
  ip="$(getent hosts "$DOMAIN" | awk '{print $1; exit}')"

  if [[ -n "$ip" ]]; then
    log "解析已生效：${DOMAIN} -> ${ip}"

    if [[ "$ip" != "$EXPECT_IP" ]]; then
      log "警告：解析值与预期不一致（预期 ${EXPECT_IP}），证书签发会失败，请检查 DNS 记录"
    fi

    # 给 Caddy 留出 ACME 时间，最多再等 5 分钟
    for ((j = 0; j < 10; j++)); do
      code="$(curl -s -o /dev/null -m 20 -w '%{http_code}' "https://${DOMAIN}/")"
      if [[ "$code" == "200" ]]; then
        log "HTTPS 就绪：https://${DOMAIN}/ -> 200，证书签发完成"
        exit 0
      fi
      log "HTTPS 尚未就绪（HTTP ${code}），30s 后重试"
      sleep 30
    done

    log "解析已生效但 HTTPS 仍未就绪，请查看：docker logs smart-scheduler-web-1 | grep -i acme"
    exit 1
  fi

  sleep 60
done

log "超时：${MAX_MINUTES} 分钟内未检测到 ${DOMAIN} 的解析记录，请确认 DNSPod A 记录已添加"
exit 1
