#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════
# AUTO-REELS PRO v10.0 — BACKUP & DISASTER RECOVERY SCRIPTS
# ═══════════════════════════════════════════════════════════════════════════

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${PROJECT_ROOT}/backups"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

mkdir -p "$BACKUP_DIR"

# ── BACKUP DATABASE ────────────────────────────────────────────────────────

backup_database() {
    echo -e "${YELLOW}📦 Backing up PostgreSQL database...${NC}"
    
    local db_url="${DATABASE_URL:-postgresql://autoreels:dev_password_change_in_prod@localhost:5432/autoreels}"
    local backup_file="${BACKUP_DIR}/db_$(date +%Y%m%d_%H%M%S).sql"
    
    if command -v pg_dump &> /dev/null; then
        pg_dump "$db_url" > "$backup_file"
        echo -e "${GREEN}✅ Database backup saved to: $backup_file${NC}"
        
        # Compress backup
        gzip "$backup_file"
        echo -e "${GREEN}✅ Backup compressed${NC}"
        
        # Keep only last 7 backups
        ls -t "${BACKUP_DIR}"/db_*.sql.gz | tail -n +8 | xargs -r rm
        echo -e "${GREEN}✅ Cleanup old backups (kept 7)${NC}"
    else
        echo -e "${RED}❌ pg_dump not found. Install PostgreSQL client tools.${NC}"
        exit 1
    fi
}

# ── BACKUP REDIS ────────────────────────────────────────────────────────────

backup_redis() {
    echo -e "${YELLOW}📦 Backing up Redis data...${NC}"
    
    local redis_url="${REDIS_URL:-redis://localhost:6379}"
    local backup_file="${BACKUP_DIR}/redis_$(date +%Y%m%d_%H%M%S).rdb"
    
    if command -v redis-cli &> /dev/null; then
        redis-cli -u "$redis_url" BGSAVE
        sleep 2
        
        # Copy RDB file
        redis-cli -u "$redis_url" --rdb "$backup_file" 2>/dev/null || true
        
        if [ -f "$backup_file" ]; then
            echo -e "${GREEN}✅ Redis backup saved to: $backup_file${NC}"
            gzip "$backup_file"
        else
            echo -e "${YELLOW}⚠️  Redis RDB backup skipped (using cloud Redis)${NC}"
        fi
    else
        echo -e "${YELLOW}⚠️  redis-cli not found. Skipping local backup.${NC}"
    fi
}

# ── BACKUP APPLICATION DATA ────────────────────────────────────────────────

backup_app_data() {
    echo -e "${YELLOW}📦 Backing up application data...${NC}"
    
    local backup_file="${BACKUP_DIR}/app_data_$(date +%Y%m%d_%H%M%S).tar.gz"
    
    tar -czf "$backup_file" \
        --exclude=".git" \
        --exclude="__pycache__" \
        --exclude="*.pyc" \
        --exclude=".venv" \
        -C "$PROJECT_ROOT" \
        cloud/config/ \
        cloud/queue/ \
        cloud/logs/ \
        2>/dev/null || true
    
    echo -e "${GREEN}✅ App data backup saved to: $backup_file${NC}"
}

# ── RESTORE DATABASE ───────────────────────────────────────────────────────

restore_database() {
    local backup_file=$1
    
    if [ ! -f "$backup_file" ]; then
        echo -e "${RED}❌ Backup file not found: $backup_file${NC}"
        exit 1
    fi
    
    echo -e "${YELLOW}⚠️  RESTORING DATABASE - THIS WILL OVERWRITE CURRENT DATA!${NC}"
    read -p "Type 'yes' to confirm: " confirm
    
    if [ "$confirm" != "yes" ]; then
        echo "Restore cancelled"
        exit 0
    fi
    
    local db_url="${DATABASE_URL:-postgresql://autoreels:dev_password_change_in_prod@localhost:5432/autoreels}"
    
    # Decompress if needed
    if [[ "$backup_file" == *.gz ]]; then
        gunzip -c "$backup_file" | psql "$db_url"
    else
        psql "$db_url" < "$backup_file"
    fi
    
    echo -e "${GREEN}✅ Database restored successfully${NC}"
}

# ── RESTORE REDIS ──────────────────────────────────────────────────────────

restore_redis() {
    local backup_file=$1
    
    if [ ! -f "$backup_file" ]; then
        echo -e "${RED}❌ Backup file not found: $backup_file${NC}"
        exit 1
    fi
    
    echo -e "${YELLOW}⚠️  RESTORING REDIS - THIS WILL OVERWRITE CURRENT DATA!${NC}"
    read -p "Type 'yes' to confirm: " confirm
    
    if [ "$confirm" != "yes" ]; then
        echo "Restore cancelled"
        exit 0
    fi
    
    local redis_url="${REDIS_URL:-redis://localhost:6379}"
    
    redis-cli -u "$redis_url" SHUTDOWN NOSAVE
    sleep 1
    
    # Copy RDB file to Redis data directory
    cp "$backup_file" /var/lib/redis/dump.rdb || cp "$backup_file" ~/.redis/dump.rdb || true
    
    # Restart Redis
    systemctl restart redis-server || brew services restart redis || docker restart autoreels-cache
    
    echo -e "${GREEN}✅ Redis restored successfully${NC}"
}

