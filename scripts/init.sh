#!/usr/bin/env bash
# tradeagnt 初始化（默认：根目录 .venv + pip install -e .）
# 用法: ./scripts/init.sh              # 单体（推荐）
#       ./scripts/init.sh --legacy-services  # 旧微服务目录（本仓通常不存在）
#       ./scripts/init.sh collector-service    # 单服务（仅当 services/ 存在时）

set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
DB_URL_HELPER="$ROOT/scripts/lib/db_url.sh"
PY_RUNTIME_HELPER="$ROOT/scripts/lib/python_runtime.sh"
if [[ -f "$DB_URL_HELPER" ]]; then
    # shellcheck disable=SC1090
    source "$DB_URL_HELPER"
fi
if [[ -f "$PY_RUNTIME_HELPER" ]]; then
    # shellcheck disable=SC1090
    source "$PY_RUNTIME_HELPER"
fi

# 核心服务（services/ 目录）
CORE_SERVICES=(collector-service trading-service signal-service)

# 预览服务（services-preview/ 目录）
PREVIEW_SERVICES=(tui-service)

# 显式入口服务（当前为空；保留扩展位）
OPTIONAL_SERVICES=()

# ==================== 工具函数 ====================
success() { echo -e "\033[0;32m✓ $1\033[0m"; }
fail() { echo -e "\033[0;31m✗ $1\033[0m"; exit 1; }
info() { echo -e "\033[0;34m→ $1\033[0m"; }
warn() { echo -e "\033[0;33m⚠ $1\033[0m"; }

read_config_key() {
    local key="$1"
    local config_file="$ROOT/config/.env"
    if declare -f tc_read_env_key >/dev/null 2>&1; then
        tc_read_env_key "$config_file" "$key"
    else
        grep "^${key}=" "$config_file" | cut -d= -f2- | tr -d '"' | tr -d "'"
    fi
}

resolve_database_url() {
    if declare -f tc_resolve_db_url >/dev/null 2>&1; then
        tc_resolve_db_url "$ROOT" "" "DATABASE_URL"
    else
        read_config_key "DATABASE_URL"
    fi
}

db_host_port() {
    local db_url="$1"
    local host="localhost"
    local port="5432"

    if declare -f tc_db_url_target >/dev/null 2>&1; then
        local target host_port
        target="$(tc_db_url_target "$db_url")"
        host_port="${target%%/*}"
        if [[ "$host_port" == *:* ]]; then
            host="${host_port%%:*}"
            port="${host_port##*:}"
        fi
    else
        host="$(echo "$db_url" | sed -n 's|.*@\([^:/]*\).*|\1|p')"
        port="$(echo "$db_url" | grep -oP ':\K\d+(?=/)' || echo '5432')"
    fi

    [ -z "$host" ] && host="localhost"
    if ! [[ "$port" =~ ^[0-9]+$ ]]; then
        port="5432"
    fi
    echo "$host $port"
}

# ==================== 查找服务目录 ====================
find_service_dir() {
    local svc="$1"
    
    # 先在 services/ 查找
    if [ -d "$ROOT/services/$svc" ]; then
        echo "$ROOT/services/$svc"
        return 0
    fi
    
    # 再在 services-preview/ 查找
    if [ -d "$ROOT/services-preview/$svc" ]; then
        echo "$ROOT/services-preview/$svc"
        return 0
    fi
    
    return 1
}

