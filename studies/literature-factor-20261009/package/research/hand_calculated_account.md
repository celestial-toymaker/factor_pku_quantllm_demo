# Independently calculated fixture

This invented ledger verifies arithmetic only. It is not market evidence. Initial cash CNY10,000; slippage zero; position cap relaxed solely for this unit test. After August 28, 2023 the configured transfer fee is 0.001% per side and stamp tax is 0.05% on sells; commission minimum is CNY5.

| Action | Shares | Notional | Commission | Transfer | Stamp | Cash after |
|---|---:|---:|---:|---:|---:|---:|
| Buy 100 at CNY10 | 100 | 1,000 | 5 | 0.010 | 0 | 8,994.990 |
| Next-day sell 100 at CNY11 | 0 | 1,100 | 5 | 0.011 | 0.550 | 10,089.429 |

Total fees: CNY10.571. Ending equity equals cash. `test_independent_hand_account` checks these independently derived constants, rather than comparing the implementation with itself. Other fixtures test cash denial, T+1, both opening limits, entitlement record dates, delayed cash and bonus availability, missing execution, calendar labels and future-data perturbations.
