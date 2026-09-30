"""Compatibility shim: the implementation moved to radar/legacy/opportunity_monitor.py.

Importing this module returns the real module object (so tests and callers that
patch attributes keep working); running it as a script runs the legacy CLI.
"""
import sys

from radar.legacy import opportunity_monitor as _impl

if __name__ == "__main__":
    _impl.cli()
else:
    sys.modules[__name__] = _impl
