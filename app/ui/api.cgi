#!/bin/bash
# api.cgi —— opencode 控制台后端 API
# 用法: /cgi/ThirdParty/com.opencode.web/api.cgi?action=<name>
#   status | start | stop | restart | logs | clear_logs | reset_auth
#   backup_download | upgrade | upgrade_status | upgrade_logs
# 写操作要求 POST。

APP_ID="com.opencode.web"
APP_ROOT="/var/apps/${APP_ID}"
BIN="${APP_ROOT}/target/opencode"
DATA_DIR="${APP_ROOT}/shares/${APP_ID}"
ENV_FILE="${APP_ROOT}/etc/opencode.env"
PID_FILE="${APP_ROOT}/var/opencode.pid"
LOG_FILE="${APP_ROOT}/var/opencode.log"
UPGRADE_LOG_FILE="${APP_ROOT}/var/opencode-upgrade.log"
UPGRADE_PID_FILE="${APP_ROOT}/var/opencode-upgrade.pid"
UPGRADE_LOCK_DIR="${APP_ROOT}/var/opencode-upgrade.lock"
PORT="14096"

mkdir -p "$(dirname "${LOG_FILE}")" 2>/dev/null

check_process() {
    local pid="$1"
    [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null
}

json_header() {
    echo "Content-Type: application/json; charset=utf-8"
    echo "Cache-Control: no-store"
    echo ""
}

json_error() {
    json_header
    printf '{"success":false,"message":"%s"}\n' "$1"
}

require_post() {
    if [ "$REQUEST_METHOD" != "POST" ]; then
        json_error "仅支持 POST 请求"
        return 1
    fi
    return 0
}

load_env() {
    if [ -f "${ENV_FILE}" ]; then
        # shellcheck disable=SC1090
        . "${ENV_FILE}"
    fi
    export OPENCODE_SERVER_PASSWORD="${OPENCODE_SERVER_PASSWORD:-}"
}

backend_cmd() {
    echo "export HOME='${DATA_DIR}'; export XDG_CONFIG_HOME='${DATA_DIR}/.config'; export XDG_DATA_HOME='${DATA_DIR}/.local/share'; export BROWSER=true; export OPENCODE_SERVER_PASSWORD='${OPENCODE_SERVER_PASSWORD}'; cd '${DATA_DIR}' && exec '${BIN}' web --hostname 0.0.0.0 --port ${PORT}"
}

do_start() {
    if [ -f "${PID_FILE}" ]; then
        local pid
        pid="$(head -n 1 "${PID_FILE}" | tr -d '[:space:]')"
        if check_process "${pid}"; then
            json_header
            printf '{"success":true,"message":"opencode 已在运行"}\n'
            return 0
        fi
        rm -f "${PID_FILE}"
    fi
    if [ ! -x "${BIN}" ]; then
        json_error "找不到可执行文件，请重新安装"
        return 0
    fi
    load_env
    mkdir -p "${DATA_DIR}"
    nohup bash -c "$(backend_cmd)" >> "${LOG_FILE}" 2>&1 &
    echo "$!" > "${PID_FILE}"
    sleep 2
    if check_process "$(head -n 1 "${PID_FILE}" | tr -d '[:space:]')"; then
        json_header
        printf '{"success":true,"message":"opencode 启动成功"}\n'
    else
        rm -f "${PID_FILE}"
        json_error "启动失败，请查看日志"
    fi
}

do_stop() {
    if [ -f "${PID_FILE}" ]; then
        local pid
        pid="$(head -n 1 "${PID_FILE}" | tr -d '[:space:]')"
        if check_process "${pid}"; then
            kill -TERM "${pid}" 2>/dev/null
            local n=0
            while check_process "${pid}" && [ "${n}" -lt 20 ]; do
                sleep 0.5
                n=$((n + 1))
            done
            if check_process "${pid}"; then
                kill -KILL "${pid}" 2>/dev/null
            fi
        fi
        rm -f "${PID_FILE}"
    fi
    pkill -f "${BIN} web" 2>/dev/null
    json_header
    printf '{"success":true,"message":"opencode 已停止"}\n'
}

do_status() {
    local running=false pid="" start_at="null" password_set=false
    if [ -f "${PID_FILE}" ]; then
        pid="$(head -n 1 "${PID_FILE}" | tr -d '[:space:]')"
        if check_process "${pid}"; then
            running=true
            start_at="$(stat -c %Y "${PID_FILE}" 2>/dev/null || echo null)"
        else
            rm -f "${PID_FILE}"
            pid=""
        fi
    fi
    [ -f "${ENV_FILE}" ] && grep -q '^OPENCODE_SERVER_PASSWORD=.\+' "${ENV_FILE}" && password_set=true

    json_header
    printf '{"success":true,"running":%s,"pid":"%s","port":%s,"startAt":%s,"passwordSet":%s}\n' \
        "${running}" "${pid}" "${PORT}" "${start_at}" "${password_set}"
}

# 检测可选依赖应用是否已安装（供控制台给出提示）
do_check_deps() {
    local node=false
    if [ -d "/var/apps/nodejs_v24" ]; then
        node=true
    fi
    json_header
    printf '{"success":true,"node":%s}\n' "${node}"
}

do_logs() {
    json_header
    if [ ! -f "${LOG_FILE}" ]; then
        echo '{"success":true,"logs":[]}'
        return
    fi
    printf '{"success":true,"logs":['
    tail -n 300 "${LOG_FILE}" | while IFS= read -r line; do
        line="${line//\\/\\\\}"
        line="${line//\"/\\\"}"
        line="${line//$'\r'/}"
        line="${line//$'\t'/    }"
        printf '"%s",' "$line"
    done | sed 's/,$//'
    printf ']}\n'
}

do_clear_logs() {
    : > "${LOG_FILE}" 2>/dev/null
    : > "${UPGRADE_LOG_FILE}" 2>/dev/null
    json_header
    printf '{"success":true,"message":"日志已清空"}\n'
}

do_reset_auth() {
    local newpass="${QUERY_STRING#*password=}"
    newpass="${newpass%%&*}"
    newpass="$(printf '%b' "${newpass//+/ }" | sed 's/%\([0-9A-Fa-f][0-9A-Fa-f]\)/\\x\1/g')"
    if [ -z "${newpass}" ]; then
        json_error "新密码不能为空"
        return
    fi
    if [ ! -f "${ENV_FILE}" ]; then
        json_error "配置文件不存在"
        return
    fi
    local tmp="${ENV_FILE}.tmp"
    grep -v '^OPENCODE_SERVER_PASSWORD=' "${ENV_FILE}" > "${tmp}"
    printf 'OPENCODE_SERVER_PASSWORD=%s\n' "${newpass}" >> "${tmp}"
    mv "${tmp}" "${ENV_FILE}"
    chmod 600 "${ENV_FILE}" 2>/dev/null
    do_stop > /dev/null
    json_header
    printf '{"success":true,"message":"密码已更新，服务已停止，请手动启动"}\n'
}

do_restart() {
    do_stop > /dev/null
    sleep 1
    do_start
}

arch_target() {
    local arch
    arch="$(uname -m)"
    case "$arch" in
    x86_64 | amd64)
        if grep -qwi avx2 /proc/cpuinfo 2>/dev/null; then
            echo "x64"
        else
            echo "x64-baseline"
        fi
        ;;
    aarch64 | arm64) echo "arm64" ;;
    *) echo "" ;;
    esac
}

