from __future__ import annotations

import math
from dataclasses import dataclass, field
from rich import box
from rich.align import Align
from rich.columns import Columns
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text


try:
    import msvcrt
except ImportError:
    msvcrt = None


@dataclass
class SelectorResult:
    entries: list = field(default_factory=list)
    quit_requested: bool = False
    back_requested: bool = False


class RecoveryDashboard:
    def __init__(self, state, boot_record, drive, mode="scan"):
        self.state = state
        self.boot = boot_record
        self.drive = drive
        self.mode = mode
        self.layout = Layout(name="root")

        self.layout.split_column(
            Layout(name="header", size=5),
            Layout(name="progress", size=4),
            Layout(name="stats", size=5),
            Layout(name="main", ratio=1),
            Layout(name="footer", size=3),
        )

        self.layout["main"].split_row(
            Layout(name="table", ratio=5),
            Layout(name="logs", ratio=2),
        )

        self.progress = Progress(
            TextColumn("[bold cyan]scanning MFT records"),
            BarColumn(bar_width=None, complete_style="green", finished_style="green"),
            TextColumn("[dim]{task.completed:,.0f} / {task.total:,.0f}"),
            TimeElapsedColumn(),
            expand=True,
        )
        self.scan_task = self.progress.add_task("scan", total=100)

    def build_header(self):
        title = Text("NTFS File Recovery Tool", style="bold cyan")
        total_size = format_size(getattr(self.boot, "bytes_per_sector", 0) * total_sectors(self.boot))

        details = Text()
        details.append("drive ", style="dim")
        details.append(self.drive, style="bold green")
        details.append(" | size ", style="dim")
        details.append(total_size, style="blue")
        details.append(" | fs ", style="dim")
        details.append("NTFS" if self.boot.is_ntfs else "unknown", style="green")

        return Panel(
            Group(title, details),
            border_style="bright_black",
            box=box.SQUARE,
        )

    def build_stats(self):
        stats = [
            stat_card("DELETED FILES", self.state.deleted_files, "green"),
            stat_card("DELETED DIRS", self.state.deleted_dirs, "yellow"),
            stat_card("RECOVERABLE", self.state.recoverable_files, "cyan"),
            stat_card("RECOVERED", self.state.recovered_files, "blue"),
        ]
        return Columns(stats, equal=True, expand=True)

    def build_progress_panel(self):
        current_file = self.state.current_file or "waiting..."
        title = "Scan Results" if self.mode == "results" else "Live Scan"
        info = Group(
            Text(f"record {self.state.current_record:,}", style="dim"),
            Text(current_file, style="white"),
            self.progress,
        )

        return Panel(info, title=title, border_style="bright_black", box=box.ROUNDED)

    def build_table(self):
        table = Table(
            title="Deleted Files",
            border_style="bright_black",
            box=box.SIMPLE_HEAVY,
            expand=True,
        )
        table.add_column("#", style="dim", width=8)
        table.add_column("filename", style="bold white", overflow="fold")
        table.add_column("type", style="dim", width=10)
        table.add_column("size", justify="right", width=12)
        table.add_column("status", width=14)

        # only display the last 18 records
        for entry in self.state.entries[-18:]:
            type = "directory" if entry.directory else ("resident" if entry.resident else "non-res")
            size = "-" if entry.directory else format_size(entry.size)
            table.add_row(
                str(entry.record_number),
                entry.filename,
                type,
                size,
                status_badge(entry),
            )

        return table

    def build_logs(self):
        logs_table = Table(title="Events", border_style="bright_black", box=box.SIMPLE, expand=True)
        logs_table.add_column("log", overflow="fold")

        for log in self.state.logs[-14:]:
            logs_table.add_row(log)

        return logs_table

    def build_footer(self):
        if self.mode == "results":
            footer = (
                "[cyan]r[/cyan] recover/select files   "
                "[cyan]q[/cyan] quit   "
                "[dim]to scroll records, go to the recovery tab by pressing r[/dim]"
            )
        else:
            footer = "[cyan]scanning[/cyan]  "
        return Panel(Align.center(footer), border_style="bright_black", box=box.ROUNDED)

    # Implement/update the layout
    def refresh(self):
        self.layout["header"].update(self.build_header())
        self.layout["progress"].update(self.build_progress_panel())
        self.layout["stats"].update(self.build_stats())
        self.layout["table"].update(self.build_table())
        self.layout["logs"].update(self.build_logs())
        self.layout["footer"].update(self.build_footer())