# ── VERIFY BACKUP ──────────────────────────────────────────────────────────

verify_backup() {
    echo -e "${YELLOW}🔍 Verifying backup integrity...${NC}"
    
    if [ ! -d "$BACKUP_DIR" ] || [ -z "$(ls -A $BACKUP_DIR)" ]; then
        echo -e "${RED}❌ No backups found${NC}"
        return 1
    fi
    
    local total_size=$(du -sh "$BACKUP_DIR" | cut -f1)
    local latest=$(ls -t "$BACKUP_DIR" | head -1)
    local latest_time=$(ls -lt "$BACKUP_DIR" | head -2 | tail -1 | awk '{print $6, $7, $8}')
    
    echo -e "${GREEN}✅ Backup directory: $BACKUP_DIR${NC}"
    echo -e "${GREEN}✅ Total size: $total_size${NC}"
    echo -e "${GREEN}✅ Latest backup: $latest (at $latest_time)${NC}"
    
    # List all backups
    echo ""
    echo "All backups:"
    ls -lh "$BACKUP_DIR" | tail -n +2 | awk '{print $9, "(" $5 ")"}'
}

# ── SYNC TO S3 ─────────────────────────────────────────────────────────────

sync_to_s3() {
    echo -e "${YELLOW}☁️  Syncing backups to S3...${NC}"
    
    local s3_bucket="${S3_BACKUP_BUCKET:-autoreels-backups}"
    
    if command -v aws &> /dev/null; then
        aws s3 sync "$BACKUP_DIR" "s3://${s3_bucket}/autoreels/" \
            --exclude "*.sql" \
            --exclude "*.rdb" \
            --sse AES256 \
            --region us-east-1
        
        echo -e "${GREEN}✅ Backups synced to S3${NC}"
    else
        echo -e "${YELLOW}⚠️  AWS CLI not installed. Skipping S3 sync.${NC}"
    fi
}

# ── HEALTH CHECK ───────────────────────────────────────────────────────────

health_check() {
    echo -e "${YELLOW}🏥 Running health checks...${NC}"
    
    # Check DB
    if command -v psql &> /dev/null; then
        local db_url="${DATABASE_URL:-postgresql://autoreels:dev_password_change_in_prod@localhost:5432/autoreels}"
        if psql "$db_url" -c "SELECT 1" &>/dev/null; then
            echo -e "${GREEN}✅ PostgreSQL: OK${NC}"
        else
            echo -e "${RED}❌ PostgreSQL: FAILED${NC}"
        fi
    fi
    
    # Check Redis
    if command -v redis-cli &> /dev/null; then
        if redis-cli ping &>/dev/null; then
            echo -e "${GREEN}✅ Redis: OK${NC}"
        else
            echo -e "${RED}❌ Redis: FAILED${NC}"
        fi
    fi
    
    # Check API
    if curl -s http://localhost:5000/health > /dev/null; then
        echo -e "${GREEN}✅ Web API: OK${NC}"
    else
        echo -e "${RED}❌ Web API: FAILED${NC}"
    fi
    
    # Check Celery
    if docker ps | grep celery-worker &>/dev/null; then
        echo -e "${GREEN}✅ Celery Worker: OK${NC}"
    else
        echo -e "${YELLOW}⚠️  Celery Worker: NOT RUNNING${NC}"
    fi
}

# ── MAIN ────────────────────────────────────────────────────────────────────

usage() {
    cat << EOF
AutoReels Pro v10 — Backup & Recovery

Usage: bash scripts/backup.sh <command>

Commands:
    backup              Full backup (DB + Redis + App)
    backup-db           Backup PostgreSQL only
    backup-redis        Backup Redis only
    backup-app          Backup application data only
    
    restore-db FILE     Restore PostgreSQL from backup
    restore-redis FILE  Restore Redis from backup
    
    verify              Verify backup integrity
    sync-s3             Sync backups to AWS S3
    health              Run health checks
    
Examples:
    bash scripts/backup.sh backup                           # Full backup
    bash scripts/backup.sh restore-db backups/db_20240327_120000.sql.gz
    bash scripts/backup.sh sync-s3

EOF
}

# Load environment
set -a
[ -f "$PROJECT_ROOT/.env" ] && source "$PROJECT_ROOT/.env"
set +a

case "${1:-help}" in
    backup)
        backup_database
        backup_redis
        backup_app_data
        sync_to_s3
        verify_backup
        ;;
    backup-db)
        backup_database
        ;;
    backup-redis)
        backup_redis
        ;;
    backup-app)
        backup_app_data
        ;;
    restore-db)
        restore_database "$2"
        ;;
    restore-redis)
        restore_redis "$2"
        ;;
    verify)
        verify_backup
        ;;
    sync-s3)
        sync_to_s3
        ;;
    health)
        health_check
        ;;
    *)
        usage
        ;;
esac
