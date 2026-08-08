"""macOS camera enumeration via AVFoundation (ctypes, no dependencies).

Uses the exact same AVCaptureDeviceDiscoverySession call that OpenCV's
AVFoundation backend uses, so the returned device order matches OpenCV's
VideoCapture indices one-to-one. Crucially, this only *lists* devices -
nothing is ever opened, so iPhone Continuity Cameras are never activated
during detection.
"""

import ctypes
import ctypes.util
import logging
import sys
from typing import List, Optional, TypedDict

logger = logging.getLogger(__name__)


class CameraInfo(TypedDict):
    name: str
    model: str
    device_type: str
    unique_id: str


_objc = None
_avf = None


def _load_libraries() -> bool:
    global _objc, _avf
    if _objc is not None and _avf is not None:
        return True
    try:
        _objc = ctypes.CDLL(ctypes.util.find_library('objc'))
        _avf = ctypes.CDLL(
            '/System/Library/Frameworks/AVFoundation.framework/AVFoundation'
        )
        _objc.objc_getClass.restype = ctypes.c_void_p
        _objc.objc_getClass.argtypes = [ctypes.c_char_p]
        _objc.sel_registerName.restype = ctypes.c_void_p
        _objc.sel_registerName.argtypes = [ctypes.c_char_p]
        return True
    except Exception as e:
        logger.debug(f"Could not load AVFoundation: {e}")
        _objc = _avf = None
        return False


def _msg(receiver, selector: str, restype, argtypes, *args):
    """Send an Objective-C message with an explicit type signature."""
    proto = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes)
    fn = proto(ctypes.cast(_objc.objc_msgSend, ctypes.c_void_p).value)
    return fn(receiver, _objc.sel_registerName(selector.encode()), *args)


def _const(name: str):
    """Read an exported NSString* constant from AVFoundation."""
    return ctypes.c_void_p.in_dll(_avf, name).value


def _to_str(nsstring) -> str:
    if not nsstring:
        return ""
    utf8 = _msg(nsstring, 'UTF8String', ctypes.c_char_p, [])
    return utf8.decode('utf-8') if utf8 else ""


def list_cameras() -> Optional[List[CameraInfo]]:
    """List video capture devices in OpenCV index order.

    Returns None if enumeration is unavailable (non-macOS, or the
    AVFoundation call failed) so callers can fall back to other detection.
    """
    if sys.platform != 'darwin':
        return None
    if not _load_libraries():
        return None
    try:
        # Match the device set OpenCV sees. Its backend uses the legacy
        # [AVCaptureDevice devicesWithMediaType:] API, which returns
        # built-in, external, and Continuity (iPhone) cameras but NOT
        # Desk View cameras - so Desk View must not occupy index slots
        # here or every device after it would be off by one.
        # (iPhones DO occupy slots; they are only hidden from the UI.)
        # Some constants only exist on newer macOS versions, hence the
        # per-symbol guard.
        types_list = []
        for symbol in (
            'AVCaptureDeviceTypeBuiltInWideAngleCamera',
            'AVCaptureDeviceTypeExternalUnknown',
            'AVCaptureDeviceTypeContinuityCamera',
        ):
            try:
                types_list.append(_const(symbol))
            except ValueError:
                pass
        media_video = _const('AVMediaTypeVideo')

        ns_array_cls = _objc.objc_getClass(b'NSArray')
        buf = (ctypes.c_void_p * len(types_list))(*types_list)
        types_array = _msg(
            ns_array_cls, 'arrayWithObjects:count:', ctypes.c_void_p,
            [ctypes.POINTER(ctypes.c_void_p), ctypes.c_ulong],
            buf, len(types_list),
        )

        disco_cls = _objc.objc_getClass(b'AVCaptureDeviceDiscoverySession')
        session = _msg(
            disco_cls, 'discoverySessionWithDeviceTypes:mediaType:position:',
            ctypes.c_void_p, [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long],
            types_array, media_video, 0,  # 0 = AVCaptureDevicePositionUnspecified
        )
        if not session:
            return None

        devices = _msg(session, 'devices', ctypes.c_void_p, [])
        count = _msg(devices, 'count', ctypes.c_ulong, [])

        cameras: List[CameraInfo] = []
        seen_ids = set()
        for i in range(count):
            dev = _msg(devices, 'objectAtIndex:', ctypes.c_void_p,
                       [ctypes.c_ulong], i)
            unique_id = _to_str(_msg(dev, 'uniqueID', ctypes.c_void_p, []))
            if unique_id in seen_ids:
                continue
            seen_ids.add(unique_id)
            device_type = _to_str(_msg(dev, 'deviceType', ctypes.c_void_p, []))
            # Defensive: never let a Desk View device claim an index slot,
            # whichever discovery type it arrived through.
            if 'DeskView' in device_type:
                continue
            cameras.append(CameraInfo(
                name=_to_str(_msg(dev, 'localizedName', ctypes.c_void_p, [])),
                model=_to_str(_msg(dev, 'modelID', ctypes.c_void_p, [])),
                device_type=device_type,
                unique_id=unique_id,
            ))

        # CRITICAL: OpenCV's AVFoundation backend sorts devices by uniqueID
        # ("Preserve devices ordering on the system" in
        # cap_avfoundation_mac.mm), so VideoCapture(n) opens the n-th device
        # of the uniqueID-sorted list - NOT the discovery order.
        cameras.sort(key=lambda c: c['unique_id'])
        return cameras
    except Exception as e:
        logger.debug(f"AVFoundation camera enumeration failed: {e}")
        return None
