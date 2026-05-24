# Raw disk/image I/O
import io
import os

class DiskReader:
    """
    Handles raw byte-level access to a disk or disk image (.img) file.
    """

    def __init__(self, path: str):
        self.file_descriptor = os.open(path, os.O_RDONLY | os.O_BINARY)
        self.data_stream = io.FileIO(self.file_descriptor)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def read_bytes(self, offset: int, length: int) -> bytes:
        self.data_stream.seek(offset)
        return self.data_stream.read(length)

    def read_sector(self, sector_number: int, sector_size: int = 512) -> bytes:
        offset = sector_number * sector_size
        return self.read_bytes(offset, sector_size)

    def read_cluster(self, cluster_number: int, cluster_size: int) -> bytes:
        offset = cluster_number * cluster_size
        return self.read_bytes(offset, cluster_size)

    def close(self):
        self.data_stream.close()
