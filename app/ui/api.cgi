#!/bin/bash
# api.cgi —— opencode 控制台后端 API
# 用法: /cgi/ThirdParty/com.opencode.web/api.cgi?action=<name>
#   status | start | stop | restart | logs | clear_logs | check_deps
#   get_config | save_config | backup_download | upgrade | upgrade_status | upgrade_logs
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
    export OPENCODE_SERVER_USERNAME="${OPENCODE_SERVER_USERNAME:-opencode}"
    export OPENCODE_SERVER_PASSWORD="${OPENCODE_SERVER_PASSWORD:-}"
    export OPENCODE_LOG_LEVEL="${OPENCODE_LOG_LEVEL:-info}"
    OPENCODE_WORKDIR="${OPENCODE_WORKDIR:-}"
}

# 探测二进制支持的工作目录参数（新版 --dir，旧版 --cwd）
web_dir_flag() {
    local help
    help="$("${BIN}" web --help 2>&1)"
    if echo "${help}" | grep -q -- '--dir'; then
        echo "--dir"
    elif echo "${help}" | grep -q -- '--cwd'; then
        echo "--cwd"
    fi
}

resolve_workdir() {
    local wd="${OPENCODE_WORKDIR:-}"
    if [ -z "${wd}" ] || [ ! -d "${wd}" ]; then
        wd="${DATA_DIR}"
    fi
    echo "${wd}"
}

backend_cmd() {
    local wd dirflag dirargs=""
    wd="$(resolve_workdir)"
    dirflag="$(web_dir_flag)"
    if [ -n "${dirflag}" ]; then
        dirargs="${dirflag} '${wd}'"
    fi
    printf "export HOME='%s'; export XDG_CONFIG_HOME='%s/.config'; export XDG_DATA_HOME='%s/.local/share'; export BROWSER=true; export OPENCODE_SERVER_USERNAME='%s'; export OPENCODE_SERVER_PASSWORD='%s'; export OPENCODE_LOG_LEVEL='%s'; cd '%s' && exec '%s' web --hostname 0.0.0.0 --port %s %s" \
        "${DATA_DIR}" "${DATA_DIR}" "${DATA_DIR}" \
        "${OPENCODE_SERVER_USERNAME}" "${OPENCODE_SERVER_PASSWORD}" "${OPENCODE_LOG_LEVEL}" \
        "${wd}" "${BIN}" "${PORT}" "${dirargs}"
}

# 读取 ?key=value 形式的查询参数并做 URL 解码
qp() {
    local key="$1" src="$2" val
    val="$(printf '%s' "${src}" | tr '&' '\n' | grep "^${key}=" | head -n 1 | cut -d= -f2-)"
    val="${val//+/ }"
    val="$(printf '%s' "${val}" | sed 's/%\([0-9A-Fa-f][0-9A-Fa-f]\)/\\x\1/g')"
    printf '%b' "${val}"
}

write_env() {
    local user="$1" pass="$2" level="$3" wdir="$4"
    umask 022
    {
        echo "# opencode 运行时配置（由控制台生成）"
        printf 'OPENCODE_SERVER_USERNAME=%s\n' "${user}"
        printf 'OPENCODE_SERVER_PASSWORD=%s\n' "${pass}"
        printf 'OPENCODE_LOG_LEVEL=%s\n' "${level}"
        printf 'OPENCODE_WORKDIR=%s\n' "${wdir}"
    } > "${ENV_FILE}"
    chmod 600 "${ENV_FILE}" 2>/dev/null
}

