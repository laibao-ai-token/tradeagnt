#!/usr/bin/env bash
# tradecat 统一启动脚本
# 用法: ./scripts/start.sh {start|stop|status|restart|daemon|daemon-stop|start-collector|status-collector|run|run-dev|run-equity}

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB_URL_HELPER="$ROOT/scripts/lib/db_url.sh"
if [[ -f "$DB_URL_HELPER" ]]; then
    # shellcheck disable=SC1090
    source "$DB_URL_HELPER"
fi

# 核心服务（与 init.sh 保持一致）
SERVICES=(collector-service signal-service trading-service)
COLLECTOR_SERVICE_DIR="$ROOT/services/collector-service"
COLLECTOR_PID="$ROOT/run/collector-service.pid"
COLLECTOR_LOG="$ROOT/logs/collector-service.log"

# 守护进程配置
DAEMON_PID="$ROOT/run/daemon.pid"
DAEMON_LOG="$ROOT/logs/daemon.log"
MAX_RESTART_ATTEMPTS=5          # 每个服务最大连续重启次数
RESTART_WINDOW=300              # 重启计数重置窗口（秒）
BASE_BACKOFF=10                 # 基础退避时间（秒）
MAX_BACKOFF=300                 # 最大退避时间（秒）
CHECK_INTERVAL=30               # 检查间隔（秒）

# ==================== 工具函数 ====================
mkdir -p "$ROOT/run" "$ROOT/logs"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$DAEMON_LOG"
}

warn_deprecated_alias() {
    local alias_name="$1"
    local canonical_name="$2"
    echo "⚠ 兼容别名 '$alias_name' 已废弃，建议改用 '$canonical_name'" >&2
}

collector_python() {
    local service_dir="$COLLECTOR_SERVICE_DIR"
    local venv_python="$service_dir/.venv/bin/python"
    if [[ -x "$venv_python" ]]; then
        echo "$venv_python"
        return 0
    fi
    if command -v python3 >/dev/null 2>&1; then
        command -v python3
        return 0
    fi
    return 1
}

collector_has_explicit_enable_flags() {
    local keys=(
        COLLECTOR_CRYPTO_KLINE_ENABLED
        COLLECTOR_CRYPTO_METRICS_ENABLED
        COLLECTOR_CRYPTO_ORDERBOOK_ENABLED
        COLLECTOR_EQUITY_ENABLED
        COLLECTOR_FUND_CN_ENABLED
        COLLECTOR_NEWS_ENABLED
    )
    local key=""
    for key in "${keys[@]}"; do
        if [[ -n "${!key:-}" ]]; then
            return 0
        fi
    done
    return 1
}

prepare_collector_runtime_env() {
    if collector_has_explicit_enable_flags; then
        return 0
    fi

    # 默认沿用旧 core 链路口径：collector-service 先承接 crypto 采集。
    export COLLECTOR_CRYPTO_KLINE_ENABLED=1
    export COLLECTOR_CRYPTO_METRICS_ENABLED=1
}

collector_on_demand_cli() {
    local python_bin=""
    if ! python_bin="$(collector_python)"; then
        echo "✗ 未找到可用的 Python 解释器" >&2
        return 1
    fi
    "$python_bin" "$ROOT/scripts/lib/collector_on_demand.py" "$@"
}

run_collector_cli() {
    if [[ ! -d "$COLLECTOR_SERVICE_DIR" ]]; then
        collector_on_demand_cli "$@"
        return $?
    fi

    local python_bin=""
    if ! python_bin="$(collector_python)"; then
        echo "✗ 未找到可用的 Python 解释器用于 collector-service" >&2
        return 1
    fi

    (
        cd "$COLLECTOR_SERVICE_DIR"
        prepare_collector_runtime_env
        PYTHONPATH="../../libs${PYTHONPATH:+:$PYTHONPATH}" "$python_bin" -m src "$@"
    )
}

start_collector() {
    run_collector_cli --run "$@"
}

