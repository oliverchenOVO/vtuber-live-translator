"""WASAPI process-tree loopback using the documented ActivateAudioInterfaceAsync API.

The virtual endpoint is VAD\\Process_Loopback. This module deliberately has no
filesystem or Qt dependencies. Call ``capture`` on a dedicated MTA thread.
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import POINTER, Structure, byref, c_int, c_long, c_ubyte, c_uint32, c_uint64, c_void_p
from ctypes.wintypes import DWORD, HANDLE
from typing import Callable

import comtypes
from comtypes import COMMETHOD, COMObject, GUID, HRESULT, IUnknown
from pycaw.api.audioclient import IAudioClient
from pycaw.api.audioclient.depend import WAVEFORMATEX


PROCESS_LOOPBACK_DEVICE = "VAD\\Process_Loopback"
AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK = 1
PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE = 0
AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
AUDCLNT_STREAMFLAGS_EVENTCALLBACK = 0x00040000
AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM = 0x80000000
AUDCLNT_BUFFERFLAGS_SILENT = 0x00000002
VT_BLOB = 65
WAIT_OBJECT_0 = 0


class ProcessLoopbackParams(Structure):
    _fields_ = [("TargetProcessId", DWORD), ("ProcessLoopbackMode", c_int)]


class ActivationParams(Structure):
    _fields_ = [("ActivationType", c_int), ("ProcessLoopbackParams", ProcessLoopbackParams)]


class Blob(Structure):
    _fields_ = [("cbSize", c_uint32), ("pBlobData", c_void_p)]


class BlobPropVariant(Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("wReserved1", ctypes.c_ushort),
                ("wReserved2", ctypes.c_ushort), ("wReserved3", ctypes.c_ushort),
                ("blob", Blob)]


class IActivateAudioInterfaceAsyncOperation(IUnknown):
    _iid_ = GUID("{72A22D78-CDE4-431D-B8CC-843A71199B6D}")
    _methods_ = (COMMETHOD([], HRESULT, "GetActivateResult",
                           (["out"], POINTER(HRESULT), "activateResult"),
                           (["out"], POINTER(POINTER(IUnknown)), "activatedInterface")),)


class IActivateAudioInterfaceCompletionHandler(IUnknown):
    _iid_ = GUID("{41D949AB-9862-444A-80F6-C261334DA5EB}")
    _methods_ = (COMMETHOD([], HRESULT, "ActivateCompleted",
                           (["in"], POINTER(IActivateAudioInterfaceAsyncOperation), "operation")),)


class IAgileObject(IUnknown):
    _iid_ = GUID("{94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90}")
    _methods_ = ()


class ActivationHandler(COMObject):
    _com_interfaces_ = (IActivateAudioInterfaceCompletionHandler, IAgileObject)

    def __init__(self):
        super().__init__()
        self.event = threading.Event()

    def ActivateCompleted(self, operation):
        # The async operation itself retains this handler. Keeping operation here
        # creates a COM reference cycle that Python GC cannot break (16 handles
        # leaked per activation on Windows 11). The caller already owns operation.
        self.event.set()
        return 0


class IAudioCaptureClient(IUnknown):
    _iid_ = GUID("{C8ADBD64-E71E-48a0-A4DE-185C395CD317}")
    _methods_ = (
        COMMETHOD([], HRESULT, "GetBuffer",
                  (["out"], POINTER(POINTER(c_ubyte)), "data"),
                  (["out"], POINTER(c_uint32), "frames"),
                  (["out"], POINTER(DWORD), "flags"),
                  (["out"], POINTER(c_uint64), "devicePosition"),
                  (["out"], POINTER(c_uint64), "qpcPosition")),
        COMMETHOD([], HRESULT, "ReleaseBuffer", (["in"], c_uint32, "frames")),
        COMMETHOD([], HRESULT, "GetNextPacketSize", (["out"], POINTER(c_uint32), "frames")),
    )


_mmdevapi = ctypes.WinDLL("Mmdevapi.dll")
_mmdevapi.ActivateAudioInterfaceAsync.argtypes = (
    ctypes.c_wchar_p, POINTER(GUID), c_void_p,
    POINTER(IActivateAudioInterfaceCompletionHandler),
    POINTER(POINTER(IActivateAudioInterfaceAsyncOperation)),
)
_mmdevapi.ActivateAudioInterfaceAsync.restype = c_long

_kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
_kernel32.CreateEventW.argtypes = (c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p)
_kernel32.CreateEventW.restype = HANDLE
_kernel32.WaitForSingleObject.argtypes = (HANDLE, DWORD)
_kernel32.WaitForSingleObject.restype = DWORD
_kernel32.CloseHandle.argtypes = (HANDLE,)
_kernel32.CloseHandle.restype = ctypes.c_int


def _check_hr(hr: int, action: str) -> None:
    if hr < 0:
        raise OSError(f"{action} failed: HRESULT 0x{hr & 0xffffffff:08X}")


def activate_process_loopback(pid: int) -> POINTER(IAudioClient):
    params = ActivationParams(AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK,
                              ProcessLoopbackParams(pid, PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE))
    variant = BlobPropVariant()
    variant.vt = VT_BLOB
    variant.blob = Blob(ctypes.sizeof(params), ctypes.cast(byref(params), c_void_p))
    handler = ActivationHandler()
    operation = POINTER(IActivateAudioInterfaceAsyncOperation)()
    iid = IAudioClient._iid_
    hr = _mmdevapi.ActivateAudioInterfaceAsync(
        PROCESS_LOOPBACK_DEVICE, byref(iid), byref(variant),
        handler.QueryInterface(IActivateAudioInterfaceCompletionHandler), byref(operation),
    )
    _check_hr(hr, "ActivateAudioInterfaceAsync")
    if not handler.event.wait(8):
        raise TimeoutError("Windows did not complete process audio activation within 8 seconds")
    result_hr, unknown = operation.GetActivateResult()
    _check_hr(result_hr, "Process audio activation")
    return unknown.QueryInterface(IAudioClient)


def capture(pid: int, stop: threading.Event, on_pcm: Callable[[bytes], None],
            ready: Callable[[], None], alive: Callable[[], bool] = lambda: True) -> None:
    """Capture 44.1 kHz stereo signed 16-bit PCM in 20 ms event-driven packets."""
    comtypes.CoInitializeEx(0)  # MTA; completion callback also arrives on an MTA worker.
    event = None
    client = None
    try:
        client = activate_process_loopback(pid)
        fmt = WAVEFORMATEX()
        fmt.wFormatTag = 1  # WAVE_FORMAT_PCM
        fmt.nChannels = 2
        fmt.nSamplesPerSec = 44100
        fmt.wBitsPerSample = 16
        fmt.nBlockAlign = 4
        fmt.nAvgBytesPerSec = 44100 * 4
        fmt.cbSize = 0
        flags = (AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_EVENTCALLBACK
                 | AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM)
        client.Initialize(0, flags, 200_000, 0, byref(fmt), None)
        service = client.GetService(byref(IAudioCaptureClient._iid_))
        capture_client = service.QueryInterface(IAudioCaptureClient)
        event = _kernel32.CreateEventW(None, 0, 0, None)
        if not event:
            raise ctypes.WinError(ctypes.get_last_error())
        client.SetEventHandle(event)
        client.Start()
        ready()
        while not stop.is_set():
            if not alive():
                raise ProcessLookupError(f"Audio source process {pid} closed")
            if _kernel32.WaitForSingleObject(event, 100) != WAIT_OBJECT_0:
                continue
            while True:
                packet_frames = capture_client.GetNextPacketSize()
                if not packet_frames:
                    break
                data, frames, packet_flags, _, _ = capture_client.GetBuffer()
                try:
                    count = frames * fmt.nBlockAlign
                    pcm = bytes(count) if packet_flags & AUDCLNT_BUFFERFLAGS_SILENT else ctypes.string_at(data, count)
                    on_pcm(pcm)
                finally:
                    capture_client.ReleaseBuffer(frames)
    finally:
        if client is not None:
            try:
                client.Stop()
            except OSError:
                pass
        if event:
            _kernel32.CloseHandle(event)
        comtypes.CoUninitialize()
