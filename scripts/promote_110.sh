#!/bin/bash
# ============================================================
# promote_110.sh —— 134 dev 验证过的版本推 110 PROD（裸机）
# 设计：110 主动从 github 拉 tarball（避免 134 中转 / Windows 传文件）
#
# 跑在 110 PROD 上
# 触发：ssh root@172.20.2.110 "bash -s -- v0.2.0 --no-dry-run" < promote_110.sh
# 或本地：.\promote_110.ps1 v0.2.0 --no-dry-run
# ============================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log()  { echo -e "${BLUE}[$(date +%H:%M:%S)]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERR]${NC} $*" >&2; }
ok()   { echo -e "${GREEN}[OK]${NC} $*"; }

# 110 出口 443 经常被 ISP 防火墙挡（ICMP 通 / HTTPS 不通）—— 5 次重试
# 用法: retry_with_backoff "命令" "描述"
retry_with_backoff() {
    local cmd="$1"
    local desc="${2:-cmd}"
    local max=5
    local delay=5
    for i in $(seq 1 $max); do
        if eval "$cmd" 2>/dev/null; then
            if [[ $i -gt 1 ]]; then
                ok "[retry] $desc 在第 $i 次成功"
            fi
            return 0
        fi
        warn "[retry] $desc 第 $i 次失败，$delay s 后重试"
        sleep $delay
        delay=$((delay * 2))
    done
    err "[retry] $desc 5 次重试全部失败"
    return 1
}

GIT_REF="${1:-}"
DRY_RUN="--dry-run"
SKIP_MIGRATE=""
GITHUB_REPO="adauncle/archerydev"
GITHUB_BASE="https://github.com/${GITHUB_REPO}"

if [[ -z "$GIT_REF" ]]; then
    err "用法: $0 <git-ref> [--no-dry-run] [--skip-migrate]"
    err "  例: $0 v0.2.0 --no-dry-run"
    err "  例: $0 2a393a4 --no-dry-run"
    exit 1
fi
shift
while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-dry-run)    DRY_RUN=""; shift ;;
        --dry-run)       DRY_RUN="--dry-run"; shift ;;
        --skip-migrate)  SKIP_MIGRATE="1"; shift ;;
        *)               err "未知参数: $1"; exit 1 ;;
    esac
done

# 110 PROD 配置
PROD_PATH="/dbdata/archery_v114"
PROD_PORT="9123"
BACKUP_ROOT="/backup/promote"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="${BACKUP_ROOT}/${TIMESTAMP}"

# 凭据从 110 现有 .env 解析（不写死 /etc/archery/dbops_password）
# 110 v1.14.0 用 DATABASE_URL / CACHE_URL 统一配置，不是分开的 MYSQL_HOST/PORT/USER
parse_db_creds() {
    local env_file="$1"
    if [[ ! -f "$env_file" ]]; then
        err "找不到 $env_file"
        return 1
    fi
    local db_url
    db_url=$(grep -E '^DATABASE_URL=' "$env_file" | head -1 | cut -d= -f2-)
    if [[ -z "$db_url" ]]; then
        err "$env_file 里找不到 DATABASE_URL"
        return 1
    fi
    # mysql://user:pass@host:port/db
    PROD_DB_USER=$(echo "$db_url" | sed -E 's|^mysql://([^:]+):.*|\1|')
    PROD_DB_PASS=$(echo "$db_url" | sed -E 's|^mysql://[^:]+:([^@]+)@.*|\1|')
    PROD_DB_HOST=$(echo "$db_url" | sed -E 's|^mysql://[^@]+@([^:]+):.*|\1|')
    PROD_DB_PORT=$(echo "$db_url" | sed -E 's|^mysql://[^@]+@[^:]+:([0-9]+)/.*|\1|')
    PROD_DB_NAME=$(echo "$db_url" | sed -E 's|^mysql://[^@]+@[^/]+/([^?]+).*|\1|')
    if [[ -z "$PROD_DB_USER" || -z "$PROD_DB_PASS" ]]; then
        err "DATABASE_URL 解析失败: $db_url"
        return 1
    fi
    return 0
}

