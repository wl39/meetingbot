"""A process-owned data directory lock on Windows, macOS and Linux."""

import os


def acquire_process_lock(path):
    handle = open(path, "a+b")
    try:
        if os.name == "nt":
            import msvcrt

            # Windows locks a byte range; ensure byte zero exists before locking it.
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise RuntimeError("Only one RAG process can own this data directory") from None
    # Both platforms release the process lock when this file descriptor closes.
    return handle