status_collector() {
    run_collector_cli "$@"
}

collector_service_is_running() {
    if [[ ! -f "$COLLECTOR_PID" ]]; then
        return 1
    fi

    local pid=""
    pid="$(cat "$COLLECTOR_PID" 2>/dev/null || true)"
    if [[ -z "$pid" ]]; then
        return 1
    fi

    if kill -0 "$pid" 2>/dev/null; then
        return 0
    fi

    rm -f "$COLLECTOR_PID"
    return 1
}

collector_service_start() {
    if [[ ! -d "$COLLECTOR_SERVICE_DIR" ]]; then
        echo "collector-service: on-demand 模式（无常驻采集，见 docs/pipeline/DATA_COLLECTION.md）"
        collector_on_demand_cli --run >/dev/null
        return 0
    fi

    mkdir -p "$(dirname "$COLLECTOR_PID")" "$(dirname "$COLLECTOR_LOG")"

    if collector_service_is_running; then
        echo "collector-service 已运行 (PID: $(cat "$COLLECTOR_PID"))"
        return 0
    fi

    rm -f "$COLLECTOR_PID"

    (
        run_collector_cli --run
    ) >>"$COLLECTOR_LOG" 2>&1 &
    local pid=$!
    echo "$pid" > "$COLLECTOR_PID"

    sleep 1
    if kill -0 "$pid" 2>/dev/null; then
        echo "collector-service 已启动 (PID: $pid)"
        echo "  日志: $COLLECTOR_LOG"
        return 0
    fi

    rm -f "$COLLECTOR_PID"
    echo "collector-service 启动失败，请检查日志: $COLLECTOR_LOG" >&2
    tail -n 20 "$COLLECTOR_LOG" 2>/dev/null || true
    return 1
}

collector_service_stop() {
    if ! collector_service_is_running; then
        echo "collector-service 未运行"
        rm -f "$COLLECTOR_PID"
        return 0
    fi

    local pid=""
    pid="$(cat "$COLLECTOR_PID" 2>/dev/null || true)"
    if [[ -z "$pid" ]]; then
        echo "collector-service 未运行"
        rm -f "$COLLECTOR_PID"
        return 0
    fi

    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do
        if ! kill -0 "$pid" 2>/dev/null; then
            break
        fi
        sleep 0.25
    done

    if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null || true
    fi

    rm -f "$COLLECTOR_PID"
    echo "collector-service 已停止"
}

collector_service_status() {
    if [[ ! -d "$COLLECTOR_SERVICE_DIR" ]]; then
        echo "collector-service: on-demand 模式（无常驻进程）"
        collector_on_demand_cli
        return 0
    fi

    if collector_service_is_running; then
        echo "collector-service 运行中 (PID: $(cat "$COLLECTOR_PID"))"
        echo "  日志: $COLLECTOR_LOG"
        return 0
    fi

    echo "collector-service 未运行"
    return 1
}

service_start() {
    local svc="$1"
    if [[ "$svc" == "collector-service" ]]; then
        collector_service_start
        return $?
    fi

    local svc_dir="$ROOT/services/$svc"
    if [ -d "$svc_dir" ]; then
        cd "$svc_dir"
        ./scripts/start.sh start
    else
        echo "$svc 目录不存在，跳过"
    fi
}

service_stop() {
    local svc="$1"
    if [[ "$svc" == "collector-service" ]]; then
        collector_service_stop
        return $?
    fi

    local svc_dir="$ROOT/services/$svc"
    if [ -d "$svc_dir" ]; then
        cd "$svc_dir"
        ./scripts/start.sh stop
    fi
}

service_status() {
    local svc="$1"
    if [[ "$svc" == "collector-service" ]]; then
        collector_service_status
        return $?
    fi

    local svc_dir="$ROOT/services/$svc"
    if [ -d "$svc_dir" ]; then
        cd "$svc_dir"
        ./scripts/start.sh status
        return $?
    fi

    echo "$svc 目录不存在"
    return 1
}

