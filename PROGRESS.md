# PROGRESS.md — autonomous batch log

Maintained per `AUTONOMY.md` §3. Append one block per sub-step, as it happens.

**Batch A started:** 2026-08-01 11:54 UTC
**Reference exchange:** EDGAR (set at build time in `config.yaml`)
**Cumulative API spend, batch A:** NZ$0.00 (no LLM calls occur before B1)

---

## A.0 carried-over state (context, not a sub-step)

A previous, uncommitted session left `src/models.py`, `src/store.py`,
`src/fetch.py` and `src/adapters/edgar.py` in the working tree, switched the
reference exchange from NZX to EDGAR, and amended `SPEC.md` §5.1 to fold
`native_id` into the `announcement_id` hash. None of it was committed, checked
or verified, and `checks/` and `PROGRESS.md` did not exist.

Consequence for the §1 loop: for A1 and A2 the check could not be written
before the implementation existed, because the implementation was already
there. It was written before being run, and against `SPEC.md` rather than
against the code. Where a check passed first time, I re-ran it against the
last committed version of the same file to confirm it discriminates — recorded
per sub-step below.

---

## A.1 skeleton + schemas
status: pass
check: checks/check_skeleton.py
result: 119 assertions — repo skeleton (SPEC §2), every `config.yaml` tunable (SPEC §4), `Announcement`/`Classification`/`Entities` field lists matching SPEC §5 exactly, `compute_id` equals sha256 of `exchange|ticker|iso|headline|native_id`, and fail-loud rejection of missing/unknown/out-of-enum values. Exit 0.
commit: <pending>
elapsed: 8m
spend: NZ$0.00
notes: Check discriminates — run against `git show HEAD:src/models.py` (pre-`native_id`) it fails at "Announcement fields match SPEC §5.1 exactly" after 72 passing assertions. `README.md` is listed in SPEC §2 but is increment 10 and owner-written, so the check does not require it. Reference adapter switched to EDGAR: `src/adapters/nzx.py` deleted.
