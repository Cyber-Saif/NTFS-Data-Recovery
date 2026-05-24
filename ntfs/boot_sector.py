import struct

class BootSector:

    def __init__(self, raw_bytes: bytes):
        self.data = raw_bytes
        self.parse()

    def parse(self):
        # Offset 0x0B Field-length '<H'
        self.bytes_per_sector = struct.unpack_from('<H', self.data, 0x0B)[0]

        # Offset 0x0D Field-length '<B'
        self.sectors_per_cluster = struct.unpack_from('<B', self.data, 0x0D)[0]

        # Offset 0x28 Field-length '<Q'
        self.total_sectors = struct.unpack_from('<Q', self.data, 0x28)

        # MFT Logical Cluster Number
        # Offset 0x30 Field-length '<Q'
        self.mft_lcn = struct.unpack_from('<Q', self.data, 0x30)[0]

        # Offset 0x38 Field-length '<Q'
        self.mft_mirror_lcn = struct.unpack_from('<Q', self.data, 0x38) # MFTMirr is MFT backup

        # Clusters Per File Record
        # Offset 0x40 → '<b' !signed
        cluster_per_file_record = struct.unpack_from('<b', self.data, 0x40)[0]
        if cluster_per_file_record < 0:
            self.mft_record_size = 2 ** abs(cluster_per_file_record)
        else:
            self.mft_record_size = cluster_per_file_record * self.bytes_per_cluster

        # OEM ID
        self.oem_id = self.data[0x03:0x0B]
        self.is_ntfs = (self.oem_id == b'NTFS    ')


    @property
    def bytes_per_cluster(self) -> int:
        return self.bytes_per_sector * self.sectors_per_cluster

    @property
    def mft_offset_bytes(self) -> int:
        return self.mft_lcn * self.bytes_per_cluster
