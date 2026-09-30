"""Compatibility shim: the implementation moved to radar/legacy/job_pages.py."""
import sys

from radar.legacy import job_pages as _impl

sys.modules[__name__] = _impl
