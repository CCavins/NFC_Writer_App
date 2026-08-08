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
        # Same device-type list as OpenCV's cap_avfoundation_mac.mm, so
        # positions in this array equal OpenCV VideoCapture indices.
        types_list = [
            _const('AVCaptureDeviceTypeBuiltInWideAngleCamera'),
            _const('AVCaptureDeviceTypeExternalUnknown'),
        ]
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
        for i in range(count):
            dev = _msg(devices, 'objectAtIndex:', ctypes.c_void_p,
                       [ctypes.c_ulong], i)
            cameras.append(CameraInfo(
                name=_to_str(_msg(dev, 'localizedName', ctypes.c_void_p, [])),
                model=_to_str(_msg(dev, 'modelID', ctypes.c_void_p, [])),
                device_type=_to_str(_msg(dev, 'deviceType', ctypes.c_void_p, [])),
            ))
        return cameras
    except Exception as e:
        logger.debug(f"AVFoundation camera enumeration failed: {e}")
        return None