# ====== Phase 0: 预检 ======
phase0_precheck() {
    log "============================================================"
    log "Phase 0: 预检"
    log "============================================================"

    # 0.1 当前用户 root
    if [[ $EUID -ne 0 ]]; then
        err "需要 root 跑（110 上）"
        exit 1
    fi
    ok "[0.1] 当前用户 root"

    # 0.2 110 PROD 当前状态
    log "[0.2] 110 PROD 当前状态"
    if [[ -d "$PROD_PATH" ]]; then
        log "       当前代码: $PROD_PATH"
        local current_git
        current_git=$(cd "$PROD_PATH" 2>/dev/null && git rev-parse HEAD 2>/dev/null || echo "NOT_GIT")
        log "       HEAD: $current_git"
        # 检查现有 venv
        if [[ -d "$PROD_PATH/venv" ]]; then
            log "       venv: 存在（可复用）"
        else
            warn "     venv: 不存在"
        fi
    else
        warn "     $PROD_PATH 不存在（首次 promote？）"
    fi

    # 0.3 网络可达 github（带 retry，110 出口 443 经常被 ISP 挡）
    log "[0.3] 网络可达 github.com"
    if [[ -z "$DRY_RUN" ]]; then
        if ! retry_with_backoff "curl -s -m 10 -o /dev/null -w '%{http_code}' '$GITHUB_BASE' | grep -qE '200|301|302'" "github.com 探活"; then
            err "[0.3] github.com 不可达（5 次重试失败）"
            exit 1
        fi
        ok "[0.3] github.com 可达"
    else
        log "[DRY-RUN] 跳过 github 探活"
    fi

    # 0.4 git ref → 110 上要能拿到 commit hash
    log "[0.4] 解析 git ref: $GIT_REF"
    if [[ -z "$DRY_RUN" ]]; then
        # 用 GitHub API 拿 ref 指向的 commit SHA
        local ref_type="tags"
        local api_url="https://api.github.com/repos/${GITHUB_REPO}/git/refs/tags/${GIT_REF}"
        local resp
        resp=$(curl -s -m 10 "$api_url" 2>&1)
        local commit
        commit=$(echo "$resp" | grep -oP '"sha":\s*"\K[a-f0-9]+' | head -1)
        if [[ -z "$commit" ]]; then
            # 试 branches
            api_url="https://api.github.com/repos/${GITHUB_REPO}/git/refs/heads/${GIT_REF}"
            resp=$(curl -s -m 10 "$api_url" 2>&1)
            commit=$(echo "$resp" | grep -oP '"sha":\s*"\K[a-f0-9]+' | head -1)
        fi
        if [[ -z "$commit" ]]; then
            # 试直接当 commit hash
            if [[ "$GIT_REF" =~ ^[a-f0-9]{7,40}$ ]]; then
                commit="$GIT_REF"
            fi
        fi
        if [[ -z "$commit" ]]; then
            err "解析 git ref 失败: $GIT_REF"
            err "  试过 tags / branches / commit hash 都拿不到"
            exit 1
        fi
        export SHORT_COMMIT="${commit:0:7}"
        export RESOLVED_COMMIT="$commit"
        ok "[0.4] $GIT_REF = $SHORT_COMMIT"
    else
        export SHORT_COMMIT="dryrun0"
        export RESOLVED_COMMIT="0000000000000000000000000000000000000000"
    fi

    # 0.5 备份目录
    log "[0.5] 备份目录: $BACKUP_DIR"
    if [[ -z "$DRY_RUN" ]]; then
        mkdir -p "$BACKUP_ROOT"
        if [[ ! -w "$BACKUP_ROOT" ]]; then
            err "备份目录不可写: $BACKUP_ROOT"
            exit 1
        fi
        ok "[0.5] 备份目录 OK"
    fi
}

