"""Cost measurement, pricing, and budget enforcement.

`pricing` is pure arithmetic and knows nothing about the database. `governor` decides
whether a call may proceed. `ledger` records what it actually cost. Keeping them apart is
what lets the arithmetic be tested exhaustively at $0 (ADR-0020).
"""
