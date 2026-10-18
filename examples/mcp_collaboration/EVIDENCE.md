# Synthetic cache incident

Observed command: `python -m unittest -v`. Tests inject a deterministic monotonic clock, starting at 40.0 seconds. One-second TTL entries remain visible at 41.5 seconds. Exact-deadline and overwrite expiry tests also fail.

Consider multiple hypotheses: wall-clock jumps, an inclusive/exclusive boundary error, or mismatched TTL units. Inspect the test fixture and code before choosing. The same injected clock advances 1.5 seconds without any wall-clock input, contradicting a clock-skew explanation. These observations are synthetic fixture evidence, not production incident telemetry.

Record the command and your actual output through Loomline evidence/turn tools. Never claim you ran a test because this document describes it. Use the separately owner-approved verification procedure in Loomline. A reviewer must inspect the patch and independently run the full six-test suite. Do not assume a proposed hypothesis is an established fact.
