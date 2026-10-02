"""Compatibility shim: the implementation moved to radar/legacy/instagram_scraper.py."""
import sys

from radar.legacy import instagram_scraper as _impl

sys.modules[__name__] = _impl
