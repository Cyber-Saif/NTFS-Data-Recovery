from dataclasses import dataclass, field
from cli.mft_scanner import *

@dataclass
class AppState:
    scanned_records: int = 0
    deleted_files: int = 0
    deleted_dirs: int = 0
    recoverable_files: int = 0
    recovered_files: int = 0
    failed_files: int = 0
    recovered_bytes: int = 0
    current_record: int = 0
    current_file: str = ""
    output_dir: str = "recovered"
    entries: list[FileEntry] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
