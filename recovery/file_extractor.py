from pathlib import Path

from ntfs.data_runs import decode_data_runs


WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}
INVALID_FILENAME_CHARS = '<>:"/\\|?*'


def safe_output_name(file_name: str) -> str:
    """Filter/sanitize the file name"""
    # Clean the file name for invalid characters
    cleaned = ""
    for char in file_name:
        if char in INVALID_FILENAME_CHARS:
            cleaned+="_"
        else:
            cleaned+=char

    cleaned = cleaned.strip(" .") or "recovered_file"

    # Extract the base/stem to check against the reserved name list
    stem = cleaned.split(".", 1)[0].upper()
    if stem in WINDOWS_RESERVED_NAMES:
        # add _ to clean it further
        cleaned = f"_{cleaned}"

    return cleaned


def unique_output_path(output_dir: str | Path, file_name: str) -> Path:
    """Ensures files are recovered with unique names"""
    output_path = Path(output_dir)
    safe_name = safe_output_name(file_name)
    output_file_path = output_path.joinpath(safe_name)
    # If a file with that name does not exist, proceed to create one
    if not output_file_path.exists():
        return output_file_path
    # If a file with that name exists, add numbers to it
    stem = output_file_path.stem
    suffix = output_file_path.suffix
    counter = 1

    while True:
        new_file_name = output_path / f"{stem}_{counter}{suffix}"
        if not new_file_name.exists():
            return new_file_name
        counter += 1


def read_non_resident_data(disk_reader, cluster_details: list, cluster_size: int, data_size: int) -> bytes:
    recovered_data = bytearray()
    # Calculates the cluster offset on the disk for reading
    for first_run_cluster, used_clusters in cluster_details:
        cluster_offset = first_run_cluster * cluster_size
        data_length = used_clusters * cluster_size
        # Reads the cluster
        run_data = disk_reader.read_bytes(offset=cluster_offset, length=data_length)
        recovered_data.extend(run_data)
        # Skips whitespaces
        if len(recovered_data) >= data_size:
            break

    return bytes(recovered_data[:data_size])


def write_recovered_file(file_name: str, data: bytes, output_dir: str | Path = "recovered") -> Path:
    out_path = unique_output_path(output_dir, file_name)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return out_path


def recover_entry(disk_reader, entry, boot_record, output_dir: str | Path = "recovered") -> tuple[Path, int]:
    if entry.directory:
        raise ValueError("Directories are listed for context but cannot be recovered as files.")

    if entry.resident:
        recovered_data = entry.data or b""
    else:
        if not entry.data_runs:
            raise ValueError(entry.error or "No data runs were available for this file.")
        # Cluster details: length and the cluster number from data_run.py
        cluster_details = decode_data_runs(entry.data_runs)
        if not cluster_details:
            raise ValueError("No readable clusters were found for this file.")

        recovered_data = read_non_resident_data(
            disk_reader=disk_reader,
            cluster_details=cluster_details,
            cluster_size=boot_record.bytes_per_cluster,
            data_size=entry.size,
        )

    out_path = write_recovered_file(entry.filename, recovered_data[:entry.size], output_dir)
    return out_path, len(recovered_data[:entry.size])


# # Reconstruct and write recovered files
# def reconstruct_files(disk_reader, file_name: str, cluster_details: list, cluster_size: int, data_size: int, output_dir: str = "recovered"):
#     recovered_data = read_non_resident_data(disk_reader, cluster_details, cluster_size, data_size)
#     return write_recovered_file(file_name, recovered_data, output_dir)
