#!/bin/bash

# ── helpers ────────────────────────────────────────────────────────────────────
BOLD='\033[1m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
RESET='\033[0m'

log()  { echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')]${RESET} $*"; }
info() { echo -e "${CYAN}[INFO]${RESET}  $*"; }
warn() { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
sep()  { echo -e "${BOLD}══════════════════════════════════════════════${RESET}"; }

# ── startup banner ─────────────────────────────────────────────────────────────
sep
echo -e "${BOLD}  Docker Swarm App — Container Starting${RESET}"
sep
info "Hostname    : $(hostname)"
info "Container ID: $(cut -c1-12 /proc/self/cgroup 2>/dev/null | grep -oE '[a-f0-9]{12}' | head -1 || echo 'n/a')"
info "Image tag   : ${IMAGE_TAG:-latest}"
info "Kernel      : $(uname -r)"
info "OS          : $(grep PRETTY_NAME /etc/os-release | cut -d= -f2 | tr -d '"')"
info "CPUs        : $(nproc)"
info "Total RAM   : $(awk '/MemTotal/{printf "%.0f MB", $2/1024}' /proc/meminfo)"
info "Working dir : $(pwd)"
sep
echo ""

# ── counters ───────────────────────────────────────────────────────────────────
ITERATION=0
START_TIME=$(date +%s)

# ── main loop ──────────────────────────────────────────────────────────────────
while true; do
    ITERATION=$((ITERATION + 1))
    NOW=$(date +%s)
    UPTIME_SEC=$((NOW - START_TIME))
    UPTIME=$(printf '%02dh %02dm %02ds' $((UPTIME_SEC/3600)) $(( (UPTIME_SEC%3600)/60 )) $((UPTIME_SEC%60)))

    sep
    log "Iteration #${ITERATION}"
    echo ""

    # -- time & uptime
    info "Timestamp   : $(date '+%Y-%m-%d %H:%M:%S %Z')"
    info "Uptime      : ${UPTIME}"

    # -- resource snapshot
    FREE_RAM=$(awk '/MemAvailable/{printf "%.0f MB", $2/1024}' /proc/meminfo)
    CPU_IDLE=$(grep 'cpu ' /proc/stat | awk '{printf "%.1f%%", ($5*100)/($2+$3+$4+$5+$6+$7+$8)}')
    DISK_FREE=$(df -h / | awk 'NR==2{print $4}')
    info "Free RAM    : ${FREE_RAM}"
    info "CPU idle    : ${CPU_IDLE}"
    info "Disk free   : ${DISK_FREE} on /"

    # -- process count
    PROC_COUNT=$(ls /proc | grep -c '^[0-9]')
    info "Processes   : ${PROC_COUNT}"

    # -- network interfaces
    echo ""
    info "Network interfaces:"
    ip -brief addr 2>/dev/null | while read -r iface state addr _rest; do
        printf "              %-12s %-10s %s\n" "$iface" "$state" "$addr"
    done

    # -- load average
    LOAD=$(cut -d' ' -f1-3 /proc/loadavg)
    info "Load avg    : ${LOAD} (1m 5m 15m)"

    # -- working directory listing
    echo ""
    info "Files in workdir ($(pwd)):"
    ls -lh | tail -n +2 | while read -r line; do
        printf "              %s\n" "$line"
    done

    echo ""
    log "Sleeping 5 seconds…"
    echo ""
    sleep 5
done