# ====== Phase 1: 备份 110 ======
phase1_backup() {
    log "============================================================"
    log "Phase 1: 备份 110 PROD"
    log "============================================================"

    if [[ -n "$DRY_RUN" ]]; then
        log "[DRY-RUN] mkdir -p $BACKUP_DIR"
        log "[DRY-RUN] mysqldump → $BACKUP_DIR/mysqldump.sql.gz"
        log "[DRY-RUN] tar $PROD_PATH → $BACKUP_DIR/code.tar.gz"
        log "[DRY-RUN] cp .env / secret_key → $BACKUP_DIR/"
        return
    fi

    mkdir -p "$BACKUP_DIR"

    # 1.1 mysqldump
    log "[1.1] mysqldump 110 $PROD_DB_NAME"
    if [[ -z "$PROD_DB_USER" ]]; then
        parse_db_creds "$PROD_PATH/.env" || exit 1
        log "       DB: $PROD_DB_USER@$PROD_DB_HOST:$PROD_DB_PORT/$PROD_DB_NAME"
    fi
    if mysqldump -h "$PROD_DB_HOST" -P "$PROD_DB_PORT" -u"$PROD_DB_USER" -p"$PROD_DB_PASS" "$PROD_DB_NAME" 2>/dev/null | gzip > "$BACKUP_DIR/mysqldump.sql.gz"; then
        local size
        size=$(stat -c%s "$BACKUP_DIR/mysqldump.sql.gz" 2>/dev/null || echo 0)
        ok "[1.1] mysqldump 完成: $size bytes"
    else
        err "[1.1] mysqldump 失败（重试一次显示真错误）"
        mysqldump -h "$PROD_DB_HOST" -P "$PROD_DB_PORT" -u"$PROD_DB_USER" -p"$PROD_DB_PASS" "$PROD_DB_NAME" 2>&1 | head -3
        exit 1
    fi

    # 1.2 备份代码
    if [[ -d "$PROD_PATH" ]]; then
        log "[1.2] 归档现有代码"
        cd "$PROD_PATH" && tar czf "$BACKUP_DIR/code.tar.gz" --exclude='venv' --exclude='logs' --exclude='*.pyc' --exclude='__pycache__' . 2>/dev/null
        ok "[1.2] code.tar.gz 完成"
    fi

    # 1.3 备份 .env + SECRET_KEY
    log "[1.3] 备份 .env + SECRET_KEY"
    [[ -f "$PROD_PATH/.env" ]] && cp "$PROD_PATH/.env" "$BACKUP_DIR/env.bak" 2>/dev/null
    [[ -f /backup/upgrade_v114/v110_secret_key.txt ]] && cp /backup/upgrade_v114/v110_secret_key.txt "$BACKUP_DIR/secret_key.bak" 2>/dev/null
    ok "[1.3] 备份完成"
}

# ====== Phase 2: 从 github 拉代码 ======
phase2_fetch() {
    log "============================================================"
    log "Phase 2: 从 github 拉 $GIT_REF ($SHORT_COMMIT) 代码"
    log "============================================================"

    local target_path="${PROD_PATH}_${SHORT_COMMIT}"
    export TARGET_PATH="$target_path"

    if [[ -n "$DRY_RUN" ]]; then
        log "[DRY-RUN] curl -L $GITHUB_BASE/archive/$SHORT_COMMIT.tar.gz | tar -xz -C $target_path"
        return
    fi

    # 2.1 建目标目录
    log "[2.1] 建目标目录: $target_path"
    mkdir -p "$target_path"

    # 2.2 拉 tarball
    # GitHub 提供的两种方式：
    #   - https://github.com/<repo>/archive/refs/tags/<tag>.tar.gz （推荐 tag）
    #   - https://github.com/<repo>/archive/<commit>.tar.gz （commit hash）
    log "[2.2] curl github tarball"
    local tarball_url
    if [[ "$GIT_REF" =~ ^v?[0-9]+\. ]]; then
        # tag
        tarball_url="$GITHUB_BASE/archive/refs/tags/${GIT_REF}.tar.gz"
    else
        # commit
        tarball_url="$GITHUB_BASE/archive/${SHORT_COMMIT}.tar.gz"
    fi
    log "       URL: $tarball_url"
    if ! retry_with_backoff "curl -sL -m 120 '$tarball_url' | tar -xz --strip-components=1 -C '$target_path'" "拉取 github tarball"; then
        err "[2.2] 拉取失败（5 次重试）"
        exit 1
    fi
    ok "[2.2] 拉取完成"

    # 2.3 验证关键文件
    log "[2.3] 验证关键文件"
    local missing=0
    for f in manage.py archery/settings.py requirements.txt; do
        if [[ ! -f "$target_path/$f" ]]; then
            warn "     缺文件: $target_path/$f"
            missing=1
        fi
    done
    if [[ $missing -eq 0 ]]; then
        ok "[2.3] 关键文件齐全"
    else
        err "[2.3] 关键文件缺失"
        exit 1
    fi

    # 2.4 保留现有 .env
    log "[2.4] 保留 110 现有 .env"
    if [[ -f "$PROD_PATH/.env" ]]; then
        cp "$PROD_PATH/.env" "$target_path/.env"
        ok "       .env 已保留"
    else
        warn "     110 现有 .env 不存在，promote 后需手动配置"
    fi
}