# ==================== 数据库就绪检查 ====================
check_database() {
    local config_file="$ROOT/config/.env"
    if [ ! -f "$config_file" ]; then
        return 0  # 无配置，跳过检查
    fi

    local db_url=""
    if declare -f tc_resolve_db_url >/dev/null 2>&1; then
        db_url="$(tc_resolve_db_url "$ROOT" "" "DATABASE_URL")"
    else
        db_url="$(grep "^DATABASE_URL=" "$config_file" 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'")"
    fi
    if [ -z "$db_url" ]; then
        return 0  # 无 DATABASE_URL，跳过检查
    fi

    local db_host="localhost"
    local db_port="5432"
    if declare -f tc_db_url_target >/dev/null 2>&1; then
        local db_target host_port
        db_target="$(tc_db_url_target "$db_url")"
        host_port="${db_target%%/*}"
        if [[ "$host_port" == *:* ]]; then
            db_host="${host_port%%:*}"
            db_port="${host_port##*:}"
        fi
    else
        db_host="$(echo "$db_url" | sed -n 's|.*@\([^:/]*\).*|\1|p')"
        db_port="$(echo "$db_url" | grep -oP ':\K\d+(?=/)' || echo "5432")"
    fi
    [ -z "$db_host" ] && db_host="localhost"
    if ! [[ "$db_port" =~ ^[0-9]+$ ]]; then
        db_port="5432"
    fi
    
    if command -v pg_isready &>/dev/null; then
        if ! pg_isready -h "$db_host" -p "$db_port" -q -t 3 2>/dev/null; then
            echo -e "\033[0;31m✗ 数据库未就绪: $db_host:$db_port\033[0m"
            echo "  请确保 TimescaleDB 已启动后重试"
            return 1
        fi
    fi
    return 0
}

# ==================== 启动所有服务 ====================
start_all() {
    echo "=== 启动全部服务 ==="
    
    # 数据库就绪检查（仅对 collector-service 和 trading-service）
    if ! check_database; then
        echo "服务启动已取消"
        return 1
    fi
    
    for svc in "${SERVICES[@]}"; do
        service_start "$svc" 2>&1 | sed "s/^/  [$svc] /"
    done
}

# ==================== 停止所有服务 ====================
stop_all() {
    echo "=== 停止全部服务 ==="
    for svc in "${SERVICES[@]}"; do
        service_stop "$svc" 2>&1 | sed "s/^/  [$svc] /"
    done
}

# ==================== 状态查询 ====================
status_all() {
    echo "=== 服务状态 ==="
    for svc in "${SERVICES[@]}"; do
        service_status "$svc" 2>&1 | sed "s/^/  [$svc] /"
        echo ""
    done
}

