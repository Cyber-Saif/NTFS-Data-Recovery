# NTFS Data Recovery Tool
This is a simple Python program that attempts to recover deleted files from a given drive/volume/disk. It scans each record inside the Master File Table (MFT) for the flagged deleted files. NTFS creates a record in the MFT for each file that exists or existed on the disk.

When a file is deleted, NTFS changes the flag in the header field of the record to mark it as deleted. An MFT record is 1024 bytes each. The first 56 bytes are reserved for the header field, and the rest are for attributes. The header field contains information such as whether it is a folder or a file, whether it is a used or unused file/data. An unused label indicates that the file is marked as deleted, and the data can be overwritten. The data remains on the disk until it gets overwritten by a new file. When a new file is created or new data is added to the disk, it will overwrite the data whose MFT record's flag is marked as unused.

The attribute field contains information such as `timestamp`, `file name`, and `data` field. If the data is resident (a small amount of data), then the record stores that data inside the `data` field of the record. If the data is non-resident (large data), then the `data` field stores the `data runs` (address) of the data that is stored on the disk.

This program can recover both resident and non-resident data. However, it can not recover overwritten files/data.

# Required Libraries
This program doesn't need any external libraries for its core functionality. However, for an interactive CLI UI, it currently uses a rich library.
```
pip install rich
```

# Usage
By default, it will recover files to the `recover` folder.
```Python
python main.py --drive \\.\D:
```
Custom destination folder.
```Python
python main.py --drive \\.\D: --output "C:\Users\Desktop\output\"
# or you can specify another disk as the destination
```
