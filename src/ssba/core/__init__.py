"""Core decryption/scanning engine.

Nothing in this package performs I/O side effects beyond what the caller
explicitly passes in (paths to read, bytes to return) — no printing, no
deciding where output goes. That's the CLI's job.
"""