# ==================== 守护进程（带重试上限和指数退避）====================
daemon_all() {
    echo "=== 启动守护进程模式 ==="
    
    # 检查是否已运行
    if [ -f "$DAEMON_PID" ] && kill -0 "$(cat "$DAEMON_PID")" 2>/dev/null; then
        echo "守护进程已运行 (PID: $(cat "$DAEMON_PID"))"
        return 0
    fi
    
    # 数据库就绪检查
    if ! check_database; then
        echo "守护进程启动已取消"
        return 1
    fi
    
    # 先启动所有服务
    start_all
    
    # 启动守护循环（子进程）
    (
        # 每个服务的重启计数和时间戳
        declare -A restart_counts
        declare -A last_restart_time
        declare -A backoff_time
        declare -A limit_logged  # 防止日志风暴：是否已记录达到上限
        
        for svc in "${SERVICES[@]}"; do
            restart_counts[$svc]=0
            last_restart_time[$svc]=0
            backoff_time[$svc]=$BASE_BACKOFF
            limit_logged[$svc]=0
        done
        
        log "守护进程启动 (检查间隔: ${CHECK_INTERVAL}s, 最大重试: $MAX_RESTART_ATTEMPTS)"
        
        while true; do
            sleep $CHECK_INTERVAL
            current_time=$(date +%s)
            
            for svc in "${SERVICES[@]}"; do
                # 检查服务状态（使用退出码）
                if service_status "$svc" >/dev/null 2>&1; then
                    # 服务运行中，重置计数
                    if [ "${restart_counts[$svc]}" -gt 0 ]; then
                        log "$svc: 恢复正常，重置重启计数"
                        restart_counts[$svc]=0
                        backoff_time[$svc]=$BASE_BACKOFF
                    fi
                    continue
                fi
                
                # 服务未运行
                local time_since_last=$((current_time - ${last_restart_time[$svc]}))
                
                # 如果超过重置窗口，重置计数
                if [ $time_since_last -gt $RESTART_WINDOW ]; then
                    restart_counts[$svc]=0
                    backoff_time[$svc]=$BASE_BACKOFF
                fi
                
                # 检查是否超过重试上限
                if [ "${restart_counts[$svc]}" -ge $MAX_RESTART_ATTEMPTS ]; then
                    if [ $time_since_last -lt $RESTART_WINDOW ]; then
                        # 仅首次记录，防止日志风暴
                        if [ "${limit_logged[$svc]}" -eq 0 ]; then
                            log "⚠️ $svc: 达到重试上限 ($MAX_RESTART_ATTEMPTS)，暂停重启 ${RESTART_WINDOW}s"
                            echo "$(date '+%Y-%m-%d %H:%M:%S') ⚠️ $svc 达到重试上限" >> "$ROOT/alerts.log"
                            limit_logged[$svc]=1
                        fi
                        continue
                    else
                        # 重置计数，允许新一轮重试
                        log "$svc: 重试窗口已过，重置计数"
                        restart_counts[$svc]=0
                        backoff_time[$svc]=$BASE_BACKOFF
                        limit_logged[$svc]=0
                    fi
                fi
                
                # 检查退避时间
                if [ $time_since_last -lt "${backoff_time[$svc]}" ]; then
                    continue
                fi
                
                # 执行重启
                restart_counts[$svc]=$((${restart_counts[$svc]} + 1))
                last_restart_time[$svc]=$current_time
                
                log "$svc: 未运行，重启 (尝试 ${restart_counts[$svc]}/$MAX_RESTART_ATTEMPTS)"
                service_start "$svc" >> "$DAEMON_LOG" 2>&1
                
                # 指数退避（翻倍，但不超过最大值）
                backoff_time[$svc]=$((${backoff_time[$svc]} * 2))
                if [ "${backoff_time[$svc]}" -gt $MAX_BACKOFF ]; then
                    backoff_time[$svc]=$MAX_BACKOFF
                fi
                
                # 重启失败告警
                if [ "${restart_counts[$svc]}" -ge $MAX_RESTART_ATTEMPTS ]; then
                    log "⚠️ $svc: 连续重启 $MAX_RESTART_ATTEMPTS 次失败，请人工检查！"
                    echo "$(date '+%Y-%m-%d %H:%M:%S') ⚠️ $svc 连续重启失败" >> "$ROOT/alerts.log"
                fi
            done
        done
    ) &
    
    local daemon_pid=$!
    echo $daemon_pid > "$DAEMON_PID"
    echo "守护进程已启动 (PID: $daemon_pid)"
    log "守护进程 PID: $daemon_pid"
}

# ==================== 停止守护进程 ====================
daemon_stop() {
    echo "=== 停止守护进程 ==="
    
    if [ -f "$DAEMON_PID" ]; then
        local pid=$(cat "$DAEMON_PID")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
            echo "守护进程已停止 (PID: $pid)"
            log "守护进程已停止 (PID: $pid)"
        else
            echo "守护进程未运行"
        fi
        rm -f "$DAEMON_PID"
    else
        echo "守护进程未运行"
    fi
    
    # 停止所有服务
    stop_all
}