# 静默启动：不输出 JSON，仅返回状态码（0 成功 / 2 无二进制 / 1 启动失败）
_start() {
    if [ -f "${PID_FILE}" ]; then
        local pid
        pid="$(head -n 1 "${PID_FILE}" | tr -d '[:space:]')"
        check_process "${pid}" && return 0
        rm -f "${PID_FILE}"
    fi
    [ -x "${BIN}" ] || return 2
    load_env
    mkdir -p "${DATA_DIR}"
    nohup bash -c "$(backend_cmd)" >> "${LOG_FILE}" 2>&1 &
    echo "$!" > "${PID_FILE}"
    sleep 2
    local np
    np="$(head -n 1 "${PID_FILE}" | tr -d '[:space:]')"
    if check_process "${np}"; then
        return 0
    fi
    rm -f "${PID_FILE}"
    return 1
}

do_start() {
    local rc
    _start
    rc=$?
    case "${rc}" in
    0) json_header; printf '{"success":true,"message":"opencode 已启动"}\n' ;;
    2) json_error "找不到可执行文件，请重新安装" ;;
    *) json_error "启动失败，请查看日志" ;;
    esac
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

do_get_config() {
    load_env
    local shares=""
    local shares_file="${APP_ROOT}/var/shares.list"
    if [ -f "${shares_file}" ]; then
        shares="$(tr '\n' ':' < "${shares_file}" | sed 's/:$//')"
    fi
    [ -n "${shares}" ] || shares="${DATA_DIR}"
    local auth_enabled=false
    if [ -n "${OPENCODE_SERVER_PASSWORD}" ]; then
        auth_enabled=true
    fi
    json_header
    printf '{"success":true,"username":"%s","passwordSet":%s,"logLevel":"%s","workdir":"%s","defaultWorkdir":"%s","shares":"%s","port":%s}\n' \
        "${OPENCODE_SERVER_USERNAME}" "${auth_enabled}" "${OPENCODE_LOG_LEVEL}" \
        "${OPENCODE_WORKDIR}" "${DATA_DIR}" "${shares}" "${PORT}"
}

do_save_config() {
    load_env
    local src="${QUERY_STRING}&${REQUEST_URI}"
    local user pass level wdir
    user="$(qp username "${src}")"
    pass="$(qp password "${src}")"
    level="$(qp log_level "${src}")"
    wdir="$(qp workdir "${src}")"

    [ -n "${user}" ] || user="${OPENCODE_SERVER_USERNAME:-opencode}"
    [ -n "${level}" ] || level="${OPENCODE_LOG_LEVEL:-info}"
    if [ -z "${pass}" ]; then
        pass="${OPENCODE_SERVER_PASSWORD}"
    fi

    local warn=""
    if [ -n "${wdir}" ]; then
        if [ ! -d "${wdir}" ]; then
            json_error "工作目录不存在：${wdir}（请先在应用设置里授权该目录）"
            return
        fi
        if [ ! -w "${wdir}" ]; then
            warn="（注意：工作目录可能无写权限，opencode 或无法修改文件）"
        fi
    fi
    if ! echo "${user}" | grep -qE '^[a-zA-Z0-9_.-]+$'; then
        json_error "用户名只能包含字母、数字、下划线、点和连字符"
        return
    fi

    write_env "${user}" "${pass}" "${level}" "${wdir}"

    # 保存后立即重启，避免应用长时间处于停止状态（会被 app-center 判为异常退出）
    do_stop > /dev/null
    sleep 1
    local rc
    _start
    rc=$?
    json_header
    if [ "${rc}" -eq 0 ]; then
        printf '{"success":true,"message":"设置已保存，服务已重启%s"}\n' "${warn}"
    else
        printf '{"success":false,"message":"设置已保存，但服务启动失败，请查看日志"}\n'
    fi
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
    *action=get_config*) action="get_config" ;;
    *action=save_config*) action="save_config" ;;
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
    get_config) do_get_config ;;
    save_config) require_post && do_save_config ;;
    backup) do_backup ;;
    check_deps) do_check_deps ;;
upgrade) require_post && do_upgrade ;;
upgrade_status) do_upgrade_status ;;
upgrade_logs) do_upgrade_logs ;;
*) json_error "无效的操作" ;;
esac
