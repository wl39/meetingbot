"""Exercise Windows handle ownership/reparse rejection with a fake Win32 API.

These tests do not substitute for running the installer and sources on Windows.
"""

import ctypes
import os
import sys
from pathlib import PureWindowsPath
from types import SimpleNamespace

import pytest

from meetingbot_rag.windows_sources import opened_windows


@pytest.fixture
def windows_kernel(monkeypatch):
    calls, closed = [], []
    state = {"reparse": None, "file": False, "fail": None}

    def create(path, access, share, security, creation, flags, template):
        calls.append((path, access, share, flags))
        return len(calls)

    def info(handle, output):
        output._obj.attributes = 0x0010
        if state["file"] and str(calls[handle - 1][0]).endswith("notes.txt"):
            output._obj.attributes = 0
        if handle == state["reparse"]:
            output._obj.attributes |= 0x0400
        return True

    def close(handle):
        closed.append(handle)
        return True

    api = SimpleNamespace(CreateFileW=create, GetFileInformationByHandle=info, CloseHandle=close)
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: api, raising=False)
    monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace())
    return calls, closed, state


def test_directory_ancestors_stay_locked_until_enumeration_finishes(windows_kernel):
    calls, closed, _ = windows_kernel
    with opened_windows(PureWindowsPath("C:/Users/reader"), ["notes"]) as path:
        assert path == PureWindowsPath("C:/Users/reader/notes")
        assert [item[0] for item in calls] == ["C:\\", "C:\\Users", "C:\\Users\\reader", str(path)]
        assert all(item[1:] == (0x0081, 1, 0x02200000) for item in calls)
        assert closed == []
    assert closed == [4, 3, 2, 1]


@pytest.mark.parametrize("reparse", [1, 2, 4])
def test_reparse_point_in_any_ancestor_or_target_is_rejected(windows_kernel, reparse):
    calls, closed, state = windows_kernel
    state["reparse"] = reparse
    with pytest.raises(OSError, match="reparse points"):
        with opened_windows(PureWindowsPath("C:/Users/reader"), ["notes"]):
            pytest.fail("must reject reparse point before yielding access")
    assert len(calls) == reparse
    assert closed == list(reversed(range(1, reparse + 1)))


def test_file_handle_ownership_passes_to_descriptor_and_closes_once(windows_kernel, tmp_path, monkeypatch):
    calls, closed, state = windows_kernel
    state["file"] = True
    note = tmp_path / "notes.txt"
    note.write_bytes(b"bounded document")
    fd = os.open(note, os.O_RDONLY)
    transferred = []

    def transfer(handle, flags):
        transferred.append(handle)
        return fd

    monkeypatch.setattr(os, "O_BINARY", 0, raising=False)
    sys.modules["msvcrt"].open_osfhandle = transfer
    with opened_windows(PureWindowsPath("C:/Users/reader"), ["notes.txt"], file=True) as opened:
        assert os.read(opened, 100) == b"bounded document"
        assert calls[-1][1] == 0x80000000
        assert transferred == [4] and not closed
    with pytest.raises(OSError):
        os.fstat(fd)
    assert closed == [3, 2, 1]


def test_windows_directory_handles_release_on_consumer_error(windows_kernel):
    _, closed, _ = windows_kernel
    with pytest.raises(RuntimeError):
        with opened_windows(PureWindowsPath("C:/Users/reader"), []):
            raise RuntimeError("enumeration stopped")
    assert closed == [3, 2, 1]
