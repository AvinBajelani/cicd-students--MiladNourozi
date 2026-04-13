#!/usr/bin/env python3
"""
System Monitor — beautiful live display of CPU, Memory, Network, and Disk.
Runs every second. Press Ctrl-C to quit.
"""

import math
import os
import time
from collections import deque

import psutil
from rich.console import Console, Group
from rich.table import Table
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich import box

# ── Config (overridable via env / Kubernetes ConfigMap) ───────────────────────
REFRESH_RATE  = float(os.environ.get("REFRESH_RATE",   "1.0"))
SHOW_LOOPBACK = os.environ.get("SHOW_LOOPBACK", "false").lower() == "true"
BAR_WIDTH     = int(os.environ.get("BAR_WIDTH",        "28"))
HISTORY_LEN   = 20

# ── Unicode art ───────────────────────────────────────────────────────────────
_SPARK  = "▁▂▃▄▅▆▇█"          # sparkline characters (low → high)
_BLOCKS = " ▏▎▍▌▋▊▉█"         # 9 levels for smooth bars (0 = empty)

# ── Theme ─────────────────────────────────────────────────────────────────────
def _c(pct: float) -> str:
    """Traffic-light colour based on percentage 0-100."""
    if pct < 60:
        return "bright_green"
    if pct < 85:
        return "yellow"
    return "bright_red"

# ── Number formatting ─────────────────────────────────────────────────────────
def _bytes(n: float) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:6.1f} {u}"
        n /= 1024
    return f"{n:6.1f} PB"

def _bps(n: float) -> str:
    return _bytes(n) + "/s"

def _uptime(secs: float) -> str:
    s = int(secs)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if d:
        return f"{d}d {h:02d}h {m:02d}m"
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    return f"{m}m {s:02d}s"

# ── Visual primitives ─────────────────────────────────────────────────────────
def smooth_bar(pct: float, width: int = BAR_WIDTH, color: str | None = None) -> Text:
    """
    Smooth progress bar using Unicode eighth-block characters.
    Example at 47%:  ████████████▍░░░░░░░░░░░░░░
    """
    color = color or _c(pct)
    pct   = max(0.0, min(100.0, pct))
    fill  = pct / 100.0 * width
    full  = int(fill)
    frac  = int((fill - full) * 8)   # 0-7

    t = Text(no_wrap=True)
    t.append("█" * full, style=color)
    if full < width:
        if frac:
            t.append(_BLOCKS[frac], style=color)
            t.append("░" * (width - full - 1), style="grey30")
        else:
            t.append("░" * (width - full), style="grey30")
    return t

def sparkline(hist: deque, width: int = 15, max_val: float | None = None) -> Text:
    """Mini spark chart built from a rolling history deque."""
    data = list(hist)[-width:]
    if not data:
        return Text("─" * width, style="dim")
    mx = max_val or max(data) or 1.0
    t = Text(no_wrap=True)
    for v in data:
        idx = min(int(v / mx * 7), 7)
        t.append(_SPARK[idx], style=_c(v / mx * 100))
    return t

# ── Rolling-history store ─────────────────────────────────────────────────────
class _History:
    def __init__(self):
        self.cpu: deque[float] = deque(maxlen=HISTORY_LEN)
        self.rx:  deque[float] = deque(maxlen=HISTORY_LEN)
        self.tx:  deque[float] = deque(maxlen=HISTORY_LEN)