# ==================== 初始化单个服务 ====================
init_service() {
    local svc="$1"
    local svc_dir
    local venv_python
    local base_python
    
    svc_dir=$(find_service_dir "$svc") || {
        warn "服务目录不存在: $svc (跳过)"
        return 0
    }
    
    echo ""
    echo "=== 初始化 $svc ==="
    cd "$svc_dir"
    
    # 1. 创建虚拟环境
    venv_python="$svc_dir/.venv/bin/python"
    if [ -x "$venv_python" ]; then
        if tc_python_is_compatible "$venv_python"; then
            info "虚拟环境已存在"
        else
            fail "$svc 的 .venv Python 版本过低: $(tc_python_version_string "$venv_python")（需要 3.12+，请删除后重建）"
        fi
    else
        base_python="$(tc_pick_python 2>/dev/null || true)"
        if [[ -z "$base_python" ]]; then
            fail "未找到兼容的 Python 解释器（需要 3.12+，可通过 TRADECAT_PYTHON 指定）"
        fi
        info "创建虚拟环境... ($base_python)"
        "$base_python" -m venv .venv
    fi

    if [ ! -x "$venv_python" ]; then
        fail "$svc 虚拟环境创建失败: $venv_python 不存在"
    fi
    
    # 2. 安装依赖
    info "安装依赖..."
    "$venv_python" -m pip install -q --upgrade pip
    
    if [ -f "requirements.txt" ]; then
        "$venv_python" -m pip install -q -r requirements.txt 2>/dev/null || {
            warn "部分依赖安装失败，请检查 requirements.txt"
        }
    elif [ -f "pyproject.toml" ]; then
        "$venv_python" -m pip install -q -e . 2>/dev/null || {
            warn "pyproject.toml 安装失败"
        }
    fi

    # 安装共享 common 包（editable），避免各服务依赖 sys.path hack
    "$venv_python" -m pip install -q -e "$ROOT/libs" 2>/dev/null || {
        warn "共享包安装失败: $ROOT/libs"
    }
    
    # 3. 创建运行时目录
    mkdir -p pids logs data/cache 2>/dev/null || true
    
    # 4. 设置脚本权限
    [ -f "scripts/start.sh" ] && chmod +x scripts/start.sh

    success "$svc 初始化完成"
}