do_upgrade() {
    if ! mkdir "${UPGRADE_LOCK_DIR}" 2>/dev/null; then
        json_header
        printf '{"success":false,"message":"升级正在进行中，请稍候"}\n'
        return
    fi

    local target url tmpdir
    target="$(arch_target)"
    if [ -z "${target}" ]; then
        rm -rf "${UPGRADE_LOCK_DIR}"
        json_error "不支持的架构：$(uname -m)"
        return
    fi
    url="https://github.com/anomalyco/opencode/releases/latest/download/opencode-linux-${target}.tar.gz"

    : > "${UPGRADE_LOG_FILE}"
    nohup bash -c "
        set -e
        log() { echo \"[\$(date '+%H:%M:%S')] \$*\" >> '${UPGRADE_LOG_FILE}'; }
        tmp='${APP_ROOT}/var/upgrade.tmp'
        rm -rf \"\$tmp\"; mkdir -p \"\$tmp\"
        log '目标: ${target}'
        log '下载: ${url}'
        if ! curl -fL --retry 3 -o \"\$tmp/pkg.tar.gz\" '${url}'; then
            log '下载失败'; rm -rf \"\$tmp\"; rm -rf '${UPGRADE_LOCK_DIR}'; rm -f '${UPGRADE_PID_FILE}'; exit 1
        fi
        tar -xzf \"\$tmp/pkg.tar.gz\" -C \"\$tmp\"
        if [ ! -f \"\$tmp/opencode\" ]; then
            log '压缩包内未找到 opencode'; rm -rf \"\$tmp\"; rm -rf '${UPGRADE_LOCK_DIR}'; rm -f '${UPGRADE_PID_FILE}'; exit 1
        fi
        chmod 755 \"\$tmp/opencode\"
        if [ -f '${PID_FILE}' ]; then
            old=\$(head -n 1 '${PID_FILE}' | tr -d '[:space:]')
            kill -TERM \"\$old\" 2>/dev/null || true
            n=0; while kill -0 \"\$old\" 2>/dev/null && [ \$n -lt 20 ]; do sleep 0.5; n=\$((n+1)); done
            kill -KILL \"\$old\" 2>/dev/null || true
            rm -f '${PID_FILE}'
        fi
        mv \"\$tmp/opencode\" '${BIN}'
        chmod 755 '${BIN}'
        rm -rf \"\$tmp\"
        log '二进制已更新，正在重启 ...'
        export HOME='${DATA_DIR}'
        export XDG_CONFIG_HOME='${DATA_DIR}/.config'
        export XDG_DATA_HOME='${DATA_DIR}/.local/share'
        export BROWSER=true
        if [ -f '${ENV_FILE}' ]; then . '${ENV_FILE}'; fi
        cd '${DATA_DIR}' && nohup '${BIN}' web --hostname 0.0.0.0 --port ${PORT} >> '${LOG_FILE}' 2>&1 &
        echo \$! > '${PID_FILE}'
        log '升级完成'
        rm -rf '${UPGRADE_LOCK_DIR}'
        rm -f '${UPGRADE_PID_FILE}'
    " >> "${UPGRADE_LOG_FILE}" 2>&1 &
    echo "$!" > "${UPGRADE_PID_FILE}"

    json_header
    printf '{"success":true,"message":"已开始升级，可查看升级日志"}\n'
}

do_upgrade_status() {
    local upgrading=false pid=""
    if [ -f "${UPGRADE_PID_FILE}" ]; then
        pid="$(head -n 1 "${UPGRADE_PID_FILE}" | tr -d '[:space:]')"
        if check_process "${pid}"; then
            upgrading=true
        else
            rm -f "${UPGRADE_PID_FILE}"
        fi
    fi
    json_header
    printf '{"success":true,"upgrading":%s}\n' "${upgrading}"
}

do_upgrade_logs() {
    json_header
    if [ ! -f "${UPGRADE_LOG_FILE}" ]; then
        echo '{"success":true,"logs":[]}'
        return
    fi
    printf '{"success":true,"logs":['
    tail -n 300 "${UPGRADE_LOG_FILE}" | while IFS= read -r line; do
        line="${line//\\/\\\\}"
        line="${line//\"/\\\"}"
        line="${line//$'\r'/}"
        printf '"%s",' "$line"
    done | sed 's/,$//'
    printf ']}\n'
}

do_backup() {
    local base="${APP_ROOT}/shares/${APP_ID}"
    local name="opencode-backup-$(date +%Y%m%d-%H%M%S).tar.gz"
    local tmp="/tmp/${name}"
    if [ ! -d "${base}" ]; then
        json_error "数据目录不存在，无法备份"
        return
    fi
    if ! tar -czf "${tmp}" -C "${base}" . 2>/dev/null; then
        json_error "打包失败，请检查磁盘空间与权限"
        rm -f "${tmp}"
        return
    fi
    echo "Content-Type: application/gzip"
    echo "Content-Disposition: attachment; filename=\"${name}\""
    echo "Cache-Control: no-store"
    echo ""
    cat "${tmp}"
    rm -f "${tmp}"
}

action=""
for src in "${QUERY_STRING}" "${REQUEST_URI}"; do
    [ -n "${action}" ] && break
    [ -z "${src}" ] && continue
    case "$src" in
    *action=status*) action="status" ;;
    *action=start*) action="start" ;;
    *action=stop*) action="stop" ;;
    *action=restart*) action="restart" ;;
    *action=logs*) action="logs" ;;
    *action=clear_logs*) action="clear_logs" ;;
    *action=reset_auth*) action="reset_auth" ;;
    *action=check_deps*) action="check_deps" ;;
    *action=backup_download*) action="backup" ;;
    *action=upgrade_status*) action="upgrade_status" ;;
    *action=upgrade_logs*) action="upgrade_logs" ;;
    *action=upgrade*) action="upgrade" ;;
    esac
done

case "$action" in
status) do_status ;;
start) require_post && do_start ;;
stop) require_post && do_stop ;;
restart) require_post && do_restart ;;
logs) do_logs ;;
clear_logs) require_post && do_clear_logs ;;
reset_auth) require_post && do_reset_auth ;;
    backup) do_backup ;;
    check_deps) do_check_deps ;;
upgrade) require_post && do_upgrade ;;
upgrade_status) do_upgrade_status ;;
upgrade_logs) do_upgrade_logs ;;
*) json_error "无效的操作" ;;
esac
