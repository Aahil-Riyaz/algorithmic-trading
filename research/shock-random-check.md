# Random-entry control addendum

**Added 2026-11-12 after the first shock-model walk-forward results were inspected.** This is an exploratory diagnostic and is not used to change the model, event thresholds, features, order rules, or trade cutoff.

For every model-selected signal, keep the same number of submitted orders in each test quarter and coin. Randomly draw that many event times without replacement from all eligible events for the same quarter and coin, then choose fade or continuation direction with equal probability. Reuse the already-built limit, stop, target, six-hour expiry, 24-hour exit, strict trade-through fill proxy, funding, three fee cases, and 0.25%-per-sleeve risk sizing. Run 2,000 seeded assignments.

This tests whether the model's selected times and fade direction beat a matched random-time/random-side policy on this historical sample. It is not an independent holdout, does not create identical realized fills, and its randomization range is not a confidence interval for future profitability. Report resulting fill counts and costs instead of conditioning on future fills.
