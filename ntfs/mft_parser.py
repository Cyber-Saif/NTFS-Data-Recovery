import struct
from dataclasses import dataclass
from typing import Optional

@dataclass
class DataContent:
    resident: bool
    data: Optional[bytes] = None
    runs: Optional[bytes] = None
    size: int = 0
    error: Optional[str] = None

class MFTRecord:
    """
    Parsing individual MFT Records
    """
    # Useful offsets:
    #   0x00 Signature - b'FILE' for valid records (4 bytes)
    #   0x16 Flags (0x00 = deleted file, 0x01 = in-use, 0x02 = directory) (1 byte)
    #   0x18–0x1B : Used size of MFT entry
    #   0x1C–0x1F : Allocated size of MFT entry

    SIGNATURE = b'FILE'
    FLAG_IN_USE = 0x01
    FLAG_DIRECTORY = 0x02

    def __init__(self, raw_bytes: bytes, record_number: int):
        self.raw_bytes = raw_bytes
        self.record_number = record_number

    def is_valid(self) -> bool:
        """Check that the record starts with the FILE signature."""
        return self.raw_bytes[0:4] == self.SIGNATURE

    def is_deleted(self) -> bool:
        flags_field = struct.unpack_from('<H', self.raw_bytes, 0x16)[0]
        return (flags_field & self.FLAG_IN_USE) == 0

    def is_directory(self) -> bool:
        flags_field = struct.unpack_from('<H', self.raw_bytes, 0x16)[0]
        return (flags_field & self.FLAG_DIRECTORY) == 2

    def parse_attributes(self) -> list:
        # Importan offsets for header
        #   0x00–0x03 : Attribute type (e.g. 0x10, 0x30, 0x80) ~ 4 bytes value
        #   0x04–0x07 : Length of this attribute ~ 4 bytes value
        #   0x08      : Non-resident flag (0 = resident, 1 = non-resident)
        #   0x09      : Length of attribute name (usually 0)
        #   0x0A–0x0B : Offset to attribute name
        #   0x0C–0x0D : Flags
        #   0x0E–0x0F : Attribute ID
        attrs = []
        # Starting offset for attributes
        attribute_offset = struct.unpack_from('<H', self.raw_bytes, 0x14)[0]

        while attribute_offset < len(self.raw_bytes):
            # Read attribute type (4 bytes at current ptr)
            attr_type = struct.unpack_from('<I', self.raw_bytes, attribute_offset)[0]

            # End of Record
            if attr_type == 0xFFFFFFFF:
                break

            # Read attribute length (4 bytes at ptr + 4)
            attr_len = struct.unpack_from('<I', self.raw_bytes, attribute_offset + 0x04)[0]
            if attr_len == 0:
                break

            attrs.append(self.raw_bytes[attribute_offset : attribute_offset + attr_len])

            # Advance pointer by attribute length
            attribute_offset += attr_len

        return attrs



class MFTParser:
    """Iterates over all MFT records on the volume."""

    ATTR_STANDARD_INFO = 0x10
    ATTR_FILE_NAME     = 0x30
    ATTR_DATA          = 0x80

    def __init__(self, disk_reader, boot_sector):
        self.disk = disk_reader
        self.boot = boot_sector

    def get_mft_size(self) -> int:
        offset = self.boot.mft_offset_bytes
        record_zero_bytes = self.disk.read_bytes(offset, self.boot.mft_record_size)
        mft_record_zero = MFTRecord(record_zero_bytes, 0)

        if not mft_record_zero.is_valid():
            raise RuntimeError("Record 0 is not a valid MFT entry")

        mft_size = self.get_data_content(mft_record_zero)

        return mft_size.size


    def iter_records(self):
        #total_records = need to find a way
        record_number = 0
        mft_length = self.get_mft_size()
        total_mft_records = mft_length // self.boot.mft_record_size

        while record_number <= total_mft_records:
            # Reading 1024 bytes record starting from the $MFT file offset
            offset = self.boot.mft_offset_bytes + (record_number * self.boot.mft_record_size)
            try:
                record_bytes = self.disk.read_bytes(offset, self.boot.mft_record_size)
            except OSError:
                break

            if len(record_bytes) < self.boot.mft_record_size:
                break

            yield MFTRecord(record_bytes, record_number)
            record_number += 1


    def get_filename(self, record: MFTRecord) -> str:
        """Extract the filename from the $FILE_NAME attribute (type 0x30)."""

        # $FILE_NAME attribute content starts with:
        #   0x00–0x07 : Parent directory reference
        #   ... (timestamps) ...
        #   0x40      : Filename length (in characters)
        #   0x41      : Filename namespace
        #   0x42+     : Filename in UTF-16-LE
        # Offset 0x42 is relative to the start of the attribute *content*.

        filename = ""
        attributes_list = record.parse_attributes()

        for attr in attributes_list:
            attr_type = struct.unpack_from('<I', attr, 0x00)[0]
            if attr_type != self.ATTR_FILE_NAME:
                continue

            # Read non-resident flag from the attribute header
            non_resident = struct.unpack_from('<B', attr, 0x08)[0]
            if non_resident:
                continue

            # Content offset from the attribute header
            content_offset = struct.unpack_from('<H', attr, 0x14)[0]

            # Ensure that the attribute has enough data before accessing the filename length
            if len(attr) < content_offset + 0x42:
                continue

            # Read the filename length
            filename_len = struct.unpack_from('<B', attr, content_offset + 0x40)[0]

            # Ensure that there are enough bytes to read the filename based on the length
            filename_end = content_offset + 0x42 + filename_len * 2
            if len(attr) < filename_end:
                continue

            # Read the filename in UTF-16-LE encoding
            filename_bytes = attr[content_offset + 0x42 : filename_end]
            try:
                filename = filename_bytes.decode('utf-16-le')
            except UnicodeDecodeError:
                print(f"Error decoding filename at content_offset {content_offset}")
                filename = ""
                continue

        return filename


    def get_data_content(self, record: MFTRecord):
        """
        Resident $DATA content offset = 0x14
        For non-resident data runs start at offset 0x20–0x21.
        """
        attributes_list = record.parse_attributes()
        for attr in attributes_list:
            attr_type = struct.unpack_from('<I', attr, 0x00)[0]

            # Checking whether the attribute type is $DATA (0x80)
            if attr_type != self.ATTR_DATA:
                continue

            attr_length = struct.unpack_from('<I', attr, 0x04)[0]

            is_resident = struct.unpack_from('<B', attr, 0x08)[0] == 0
            is_non_resident = struct.unpack_from('<B', attr, 0x08)[0] == 1

            try:
                # For resident data
                if is_resident:
                    data_offset = struct.unpack_from('<H', attr, 0x14)[0]
                    data_length = struct.unpack_from('<I', attr, 0x18)[0]
                    attr_data = attr[data_offset: data_offset + data_length]

                    return DataContent(resident=True, data=attr_data, size=data_length)

                # For non-resident data
                elif is_non_resident:
                    data_run_list = struct.unpack_from('<H', attr, 0x20)[0]
                    data_size = struct.unpack_from('<Q', attr, 0x30)[0]
                    data_bytes = attr[data_run_list:]

                    return DataContent(resident=False, runs=data_bytes, size=data_size)


                else:
                    return DataContent(resident=False, error="Could not interpret $DATA")

            # For files without any data in it (empty files)
            except struct.error:
                return DataContent(resident=False, error="[*] The File is empty!")

        return DataContent(resident=False, error="No $DATA attribute found")
