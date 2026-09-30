# T11: Hardening and docs
**Context:** 00-overview.md; test suite layout.
**Deliver:** end-to-end test with recorded fixtures (source -> pipeline -> alert -> API), load test (1000 fake boards), failure-injection (source 500s, DB locked, LLM down, channel down), structured JSON logging, secrets scan in CI, README rewrite (architecture, setup in 15 min, config reference), runbook (session expired, source blocked, restore backup).
**Accept:** CI green; load test sustains target poll rate with < 5% CPU idle budget used; every failure-injection case degrades without losing or duplicating an alert.
