import argparse

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from cli.dashboard import RecoveryDashboard, RecoverySelector, ResultsDashboard, format_size
from cli.mft_scanner import MFTScanner
from cli.file_state import AppState

from ntfs.boot_sector import BootSector
from ntfs.disk_reader import DiskReader
from ntfs.mft_parser import MFTParser

from recovery.file_extractor import recover_entry

# For debugging
# DEFAULT_DRIVE = r"\\.\F:"


def parse_args():
    parser = argparse.ArgumentParser(description="NTFS data recovery tool")
    #parser.add_argument("--drive", default=DEFAULT_DRIVE, help=r"Raw NTFS volume path, for example \\.\F:")
    parser.add_argument("--drive", help=r"Provide NTFS volume path, for example \\.\F:", required=True)
    parser.add_argument("--output", type= str, default="recovered", help="Directory to store recovered files")
    parser.add_argument("--no-screen", action="store_true", help="Do not use the alternate terminal screen")
    return parser.parse_args()


def ntfs_details(boot):
    """Stores useful NTFS details from the boot sector"""
    return {
        "Valid NTFS": boot.is_ntfs,
        "Bytes per sector": boot.bytes_per_sector,
        "Sectors per cluster": boot.sectors_per_cluster,
        "Bytes per cluster": boot.bytes_per_cluster,
        "MFT starts at LCN": boot.mft_lcn,
        "MFT byte offset": boot.mft_offset_bytes,
        "MFT record size": boot.mft_record_size,
    }


def scan_deleted_entries(parser, boot_record, drive, output_dir, console, screen=True):
    state = AppState(output_dir=output_dir)
    scanner = MFTScanner(parser)
    ui = RecoveryDashboard(state, boot_record, drive)

    total_records = parser.get_mft_size() // boot_record.mft_record_size
    ui.progress.update(ui.scan_task, total=total_records)
    ui.refresh()

    with Live(ui.layout, console=console, refresh_per_second=10, screen=screen):
        # Scans the MFT table and parses the records
        for entry in scanner.record_scanner():
            state.scanned_records += 1
            state.current_record = entry.record_number
            state.current_file = entry.filename
            # if file deleted, store the entry in the AppState entries list
            if entry.deleted:
                state.entries.append(entry)
                # count for total deleted files & folders
                if entry.directory:
                    state.deleted_dirs += 1
                else:
                    state.deleted_files += 1
                    if entry.recoverable:
                        state.recoverable_files += 1

                state.logs.append(format_scan_log(entry))

            ui.progress.update(ui.scan_task, advance=1)
            ui.refresh()

        state.current_file = "Scan complete"
        ui.refresh()

    return state

def format_scan_log(entry):
    if entry.directory:
        return f"[yellow]DIR[/] #{entry.record_number} {entry.filename}"
    if entry.recoverable:
        return f"[green]FILE[/] #{entry.record_number} {entry.filename} ({format_size(entry.size)})"
    return f"[red]SKIP[/] #{entry.record_number} {entry.filename} - {entry.error or 'not recoverable'}"


def recover_selected_entries(disk, boot_record, entries, state, output_dir):
    results = []
    for entry in entries:
        try:
            path, written = recover_entry(disk, entry, boot_record, output_dir)
            entry.status = "recovered"
            state.recovered_files += 1
            state.recovered_bytes += written
            results.append((entry, "recovered", path, written, None))
        except Exception as exc:
            entry.status = "failed"
            state.failed_files += 1
            results.append((entry, "failed", None, 0, str(exc)))
    return results


def render_results(results, state):
    table = Table(expand=True)
    table.add_column("#", style="dim", width=8)
    table.add_column("filename", overflow="fold")
    table.add_column("status", width=12)
    table.add_column("written", justify="right", width=12)
    table.add_column("output / error", overflow="fold")

    for entry, status, path, written, error in results:
        style = "green" if status == "recovered" else "red"
        detail = str(path) if path else error or "failed"
        table.add_row(
            str(entry.record_number),
            entry.filename,
            f"[{style}]{status}[/]",
            format_size(written),
            detail,
        )

    summary = (
        f"\n[green]{state.recovered_files} recovered[/]  "
        f"[red]{state.failed_files} failed[/]  "
        f"[blue]{format_size(state.recovered_bytes)} saved[/]  "
        f"\n[dim]recorvered files destination ->[/] {state.output_dir}"
    )

    return Panel(Group(table, summary), title="[bold cyan]Recovered Files[/]", border_style="bright_black")


def main():
    args = parse_args()
    console = Console()

    try:
        with DiskReader(args.drive) as disk:
            boot_sector_bytes = disk.read_sector(0)
            boot_record = BootSector(boot_sector_bytes)
            if not boot_record.is_ntfs:
                console.print(f"[red]The selected drive does not look like NTFS:[/] {args.drive}")
                return 1

            parser = MFTParser(disk, boot_record)
            state = scan_deleted_entries(
                parser=parser,
                boot_record=boot_record,
                drive=args.drive,
                output_dir=args.output,
                console=console,
                screen=not args.no_screen,
            )

            while True:
                action = ResultsDashboard(state, boot_record, args.drive, console).run(screen=not args.no_screen)
                if action == "quit":
                    console.print("[yellow]No files recovered.[/]")
                    return 0

                selector = RecoverySelector(state, boot_record, args.drive, console)
                result = selector.run()
                if result.quit_requested:
                    console.print("[yellow]No files recovered.[/]")
                    return 0
                if result.back_requested or not result.entries:
                    continue

                results = recover_selected_entries(disk, boot_record, result.entries, state, args.output)
                console.print(render_results(results, state))

                return 0 if state.failed_files == 0 else 2

    except PermissionError:
        console.print(
            "[red]Permission denied.[/] Run the terminal as Administrator, "
            "or pass --drive with a readable disk image path.\n"
            r"[grey42]Example:[/] [light_slate_blue]\\.\F:[/]"
        )
        return 1
    except OSError as exc:
        console.print(f"[red]Could not open/read {args.drive}:[/] {exc}")
        return 1
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/]")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
