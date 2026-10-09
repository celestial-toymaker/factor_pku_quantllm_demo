# Reproduction

Use Python 3.11.11 and the supplied exact dependency lock. From this `package` directory:

```sh
uv venv --python 3.11.11 .venv
uv pip sync --python .venv/bin/python requirements.lock
uv pip install --python .venv/bin/python --no-deps --no-build-isolation -e .
.venv/bin/python -m pytest -q
.venv/bin/python -m factorlab.cli --root . verify
```

The offline suite uses explicitly synthetic fixtures. The verifier reads existing metrics and checks the package, original freeze evidence, unchanged scientific modules and declared presentation changes. It does not read market labels or run a portfolio.

The report command reads the recorded metrics only. Run it in a disposable copy because intentional regeneration changes presentation files and invalidates the shipped file checksum manifest:

```sh
.venv/bin/python -m factorlab.cli --root . report
```

The 25 original research tests passed. This publication copy includes eight integrity tests that reject modified scientific modules, metrics, method documentation, exposure facts or original-hash evidence and confirm that the old finalist cannot be reopened from the presentation copy. The full historical pipeline was reproduced in an isolated pinned environment, with exact equality of candidate results and diagnostics. The retained record is `results/fresh_reproduction_verification.json`; actual run logs are included. Full empirical reproduction requires lawful access to the recorded private input files. Vendor revisions must be treated as changed inputs rather than silently substituted. This shareable archive alone cannot recreate those inputs.

## Publication copy and research freeze

The scientific Python modules and result metrics are byte-identical to the completed study. Only `report.py`, `verify.py`, the declared method-document presentation and the identity/citation fields of the exposure ledger differ from the original frozen set. The publication verifier reconstructs the original module hash from the retained individual hashes, checks it against the original protocol freeze, and checks every unchanged scientific module against that evidence. It also checks the publication versions of the two presentation modules and the edited documents. Exposure dates and research facts are checked separately from the redacted identity and citation fields. The invalidated first-version exposure ledger receives the same narrow redaction; its original freeze and numeric results remain unchanged.

The original research guard still compares the complete code freeze. Consequently, a historical or final evaluation cannot be resumed directly from this presentation copy using the old freeze. To run a new independent study, use a fresh root, lawfully acquired inputs, and a new protocol freeze; that run is a new experiment. The recorded original historical replay used the original source, whose aggregate hash is retained. No validation or final portfolio was rerun to create this publication preview.

## Recorded evaluation boundary

The selected method received one final portfolio evaluation on September 21–24 and 28–30, 2026. The earlier acquisition gate stopped before portfolio evaluation and was resumed after an issuer-confirmed dividend supplement; both events remain in the access record. `research/protocol_deviations.md` explains the correction. Repeating the completed final experiment is not part of ordinary reproduction.

CLI exit 0 means the command completed, exit 2 means a gate blocked it, and exit 3 records an exception. Completion is separate from validation qualification. Historical exposure, seven-session sample size, daily-bar opening-fill approximations and vendor revision limits are documented with the measured results.

The [review checklist](release/review_checklist.md) links the current assignment evidence. The gross/net accounting table reads recorded metrics only.