class RecoverySelector:
    def __init__(self, state, boot_record, drive, console: Console | None = None):
        self.state = state
        self.boot = boot_record
        self.drive = drive
        self.console = console or Console()
        self.cursor = 0
        self.offset = 0
        self.selected: set[int] = set()
        self.search = ""
        self.message = "Use arrows or j/k to move, Space to select, Enter to recover, B/esc to go back."

    def run(self) -> SelectorResult:
        entries = self.visible_entries
        if not entries:
            return SelectorResult([])

        with Live(self.render(), console=self.console, refresh_per_second=12, screen=True) as live:
            while True:
                key = read_key()
                if key in {"b", "B", "esc"}:
                    return SelectorResult(back_requested=True)
                if key in {"q", "Q"}:
                    return SelectorResult(quit_requested=True)
                if key in {"up", "k", "K"}:
                    self.move(-1)
                elif key in {"down", "j", "J"}:
                    self.move(1)
                elif key == "pageup":
                    self.move(-10)
                elif key == "pagedown":
                    self.move(10)
                elif key in {" ", "space"}:
                    self.toggle_current()
                elif key in {"a", "A"}:
                    self.toggle_all_visible()
                elif key in {"c", "C"}:
                    self.selected.clear()
                    self.message = "Selection cleared."
                elif key in {"/", "f", "F"}:
                    live.stop()
                    self.search = Prompt.ask("Filter filename", default=self.search, console=self.console).strip()
                    self.cursor = 0
                    self.offset = 0
                    self.message = f"Filter: {self.search or 'all files'}"
                    live.start(refresh=True)
                elif key in {"enter", "\r", "\n"}:
                    if not self.visible_entries:
                        self.message = "No files match the current filter."
                        live.update(self.render(), refresh=True)
                        continue
                    if not self.selected_entries and not self.visible_entries[self.cursor].recoverable:
                        self.message = "Current file is not recoverable; select a recoverable file first."
                        live.update(self.render(), refresh=True)
                        continue
                    chosen = self.selected_entries or [self.visible_entries[self.cursor]]
                    return SelectorResult(chosen)

                live.update(self.render(), refresh=True)

    @property
    def file_entries(self):
        return [entry for entry in self.state.entries if not entry.directory]


    @property
    def visible_entries(self):
        query = self.search.casefold()
        entries = self.file_entries
        if query:
            entries = [entry for entry in entries if query in entry.filename.casefold()]
        return entries

    @property
    def selected_entries(self):
        return [entry for entry in self.file_entries if entry.record_number in self.selected]

    def move(self, amount: int):
        total = len(self.visible_entries)
        if total == 0:
            self.cursor = 0
            return

        self.cursor = max(0, min(total - 1, self.cursor + amount))
        page_size = self.page_size
        if self.cursor < self.offset:
            self.offset = self.cursor
        elif self.cursor >= self.offset + page_size:
            self.offset = self.cursor - page_size + 1

    def toggle_current(self):
        entries = self.visible_entries
        if not entries:
            return

        entry = entries[self.cursor]
        if not entry.recoverable:
            self.message = f"{entry.filename} is not recoverable: {entry.error or 'no readable data'}"
            return

        if entry.record_number in self.selected:
            self.selected.remove(entry.record_number)
            self.message = f"Removed {entry.filename}"
        else:
            self.selected.add(entry.record_number)
            self.message = f"Selected {entry.filename}"

    def toggle_all_visible(self):
        visible_recoverable = {entry.record_number for entry in self.visible_entries if entry.recoverable}
        if visible_recoverable and visible_recoverable.issubset(self.selected):
            self.selected.difference_update(visible_recoverable)
            self.message = "Visible files deselected."
        else:
            self.selected.update(visible_recoverable)
            self.message = f"Selected {len(visible_recoverable)} visible recoverable files."

    @property
    def page_size(self):
        return max(8, min(18, self.console.size.height - 16))

    def render(self):
        layout = Layout(name="selector")
        layout.split_column(
            Layout(self.selector_header(), size=7),
            Layout(self.selector_table(), ratio=1),
            Layout(self.selector_summary(), size=7),
        )
        return layout

    def selector_header(self):
        title = Text("Select Files to Recover", style="bold cyan")
        details = Text()
        details.append("drive ", style="dim")
        details.append(self.drive, style="green")
        details.append("  output folder ", style="dim")
        details.append(f"{self.state.output_dir_path}", style="green")
        details.append("  filter ", style="dim")
        details.append(self.search or "none", style="white")
        return Panel(Group(title, details, Text(self.message, style="dim")), border_style="bright_black")

    def selector_table(self):
        entries = self.visible_entries
        page_size = self.page_size
        visible_page = entries[self.offset : self.offset + page_size]

        table = Table(box=box.SIMPLE_HEAVY, expand=True, border_style="bright_black")
        table.add_column("", width=2)
        table.add_column("sel", width=5)
        table.add_column("#", width=8, style="dim")
        table.add_column("filename", overflow="fold")
        table.add_column("type", width=10)
        table.add_column("size", justify="right", width=12)
        table.add_column("status", width=18)

        for index, entry in enumerate(visible_page, start=self.offset):
            active = index == self.cursor
            selected = entry.record_number in self.selected
            pointer = ">" if active else ""
            row_style = "cyan" if active else None
            checkbox = "[green][x][/]" if selected else "[dim][ ][/]"
            table.add_row(
                pointer,
                checkbox,
                str(entry.record_number),
                entry.filename,
                "resident" if entry.resident else "non-res",
                format_size(entry.size),
                status_badge(entry),
                style=row_style,
            )

        if not visible_page:
            table.add_row("", "", "-", "No files match the current filter.", "-", "-", "[dim]empty[/]")

        return Panel(table, title="Deleted Files", border_style="bright_black")

    def selector_summary(self):
        selected_size = sum(entry.size for entry in self.selected_entries)
        total_pages = max(1, math.ceil(len(self.visible_entries) / self.page_size))
        page = min(total_pages, self.offset // self.page_size + 1)
        summary = Columns(
            [
                stat_card("SELECTED", len(self.selected), "green"),
                stat_card("TOTAL SIZE", format_size(selected_size), "blue"),
                stat_card("VISIBLE", len(self.visible_entries), "cyan"),
                stat_card("PAGE", f"{page}/{total_pages}", "yellow"),
            ],
            equal=True,
            expand=True,
        )
        keys = Align.center(
            "[cyan]up/down[/cyan] move   [cyan]space[/cyan] select   "
            "[cyan]a[/cyan] all   [cyan]/[/cyan] filter   [cyan]enter[/cyan] recover   "
            "[cyan]b[/cyan] back   [cyan]q[/cyan] quit"
        )
        return Panel(Group(summary, keys), border_style="bright_black")


class ResultsDashboard:
    def __init__(self, state, boot_record, drive, console: Console | None = None):
        self.state = state
        self.boot = boot_record
        self.drive = drive
        self.console = console or Console()
        self.ui = RecoveryDashboard(state, boot_record, drive, mode="results")
        total = max(1, state.scanned_records)
        self.ui.progress.update(
            self.ui.scan_task,
            completed=state.scanned_records,
            total=total,
        )

    def run(self, screen=True) -> str:
        self.state.current_file = "Scan complete"
        self.ui.refresh()

        with Live(self.ui.layout, console=self.console, refresh_per_second=8, screen=screen) as live:
            while True:
                key = read_key()
                if key in {"r", "R", "enter", "\r", "\n"}:
                    return "recover"
                if key in {"q", "Q", "esc"}:
                    return "quit"
                self.ui.refresh()
                live.update(self.ui.layout, refresh=True)


def read_key() -> str:
    if msvcrt is None:
        return input("> ").strip()

    key = msvcrt.getwch()
    if key in ("\x00", "\xe0"):
        code = msvcrt.getwch()
        return {
            "H": "up",
            "P": "down",
            "I": "pageup",
            "Q": "pagedown",
            "K": "left",
            "M": "right",
        }.get(code, code)

    return {
        "\r": "enter",
        "\x1b": "esc",
        " ": "space",
    }.get(key, key)


def stat_card(label: str, value, color: str):
    body = Align.center(f"[bold {color}]{value}[/]\n[dim]{label}[/]")
    return Panel(body, border_style="bright_black", box=box.ROUNDED)


def status_badge(entry) -> str:
    if entry.recoverable:
        return "[green]recoverable[/]"
    if entry.error:
        return f"[red]{entry.error.replace('[*] ', '')[:16]}[/]"
    return "[red]unreadable[/]"


def format_size(size: int):
    size = int(size or 0)
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    if size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / (1024 * 1024 * 1024):.1f} GB"


def total_sectors(boot_record) -> int:
    total = getattr(boot_record, "total_sectors", 0)
    if isinstance(total, tuple):
        return int(total[0])
    return int(total or 0)
