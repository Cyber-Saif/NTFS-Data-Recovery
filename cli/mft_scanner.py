from dataclasses import dataclass
from enum import Enum
from ntfs.data_runs import decode_data_runs


SYSTEM_RECORDS = 26

@dataclass
class FileEntry:
    record_number: int
    directory: bool
    filename: str
    size: int
    resident: bool
    deleted: bool
    recoverable: bool
    status: str
    data: bytes | None = None
    data_runs: bytes | None = None
    error: str| None = None


class RecoveryStatus(Enum):
    QUEUED = "queued"
    RECOVERED = "recovered"
    FAILED = "failed"
    OVERWRITTEN = "overwritten"


class MFTScanner:
    def __init__(self, parser):
        self.parser = parser

    def record_scanner(self):
        # Scanning each record from MFTParser record iterator
        for record in self.parser.iter_records():
            # Skipping system records
            if record.record_number < SYSTEM_RECORDS:
                continue
             #Skipping corrupted records
            if not record.is_valid():
                continue

            filename = self.parser.get_filename(record)
            # Retrieve the data content dataclass
            data = self.parser.get_data_content(record)

            if not filename:
                filename = "no_name"

            file_size = self.get_file_size(data)

            entry = FileEntry(
                record_number=record.record_number,
                directory=record.is_directory(),
                filename=filename,
                size=file_size,
                resident=data.resident,
                deleted=record.is_deleted(),
                recoverable=data.error is None,
                status=RecoveryStatus.QUEUED.value,
                data=data.data,
                data_runs=data.runs,
                error=data.error
            )

            yield entry

    def get_file_size(self, data) -> int:
        """Extracts/Parse data fields from the returned DataContent"""
        if data.resident:
            return len(data.data or b"")

        if not data.runs:
            return data.size

        try:
            cluster_size = self.parser.boot.bytes_per_cluster
            run_capacity = sum(length for _, length in decode_data_runs(data.runs)) * cluster_size
        except (AttributeError, IndexError, TypeError, ValueError):
            return data.size

        if data.size <= 0:
            return run_capacity
        if run_capacity and data.size > run_capacity:
            return run_capacity
        return data.size