# ====== Phase 3: 适配 110 ======
phase3_adapt() {
    log "============================================================"
    log "Phase 3: 适配 110 PROD"
    log "============================================================"

    if [[ -n "$DRY_RUN" ]]; then
        log "[DRY-RUN] venv 软链/重建"
        log "[DRY-RUN] patch Django features.py (5,7)"
        log "[DRY-RUN] .env 适配 MYSQL/REDIS/端口"
        log "[DRY-RUN] systemd unit 路径更新"
        return
    fi

    # 3.1 venv 处理
    log "[3.1] venv 处理"
    if [[ ! -d "$TARGET_PATH/venv" ]]; then
        if [[ -d "$PROD_PATH/venv" ]]; then
            log "       复用 $PROD_PATH/venv（节省 30-60 min pip install）"
            ln -s "$PROD_PATH/venv" "$TARGET_PATH/venv"
            # 增量装 requirements
            cd "$TARGET_PATH" && source venv/bin/activate && pip install -q -r requirements.txt 2>&1 | tail -5
            ok "[3.1] venv 软链 + 增量装包"
        else
            err "[3.1] 110 venv 不存在且无旧 venv 可复用"
            err "      需手动跑 03_venv_install.sh 建 venv（30-60 min）"
            exit 1
        fi
    else
        ok "[3.1] venv 已存在"
    fi

    # 3.2 patch Django features.py 兼容 MySQL 5.7
    log "[3.2] patch Django features.py (MySQL 5.7)"
    local features_py
    features_py="$TARGET_PATH/venv/lib/python3.9/site-packages/django/db/backends/mysql/features.py"
    if [[ ! -f "$features_py" ]]; then
        # 试 python3.11
        features_py="$TARGET_PATH/venv/lib/python3.11/site-packages/django/db/backends/mysql/features.py"
    fi
    if [[ -f "$features_py" ]]; then
        if grep -q 'return (5, 7)' "$features_py" 2>/dev/null; then
            log "       patch 已存在"
        else
            cp "$features_py" "${features_py}.bak.5.7.${TIMESTAMP}"
            sed -i 's/return (8,)/return (5, 7)/' "$features_py"
            log "       patch 应用"
        fi
        grep -n 'return (5, 7)' "$features_py"
        ok "[3.2] features.py 兼容 OK"
    else
        warn "     features.py 路径不存在（venv 结构可能不同）"
    fi

    # 3.3 适配 .env —— 110 已有 .env 走 DATABASE_URL 统一配置
    # v0.x.x 134 dev 的 .env 用 MYSQL_HOST/PORT/USER/PASSWORD 散开配置
    # 110 走 DATABASE_URL 统一配置，promote 不能破坏
    # 策略：保留 110 现有 .env（已经在 phase 2.4 cp 过去），不 sed 改
    log "[3.3] 保留 110 现有 .env（已 cp 过去）"
    if [[ -f "$TARGET_PATH/.env" ]]; then
        # 仅做最小必要补充：v0.x.x 新增的开关默认 False
        grep -q '^DINGTALK_OA_ENABLED' "$TARGET_PATH/.env" || echo 'CUSTOM_DINGTALK_OA_ENABLED=False' >> "$TARGET_PATH/.env"
        ok "[3.3] .env 保留 + 补 DINGTALK_OA_ENABLED 开关"
    else
        err "[3.3] .env 不存在（phase 2.4 应该已 cp）"
        exit 1
    fi

    # 3.4 systemd unit 路径
    log "[3.4] 更新 systemd unit 路径: $PROD_PATH → $TARGET_PATH"
    [[ -f /etc/systemd/system/archery-v114-gunicorn.service ]] && {
        cp /etc/systemd/system/archery-v114-gunicorn.service "/etc/systemd/system/archery-v114-gunicorn.service.bak.${TIMESTAMP}"
        sed -i "s|$PROD_PATH|$TARGET_PATH|g" /etc/systemd/system/archery-v114-gunicorn.service
    }
    [[ -f /etc/systemd/system/archery-v114-qcluster.service ]] && {
        cp /etc/systemd/system/archery-v114-qcluster.service "/etc/systemd/system/archery-v114-qcluster.service.bak.${TIMESTAMP}"
        sed -i "s|$PROD_PATH|$TARGET_PATH|g" /etc/systemd/system/archery-v114-qcluster.service
    }
    systemctl daemon-reload
    ok "[3.4] systemd unit 指向 $TARGET_PATH"
}

