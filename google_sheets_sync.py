"""Compatibility shim: the implementation moved to radar/legacy/google_sheets_sync.py."""
import sys

from radar.legacy import google_sheets_sync as _impl

sys.modules[__name__] = _impl
