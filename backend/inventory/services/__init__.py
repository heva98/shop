"""Stock-keeping use cases a manager drives directly.

    adjustments  write stock off (expired, broken, stolen) or correct an entry
    counts       a physical stock take: start, count, submit, approve

Movements made by other modules (sales, receiving, transfers) go through
inventory.stock instead."""
