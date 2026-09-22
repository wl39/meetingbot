"""Windows file access without following junctions or symbolic links.

Retain read-only, non-share-delete handles for every ancestor until the operation
finishes. Directory enumeration uses the pinned path because Windows scandir
does not accept the Unix directory file descriptors used by the other platforms.
"""

import os
from contextlib import contextmanager


@contextmanager
def opened_windows(root, parts, file=False):
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL

    class FileInfo(ctypes.Structure):
        _fields_ = [
            ("attributes", wintypes.DWORD),
            ("created", wintypes.FILETIME),
            ("accessed", wintypes.FILETIME),
            ("written", wintypes.FILETIME),
            ("volume", wintypes.DWORD),
            ("size_high", wintypes.DWORD),
            ("size_low", wintypes.DWORD),
            ("links", wintypes.DWORD),
            ("index_high", wintypes.DWORD),
            ("index_low", wintypes.DWORD),
        ]

    kernel.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(FileInfo)]
    kernel.GetFileInformationByHandle.restype = wintypes.BOOL
    handles, fd = [], None
    try:
        target = root.joinpath(*parts)
        # Local drives and UNC shares have an anchor; never use a drive-relative path.
        if not target.is_absolute():
            raise OSError("absolute source required")
        paths = [*reversed(target.parents), target]
        for index, path in enumerate(paths):
            final_file = file and index == len(paths) - 1
            handle = kernel.CreateFileW(
                str(path),
                0x80000000 if final_file else 0x0081,  # GENERIC_READ / LIST_DIRECTORY + READ_ATTRIBUTES
                0x00000001,  # FILE_SHARE_READ: deny replacement and reparse-point mutation
                None,
                3,  # OPEN_EXISTING
                0x02200000,  # BACKUP_SEMANTICS | OPEN_REPARSE_POINT
                None,
            )
            if handle == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            handles.append(handle)
            info = FileInfo()
            if not kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
                raise ctypes.WinError(ctypes.get_last_error())
            if info.attributes & 0x0400:  # FILE_ATTRIBUTE_REPARSE_POINT (including junctions)
                raise OSError("reparse points are excluded")
            is_directory = bool(info.attributes & 0x0010)
            if is_directory == final_file:
                raise OSError("source type mismatch")
        if file:
            fd = msvcrt.open_osfhandle(handles[-1], os.O_RDONLY | os.O_BINARY)
            handles.pop()  # The CRT descriptor now owns the final file handle.
            yield fd
        else:
            yield target
    finally:
        if fd is not None:
            os.close(fd)
        for handle in reversed(handles):
            kernel.CloseHandle(handle)