# ==================== 系统依赖检查 ====================
check_system() {
    echo "=== 系统依赖检查 ==="
    local base_python=""
    local py_ver=""
    
    # Python 版本检查
    base_python="$(tc_pick_python 2>/dev/null || true)"
    if [[ -n "$base_python" ]]; then
        py_ver="$(tc_python_version_string "$base_python")"
        success "Python: $py_ver ($base_python)"
    else
        if command -v python3 &>/dev/null; then
            py_ver="$(python3 -c "import sys; sys.stdout.write(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")"
            fail "Python 版本需要 3.12+，当前 python3: $py_ver"
        else
            fail "未找到兼容的 Python 解释器（需要 3.12+）"
        fi
    fi
    
    # pip
    if [[ -n "$base_python" ]] && "$base_python" -m pip --version &>/dev/null; then
        success "pip: $("$base_python" -m pip --version | cut -d' ' -f2)"
    else
        fail "pip 未安装，请运行: ${base_python:-python3} -m ensurepip"
    fi
    
    # TA-Lib (可选)
    if [[ -n "$base_python" ]] && "$base_python" -c "import talib" 2>/dev/null; then
        success "TA-Lib: 已安装"
    else
        info "TA-Lib: 未安装（K线形态检测需要）"
    fi
    
    # PostgreSQL client (可选)
    if command -v psql &>/dev/null; then
        success "psql: $(psql --version 2>&1 | head -1)"
    else
        info "psql: 未安装（数据库操作需要）"
    fi
}

# ==================== 创建全局目录 ====================
init_global() {
    echo ""
    echo "=== 创建全局目录 ==="
    mkdir -p "$ROOT/run" "$ROOT/logs" "$ROOT/backups" "$ROOT/data"
    mkdir -p "$ROOT/libs/database/services/telegram-service"
    mkdir -p "$ROOT/libs/database/services/signal-service"
    chmod +x "$ROOT/scripts/"*.sh 2>/dev/null || true
    success "全局目录已创建"
}

# ==================== 单体根目录 .venv ====================
init_monolith() {
    echo ""
    echo "=== 初始化 tradeagnt 单体 ==="
    local base_python=""
    local venv_python="$ROOT/.venv/bin/python"

    base_python="$(tc_pick_python 2>/dev/null || true)"
    if [[ -z "$base_python" ]]; then
        fail "未找到 Python 3.12+（可设置 TRADECAT_PYTHON）"
    fi

    if [[ -x "$venv_python" ]] && tc_python_is_compatible "$venv_python"; then
        info "根目录 .venv 已存在"
    else
        info "创建 $ROOT/.venv ..."
        rm -rf "$ROOT/.venv"
        "$base_python" -m venv "$ROOT/.venv"
    fi

    if [[ ! -x "$venv_python" ]]; then
        fail "虚拟环境创建失败"
    fi

    info "安装依赖 (pip install -e .[dev])..."
    "$venv_python" -m pip install -q --upgrade pip
    (
        cd "$ROOT"
        "$venv_python" -m pip install -q -e ".[dev]" 2>/dev/null || "$venv_python" -m pip install -q -e .
    )
    success "tradecat CLI 就绪（激活 .venv 后执行: tradecat --help）"
}

# ==================== 配置文件检查 ====================
check_config() {
    echo ""
    echo "=== 配置文件检查 ==="
    
    local config_file="$ROOT/config/.env"
    local config_example="$ROOT/config/.env.example"
    
    if [ -f "$config_file" ]; then
        local perms=$(stat -c %a "$config_file" 2>/dev/null || stat -f %Lp "$config_file" 2>/dev/null)
        if [ "$perms" = "600" ] || [ "$perms" = "400" ]; then
            success "config/.env 存在 (权限: $perms)"
        else
            warn "config/.env 权限不安全: $perms (建议: chmod 600 config/.env)"
        fi
        
        # 显示 DATABASE_URL 端口
        local db_url
        db_url="$(read_config_key "DATABASE_URL")"
        if [ -n "$db_url" ]; then
            local _db_host db_port
            read -r _db_host db_port <<< "$(db_host_port "$db_url")"
            success "DATABASE_URL: 端口 $db_port"
        else
            warn "DATABASE_URL: 未配置"
        fi
    else
        if [ -f "$config_example" ]; then
            info "config/.env 不存在，请执行:"
            echo "    cp config/.env.example config/.env && chmod 600 config/.env"
        else
            fail "配置模板不存在: config/.env.example"
        fi
    fi
}

# ==================== 数据库连接检查 ====================
check_database() {
    echo ""
    echo "=== 数据库连接检查 ==="
    
    local config_file="$ROOT/config/.env"
    if [ ! -f "$config_file" ]; then
        info "跳过数据库检查 (config/.env 不存在)"
        return 0
    fi
    
    # 解析 DATABASE_URL
    local db_url
    db_url="$(resolve_database_url)"
    if [ -z "$db_url" ]; then
        info "跳过数据库检查 (DATABASE_URL 未配置)"
        return 0
    fi

    # 提取 host 和 port
    local db_host db_port
    read -r db_host db_port <<< "$(db_host_port "$db_url")"
    
    if command -v pg_isready &>/dev/null; then
        if pg_isready -h "$db_host" -p "$db_port" -q 2>/dev/null; then
            success "PostgreSQL: $db_host:$db_port 可连接"
        else
            warn "PostgreSQL: $db_host:$db_port 无法连接"
            echo "    请确保 TimescaleDB 已启动"
        fi
    else
        info "跳过数据库连接检查 (pg_isready 未安装)"
    fi
}

# ==================== 打印完成信息 ====================
print_summary() {
    echo ""
    echo "=========================================="
    echo -e "\033[0;32m✓ 初始化完成\033[0m"
    echo "=========================================="
    echo ""
    echo "下一步："
    
    local config_file="$ROOT/config/.env"
    if [ ! -f "$config_file" ]; then
        echo "  1. 创建配置文件:"
        echo "     cp config/.env.example config/.env && chmod 600 config/.env"
        echo ""
        echo "  2. 编辑配置 (必填 DATABASE_URL):"
        echo "     vim config/.env"
        echo ""
        echo "  3. 启动服务:"
    else
        echo "  1. 启动服务:"
    fi
    echo "     ./scripts/start.sh start"
    echo ""
    echo "  TUI:       TRADECAT_PIPELINE_PROFILE=tui_dual tradecat tui"
    echo "  或:        ./scripts/start.sh run"
    echo "  验收:      ./scripts/freeze_verify.sh"
}

# ==================== 入口 ====================
case "${1:-}" in
    --legacy-services)
        check_system
        init_global
        for svc in "${CORE_SERVICES[@]}"; do
            init_service "$svc"
        done
        for svc in "${PREVIEW_SERVICES[@]}"; do
            init_service "$svc"
        done
        check_config
        check_database
        print_summary
        ;;
    --all)
        # 初始化全部（含 preview）
        check_system
        init_global
        
        for svc in "${CORE_SERVICES[@]}"; do
            init_service "$svc"
        done
        
        echo ""
        info "初始化预览服务..."
        for svc in "${PREVIEW_SERVICES[@]}"; do
            init_service "$svc"
        done

        echo ""
        info "初始化显式入口服务..."
        for svc in "${OPTIONAL_SERVICES[@]}"; do
            init_service "$svc"
        done
        
        check_config
        check_database
        print_summary
        ;;
    "")
        check_system
        init_global
        init_monolith
        check_config
        check_database
        print_summary
        ;;
    *)
        # 初始化单个服务
        init_service "$1"
        ;;
esac