# ==================== TUI 快捷入口（根目录直启） ====================
run_tui_single() {
    local tui_dir="$ROOT/services-preview/tui-service"
    if [ ! -d "$tui_dir" ]; then
        echo "✗ tui-service 目录不存在: $tui_dir"
        return 1
    fi
    cd "$tui_dir"
    ./scripts/start.sh run "$@"
}

run_tui() {
    echo "[TUI] 正在启动依赖服务..."
    # 启动 collector-service（行情数据采集）
    collector_service_start 2>&1 | sed 's/^/  [collector] /'
    # 启动 signal-service（信号检测）
    if [ -d "$ROOT/services/signal-service" ]; then
        cd "$ROOT/services/signal-service"
        ./scripts/start.sh start 2>&1 | sed 's/^/  [signal] /'
    fi
    echo "[TUI] 依赖服务已就绪，正在启动看板..."
    run_tui_single "$@"
}

run_tui_dev() {
    local tui_dir="$ROOT/services-preview/tui-service"
    if [ ! -d "$tui_dir" ]; then
        echo "✗ tui-service 目录不存在: $tui_dir"
        return 1
    fi
    cd "$tui_dir"
    ./scripts/start.sh run-dev "$@"
}

run_tui_equity() {
    local tui_dir="$ROOT/services-preview/tui-service"
    if [ ! -d "$tui_dir" ]; then
        echo "✗ tui-service 目录不存在: $tui_dir"
        return 1
    fi
    cd "$tui_dir"
    ./scripts/start.sh run-equity "$@"
}


# ==================== 入口 ====================
case "${1:-status}" in
    start)       start_all ;;
    stop)        stop_all ;;
    status)      status_all ;;
    restart)     stop_all; sleep 2; start_all ;;
    daemon)      daemon_all ;;
    daemon-stop) daemon_stop ;;
    start-collector) shift || true; start_collector "$@" ;;
    status-collector) shift || true; status_collector "$@" ;;
    run)         shift || true; run_tui "$@" ;;
    run-single)  warn_deprecated_alias "run-single" "run"; shift || true; run_tui_single "$@" ;;
    run-dev)     shift || true; run_tui_dev "$@" ;;
    run-equity)  shift || true; run_tui_equity "$@" ;;
    tui)         warn_deprecated_alias "tui" "run"; shift || true; run_tui "$@" ;;
    tui-single)  warn_deprecated_alias "tui-single" "run"; shift || true; run_tui_single "$@" ;;
    tui-dev)     warn_deprecated_alias "tui-dev" "run-dev"; shift || true; run_tui_dev "$@" ;;
    tui-equity)  warn_deprecated_alias "tui-equity" "run-equity"; shift || true; run_tui_equity "$@" ;;
    *)
        echo "用法: $0 {start|stop|status|restart|daemon|daemon-stop|start-collector|status-collector|run|run-dev|run-equity}"
        echo ""
        echo "命令说明:"
        echo "  start       - 启动所有核心服务"
        echo "  stop        - 停止所有核心服务"
        echo "  status      - 查看服务状态"
        echo "  restart     - 重启所有服务"
        echo "  daemon      - 启动守护进程模式（自动重启崩溃的服务）"
        echo "  daemon-stop - 停止守护进程和所有服务"
        echo "  start-collector  - 显式运行 collector-service，并透传 --only/--exclude"
        echo "  status-collector - 查看当前 collector-service 启用模块（透传选择器）"
        echo "  run         - 从根目录启动 TradeCat TUI"
        echo "  run-dev     - 从根目录启动 TUI 开发模式（强制热重载）"
        echo "  run-equity  - 从根目录启动 TUI + collector equity 采集"
        echo ""
        echo "兼容别名（逐步收敛，后续可能移除）:"
        echo "  run-single  -> run"
        echo "  tui         -> run"
        echo "  tui-single  -> run"
        echo "  tui-dev     -> run-dev"
        echo "  tui-equity  -> run-equity"
        exit 1
        ;;
esac
