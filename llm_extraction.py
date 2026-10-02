"""Compatibility shim: the implementation moved to radar/legacy/llm_extraction.py."""
import sys

from radar.legacy import llm_extraction as _impl

sys.modules[__name__] = _impl