# ── Data collector ────────────────────────────────────────────────────────────
class Monitor:
    def __init__(self):
        psutil.cpu_percent(interval=None, percpu=True)     # warm-up
        self._prev_net  = psutil.net_io_counters(pernic=True)
        # Session baseline: bytes at startup; used to show "transferred this session"
        self._init_net  = {k: (v.bytes_recv, v.bytes_sent)
                           for k, v in self._prev_net.items()}
        self._prev_disk = psutil.disk_io_counters()
        self._prev_ts   = time.monotonic()
        self.hist       = _History()

    def snapshot(self) -> dict:
        now     = time.monotonic()
        elapsed = max(now - self._prev_ts, 0.001)
        self._prev_ts = now

        # CPU
        cpu_pcts  = psutil.cpu_percent(interval=None, percpu=True)
        cpu_total = sum(cpu_pcts) / len(cpu_pcts) if cpu_pcts else 0.0
        try:    freq = psutil.cpu_freq()
        except: freq = None
        try:    load = os.getloadavg()
        except: load = (0.0, 0.0, 0.0)
        try:    uptime = time.time() - psutil.boot_time()
        except: uptime = 0.0

        # Memory
        mem  = psutil.virtual_memory()
        swap = psutil.swap_memory()

        # Network
        cur_net   = psutil.net_io_counters(pernic=True)
        net_stats = {}
        total_rx = total_tx = 0.0
        for iface, cur in cur_net.items():
            prev = self._prev_net.get(iface)
            if not prev:
                continue
            rx = max(0.0, (cur.bytes_recv - prev.bytes_recv) / elapsed)
            tx = max(0.0, (cur.bytes_sent - prev.bytes_sent) / elapsed)
            init_rx, init_tx = self._init_net.get(iface, (0, 0))
            net_stats[iface] = {
                "rx_rate":    rx,
                "tx_rate":    tx,
                "session_rx": max(0, cur.bytes_recv - init_rx),
                "session_tx": max(0, cur.bytes_sent - init_tx),
                "total_rx":   cur.bytes_recv,
                "total_tx":   cur.bytes_sent,
                "pkts_rx":    cur.packets_recv,
                "pkts_tx":    cur.packets_sent,
                "errin":      cur.errin,
                "errout":     cur.errout,
            }
            if iface != "lo":
                total_rx += rx
                total_tx += tx
        self._prev_net = cur_net

        # Disk I/O
        cur_disk = psutil.disk_io_counters()
        rd_rate = wr_rate = 0.0
        if cur_disk and self._prev_disk:
            rd_rate = max(0.0, (cur_disk.read_bytes  - self._prev_disk.read_bytes)  / elapsed)
            wr_rate = max(0.0, (cur_disk.write_bytes - self._prev_disk.write_bytes) / elapsed)
        self._prev_disk = cur_disk

        # History
        self.hist.cpu.append(cpu_total)
        self.hist.rx.append(total_rx)
        self.hist.tx.append(total_tx)

        return dict(
            cpu_pcts=cpu_pcts, cpu_total=cpu_total, freq=freq,
            load=load, uptime=uptime,
            mem=mem, swap=swap,
            net=net_stats, total_rx=total_rx, total_tx=total_tx,
            rd_rate=rd_rate, wr_rate=wr_rate,
            disk=psutil.disk_usage("/"),
            ts=time.strftime("%Y-%m-%d  %H:%M:%S"),
            hist=self.hist,
        )


# ── Panel builders ────────────────────────────────────────────────────────────

def _header(d: dict) -> Panel:
    try:    host = os.uname().nodename
    except: host = "unknown"

    n  = len(d["cpu_pcts"])
    f  = f"  {d['freq'].current:.0f} MHz" if d["freq"] else ""
    la = d["load"]

    line1 = Text()
    line1.append("  ◆ SYSTEM MONITOR", style="bold bright_white")
    line1.append("   ")
    line1.append(host, style="bold bright_cyan")
    line1.append(f"   {n} cores{f}", style="dim cyan")
    line1.append("   ")
    line1.append(d["ts"], style="bold white")
    line1.append(f"  ·  up {_uptime(d['uptime'])}", style="dim")

    line2 = Text()
    line2.append("  Load avg: ", style="dim")
    line2.append(f"{la[0]:.2f}  {la[1]:.2f}  {la[2]:.2f}", style="yellow")
    line2.append("    CPU: ", style="dim")
    line2.append_text(sparkline(d["hist"].cpu, width=HISTORY_LEN))
    line2.append("    Net ↓: ", style="dim")
    line2.append_text(sparkline(d["hist"].rx, width=10))
    line2.append("  Net ↑: ", style="dim")
    line2.append_text(sparkline(d["hist"].tx, width=10))

    return Panel(
        Group(line1, line2),
        box=box.HEAVY,
        border_style="bright_cyan",
        padding=(0, 0),
    )