# ====== Phase 4: deploy ======
phase4_deploy() {
    log "============================================================"
    log "Phase 4: stop → migrate → start → smoke test（停机开始）"
    log "============================================================"

    if [[ -n "$DRY_RUN" ]]; then
        log "[DRY-RUN] stop archery-v114-gunicorn archery-v114-qcluster"
        log "[DRY-RUN] python manage.py check + migrate + collectstatic"
        log "[DRY-RUN] start archery-v114-gunicorn archery-v114-qcluster"
        log "[DRY-RUN] curl http://127.0.0.1:9123/login/"
        log "[DRY-RUN] mysql ... 'SHOW TABLES LIKE ext_%'"
        return
    fi

    # 4.0 stop 旧服务
    log "[4.0] stop 旧 gunicorn + qcluster（停机开始: $(date)）"
    systemctl stop archery-v114-gunicorn archery-v114-qcluster 2>&1 || warn "     stop 失败（可能没在跑）"
    sleep 2

    cd "$TARGET_PATH"
    source venv/bin/activate
    set -a; source .env; set +a

    # 4.1 Django check
    log "[4.1] python manage.py check"
    python manage.py check 2>&1 | tail -5 || { err "[4.1] check 失败"; exit 1; }

    # 4.2 migrate
    if [[ -z "$SKIP_MIGRATE" ]]; then
        log "[4.2] python manage.py migrate"
        python manage.py migrate --noinput 2>&1 | tail -20
        ok "[4.2] migrate 完成"
    else
        log "[4.2] --skip-migrate，跳过"
    fi

    # 4.3 collectstatic
    log "[4.3] python manage.py collectstatic"
    python manage.py collectstatic --noinput 2>&1 | tail -5

    # 4.4 start 新服务
    log "[4.4] start 新 gunicorn + qcluster（服务启动: $(date)）"
    systemctl start archery-v114-gunicorn archery-v114-qcluster
    sleep 5

    # 4.5 验证 active
    log "[4.5] 验证服务 active"
    systemctl is-active archery-v114-gunicorn archery-v114-qcluster

    # 4.6 HTTP smoke
    log "[4.6] HTTP smoke test (9123)"
    local http_code
    http_code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$PROD_PORT/login/)
    if [[ "$http_code" == "200" || "$http_code" == "302" ]]; then
        ok "[4.6] HTTP $http_code"
    else
        err "[4.6] HTTP $http_code 不对，详情："
        journalctl -u archery-v114-gunicorn --since '1 min ago' | tail -30
        exit 1
    fi

    # 4.7 ext_ 表数
    log "[4.7] 校验 ext_ 表数（v0.x.x 二次开发）"
    if [[ -z "$PROD_DB_USER" ]]; then
        parse_db_creds "$TARGET_PATH/.env" || exit 1
    fi
    local ext_count
    ext_count=$(mysql -h "$PROD_DB_HOST" -P "$PROD_DB_PORT" -u"$PROD_DB_USER" -p"$PROD_DB_PASS" "$PROD_DB_NAME" -B -N -e 'SHOW TABLES LIKE "ext\_%"' 2>/dev/null | wc -l)
    log "       ext_ 表数: $ext_count（v0.x.x 期望 ≥ 7）"
    if [[ $ext_count -lt 7 ]]; then
        warn "     ext_ 表数 < 7，migrate 可能漏跑"
    fi
}

# ====== Phase 5: 收尾 ======
phase5_finish() {
    log "============================================================"
    log "Phase 5: 收尾"
    log "============================================================"

    if [[ -n "$DRY_RUN" ]]; then
        log "[DRY-RUN] 通知 DBA 团队 / 7 天后清理"
        return
    fi

    log "[5.1] 旧版本 $PROD_PATH 保留作 A 级回滚保险（不动）"
    log "      当前活跃: $TARGET_PATH（systemd unit 已指向）"
    log "[5.2] 备份位置: $BACKUP_DIR"
    log "[5.3] D+7 清理（建议 cron）:"
    log "      rm -rf $PROD_PATH  # 旧版"
    log "      rm -rf $BACKUP_DIR  # 30 天后"
    log ""
    ok "============================================================"
    ok "promote_110.sh 完成"
    ok "  Git ref:    $GIT_REF ($SHORT_COMMIT)"
    ok "  Active:     $TARGET_PATH"
    ok "  Backup:     $BACKUP_DIR"
    ok "============================================================"
}

# ====== 主流程 ======
main() {
    echo
    log "============================================================"
    log "promote_110.sh 启动（110 主动从 github 拉）"
    log "============================================================"
    log "Git ref:    $GIT_REF"
    log "Mode:       ${DRY_RUN:-REAL（实际执行）}"
    log "Skip-mig:   ${SKIP_MIGRATE:-NO}"
    log "Prod path:  $PROD_PATH"
    log "Target:     ${PROD_PATH}_<commit>"
    log "Backup:     $BACKUP_DIR"
    echo

    phase0_precheck
    phase1_backup
    phase2_fetch
    phase3_adapt
    phase4_deploy
    phase5_finish
}

main "$@"
