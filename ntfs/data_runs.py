def decode_data_runs(raw_runs: bytes) -> list[tuple[int, int]]:
    """
    Decode a non-resident data run list into (start_cluster, length) pairs.
    """
    data_cluster_offset = []
    current_cluster = 0
    run_count = 0

    while True:
        header = raw_runs[run_count]
        if header == 0x00:
            break
        run_count+=1

        # Low Nibble - number of bytes used to encode the run LENGTH
        # High Nibble - number of bytes used to encode the run OFFSET (delta)

        # 0x0F in binary is '00001111'. Using AND Logic to eliminate high nibble
        # Size/Bytes of the length field
        len_bytes = header & 0x0F

        # Bytes (size) of the offset
        offset_bytes = (header >> 4) & 0x0F

        # No. of used clusters
        run_length = int.from_bytes(raw_runs[run_count: run_count + len_bytes], 'little', signed=False)
        run_count+= len_bytes

        if offset_bytes == 0:
            # For sparse run offset = 0 means clusters are unallocated
            run_offset = 0
            # mark sparse runs with None
            start_cluster = None
        else:
            # First cluster offset for the run
            run_offset = int.from_bytes(raw_runs[run_count: run_count + offset_bytes], 'little', signed=True)
            run_count += offset_bytes
            current_cluster += run_offset
            start_cluster = current_cluster

            data_cluster_offset.append((start_cluster, run_length))

    return data_cluster_offset