def _cpu(d: dict) -> Panel:
    pcts  = d["cpu_pcts"]
    total = d["cpu_total"]
    n     = len(pcts)
    la    = d["load"]

    num_cols = 1 if n <= 8 else 2 if n <= 16 else 3
    bar_w    = max(10, (BAR_WIDTH - (num_cols - 1) * 4) // num_cols)
    rows     = math.ceil(n / num_cols)

    # Wide "All CPUs" summary + sparkline
    c_all = _c(total)
    summary = Text()
    summary.append("  All  ", style="bold white")
    summary.append_text(smooth_bar(total, BAR_WIDTH + 10, c_all))
    summary.append(f"  {total:5.1f}%", style=f"bold {c_all}")
    summary.append("   ", style="")
    summary.append_text(sparkline(d["hist"].cpu, width=HISTORY_LEN))

    # Per-core grid
    tbl = Table(box=None, padding=(0, 0), expand=True, show_header=False)
    for _ in range(num_cols):
        tbl.add_column("id",  width=4,          no_wrap=True, style="dim cyan")
        tbl.add_column("bar", width=bar_w + 1,  no_wrap=True)
        tbl.add_column("pct", width=5,          no_wrap=True, justify="right")
        tbl.add_column("gap", width=3,          no_wrap=True)

    for r in range(rows):
        row: list = []
        for c in range(num_cols):
            idx = c * rows + r
            if idx < n:
                p   = pcts[idx]
                col = _c(p)
                row += [
                    f"{idx:>2}",
                    smooth_bar(p, bar_w, col),
                    Text(f"{p:3.0f}%", style=f"bold {col}"),
                    Text(""),
                ]
            else:
                row += [Text(""), Text(""), Text(""), Text("")]
        tbl.add_row(*row)

    f_str = f"{d['freq'].current:.0f} MHz" if d["freq"] else "─"
    return Panel(
        Group(summary, Text(""), tbl),
        title=(
            f"[bold bright_cyan] CPU[/bold bright_cyan]"
            f"  [dim]│  {f_str}  │  load {la[0]:.2f}  {la[1]:.2f}  {la[2]:.2f}[/dim]"
        ),
        border_style="cyan",
        box=box.ROUNDED,
        padding=(0, 1),
    )


def _memory(d: dict) -> Panel:
    mem  = d["mem"]
    swap = d["swap"]
    w    = BAR_WIDTH + 10

    tbl = Table(box=None, padding=(0, 1), expand=True, show_header=False)
    tbl.add_column("lbl",   width=5,      style="bold white",   no_wrap=True)
    tbl.add_column("bar",   width=w + 2,  no_wrap=True)
    tbl.add_column("pct",   width=7,      justify="right",      no_wrap=True)
    tbl.add_column("used",  width=11,     justify="right",      no_wrap=True)
    tbl.add_column("sep",   width=3,      no_wrap=True)
    tbl.add_column("total", width=11,     justify="right",      no_wrap=True)
    tbl.add_column("free",  width=15,     justify="right",      no_wrap=True)

    def _row(label, used, total_b, pct):
        col = _c(pct)
        return (
            label,
            smooth_bar(pct, w, col),
            Text(f"{pct:5.1f}%", style=f"bold {col}"),
            Text(_bytes(used).strip(),    style=col),
            Text(" / ",                   style="dim"),
            Text(_bytes(total_b).strip(), style="dim"),
            Text(f"free {_bytes(total_b - used).strip()}", style="bright_green"),
        )

    tbl.add_row(*_row("RAM",  mem.used,  mem.total,  mem.percent))
    if swap.total > 0:
        tbl.add_row(*_row("Swap", swap.used, swap.total, swap.percent))

    cached = getattr(mem, "cached", 0) + getattr(mem, "buffers", 0)
    avail_pct = mem.available / mem.total * 100 if mem.total else 0
    return Panel(
        tbl,
        title=(
            f"[bold bright_green] Memory[/bold bright_green]"
            f"  [dim]│  avail {_bytes(mem.available).strip()}  ({avail_pct:.1f}%)"
            f"  │  cache+buf {_bytes(cached).strip()}[/dim]"
        ),
        border_style="green",
        box=box.ROUNDED,
        padding=(0, 1),
    )


def _mbps(bps: float) -> str:
    """Convert bytes/s to a Mbps string — the unit everyone knows their ISP by."""
    mbps = bps * 8 / 1_000_000   # bytes → megabits
    if mbps >= 1000:
        return f"{mbps/1000:.2f} Gbps"
    if mbps >= 1:
        return f"{mbps:.1f} Mbps"
    kbps = bps * 8 / 1_000
    if kbps >= 1:
        return f"{kbps:.1f} Kbps"
    return f"{bps * 8:.0f} bps"

def _rate_bar(bps: float, max_bps: float, width: int = 12) -> Text:
    """Compact rate bar scaled to the fastest interface (or 125 MB/s = 1 Gbps)."""
    pct = min(bps / max(max_bps, 1), 1.0) * 100
    return smooth_bar(pct, width, _c(pct))

def _network(d: dict) -> Panel:
    net    = d["net"]
    ifaces = [i for i in net if SHOW_LOOPBACK or i != "lo"]

    if not ifaces:
        return Panel(
            "[dim]No network interfaces found[/dim]",
            title="[bold yellow] Network[/bold yellow]",
            border_style="yellow", box=box.ROUNDED,
        )

    # Scaling reference: max RX rate across all visible interfaces (min 1 MB/s)
    max_rx = max((net[i]["rx_rate"] for i in ifaces), default=0.0)
    max_rx = max(max_rx, 1 * 1024 * 1024)   # floor at 1 MB/s so bar isn't always full

    # ── Summary row ──────────────────────────────────────────────────────────
    total_rx = d["total_rx"]
    total_tx = d["total_tx"]
    summary = Text()
    summary.append("  ↓ ", style="bold bright_cyan")
    summary.append(f"{_bps(total_rx).strip()}", style="bold bright_cyan")
    summary.append(f"  ({_mbps(total_rx)})", style="dim cyan")
    summary.append("  ")
    summary.append_text(sparkline(d["hist"].rx, width=16))
    summary.append("      ↑ ", style="bold bright_magenta")
    summary.append(f"{_bps(total_tx).strip()}", style="bold bright_magenta")
    summary.append(f"  ({_mbps(total_tx)})", style="dim magenta")
    summary.append("  ")
    summary.append_text(sparkline(d["hist"].tx, width=16))

    # ── Per-interface table ───────────────────────────────────────────────────
    tbl = Table(box=box.SIMPLE, padding=(0, 1), expand=True)
    tbl.add_column("Interface",   width=14, style="bold white")
    tbl.add_column("↓ RX/s",     width=12, justify="right")
    tbl.add_column("(Mbps)",      width=11, justify="right", style="dim cyan")
    tbl.add_column("RX bar",      width=14, no_wrap=True)
    tbl.add_column("↑ TX/s",     width=12, justify="right")
    tbl.add_column("(Mbps)",      width=11, justify="right", style="dim magenta")
    tbl.add_column("▲ Session",  width=12, justify="right", style="bold yellow")
    tbl.add_column("Err",         width=5,  justify="right")

    # Sort: most active (by RX rate) first
    ifaces_sorted = sorted(ifaces, key=lambda i: net[i]["rx_rate"], reverse=True)

    for iface in ifaces_sorted:
        s     = net[iface]
        er    = s["errin"] + s["errout"]
        rx    = s["rx_rate"]
        tx    = s["tx_rate"]
        # highlight the busiest interface
        name_style = "bold bright_cyan" if iface == ifaces_sorted[0] and rx > 1024 else "bold white"

        tbl.add_row(
            Text(iface, style=name_style),
            # MB/s rate — color by load
            Text(_bps(rx).strip(), style=_c(min(rx / max_rx * 100, 100))),
            # Mbps equivalent — the number users compare against their ISP speed
            f"({_mbps(rx)})",
            # visual bar
            _rate_bar(rx, max_rx),
            Text(_bps(tx).strip(), style="bright_magenta" if tx > 1024 else "dim"),
            f"({_mbps(tx)})",
            # session bytes: shows exactly how much was downloaded since app start
            _bytes(s["session_rx"]).strip() if s["session_rx"] > 0 else Text("─", style="dim"),
            Text(str(er), style="bright_red" if er else "dim"),
        )

    return Panel(
        Group(summary, tbl),
        title=(
            "[bold yellow] Network[/bold yellow]"
            "  [dim]│  ▲ Session = bytes received since this app started[/dim]"
        ),
        border_style="yellow",
        box=box.ROUNDED,
        padding=(0, 1),
    )


def _disk(d: dict) -> Panel:
    u   = d["disk"]
    pct = u.percent
    col = _c(pct)

    row1 = Text()
    row1.append("  / ", style="bold white")
    row1.append_text(smooth_bar(pct, BAR_WIDTH + 10, col))
    row1.append(f"  {pct:5.1f}%", style=f"bold {col}")
    row1.append(f"   used  {_bytes(u.used).strip()}", style=col)
    row1.append(" / ", style="dim")
    row1.append(_bytes(u.total).strip(), style="dim")
    row1.append(f"   free  {_bytes(u.free).strip()}", style="bright_green")

    row2 = Text()
    row2.append("       ", style="")
    row2.append("Read  ", style="dim")
    row2.append(f"{_bps(d['rd_rate']).strip():<14}", style="bright_cyan")
    row2.append("  Write  ", style="dim")
    row2.append(_bps(d["wr_rate"]).strip(), style="bright_magenta")

    return Panel(
        Group(row1, row2),
        title="[bold blue] Disk[/bold blue]",
        border_style="blue",
        box=box.ROUNDED,
        padding=(0, 1),
    )


# ── Screen ────────────────────────────────────────────────────────────────────

def build_screen(d: dict) -> Group:
    return Group(
        _header(d),
        _cpu(d),
        _memory(d),
        _network(d),
        _disk(d),
    )


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    console = Console()
    monitor = Monitor()
    monitor.snapshot()     # warm-up; discard
    time.sleep(0.5)

    d = monitor.snapshot()
    with Live(build_screen(d), console=console, screen=True, refresh_per_second=2) as live:
        while True:
            time.sleep(REFRESH_RATE)
            d = monitor.snapshot()
            live.update(build_screen(d))


if __name__ == "__main__":
    main()
