#!/bin/bash
# =============================================================================
# Daily PostgreSQL backup to Cloudflare R2
# =============================================================================
# Setup: Add to crontab with:  crontab -e
#   0 2 * * * /home/ubuntu/nova-pa/scripts/backup_db.sh >> /home/ubuntu/nova-pa/logs/backup.log 2>&1
#
# Requires: rclone configured with R2 remote named "r2"
#   rclone config → new remote → "r2" → S3-compatible → Cloudflare R2
# =============================================================================

DB_NAME="nova_db"
BACKUP_DIR="/tmp/nova-backups"
R2_BUCKET="nova-backups"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/nova_${DATE}.sql.gz"

mkdir -p "$BACKUP_DIR"

echo "[$DATE] Starting backup..."

# Dump and compress
pg_dump "$DB_NAME" | gzip > "$BACKUP_FILE"
SIZE=$(du -sh "$BACKUP_FILE" | cut -f1)
echo "  Dump size: $SIZE"

# Upload to R2
if command -v rclone &> /dev/null; then
    rclone copy "$BACKUP_FILE" "r2:$R2_BUCKET/"
    echo "  Uploaded to r2:$R2_BUCKET/$(basename $BACKUP_FILE)"
else
    echo "  rclone not installed — backup stays local at $BACKUP_FILE"
fi

# Keep only last 7 local backups
find "$BACKUP_DIR" -name "nova_*.sql.gz" -mtime +7 -delete

echo "  Backup complete"
