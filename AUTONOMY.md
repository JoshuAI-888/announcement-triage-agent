# AUTONOMY.md — execution contract for autonomous batches

**Read together with `SPEC.md`. Where they conflict, `SPEC.md` wins.**

This file governs how you work when I ask you to run a batch autonomously.
It does not change what to build — only how to build it, verify it, and when
to stop and ask.

---

## 1. The loop

For **every sub-step** inside a batch, in this order. Do not reorder.

```
1. WRITE THE CHECK FIRST
   Create an executable assertion in checks/check_<name>.py that will fail
   right now, before the implementation exists.

2. IMPLEMENT
   Write the minimum code to satisfy the check. No extras.

3. RUN
   Execute the check. Capture the output.

4. BRANCH
   PASS -> append to PROGRESS.md, git commit, move to next sub-step.
   FAIL -> diagnose, fix, return to step 3.

5. BOUND
   Three failed attempts on the same check -> STOP.
   Write the diagnosis to PROGRESS.md and ask me.
   Do NOT loosen the check to make it pass.
   Do NOT stub, mock, or hardcode a value to satisfy it.
```

Weakening a check to get a green result is the single worst failure mode
available to you here. If a check is genuinely wrong, say so and propose the
corrected check — do not silently rewrite it.

---

## 2. Checks are executable, not narrative

Every check is a Python file under `checks/` that exits non-zero on failure
and prints what it asserted. "I verified this looks correct" is not a check.

Checks are cheap and permanent. Never delete one. `python -m checks.run_all`
must always run every check written so far, so later work cannot silently
break earlier work.

---

## 3. PROGRESS.md

Maintain `PROGRESS.md` at the repo root. Append one block per sub-step:

```
## <batch>.<step> <name>
status: pass | fail | blocked
check: checks/check_<name>.py
result: <one line — what the check asserted and what it returned>
commit: <sha>
notes: <anything I need to know; blank if nothing>
```

Update it as you go, not at the end. If the session resets, this file plus
`git log` is how you recover state.

---

## 4. Stop conditions — halt and ask, do not improvise

Stop immediately and write the reason to `PROGRESS.md` if any of these occur:

| # | Condition |
|---|---|
| S1 | Three failed attempts on the same check |
| S2 | The external data source returns errors, blocks requests, requires authentication, or its terms are unclear |
| S3 | `SPEC.md` is ambiguous or contradicts what the data actually contains |
| S4 | A task would require creating, modifying, or inferring anything under `data/gold/` |
| S5 | Making a check pass would require changing the check itself |
| S6 | A dependency not listed in `SPEC.md` §3 appears necessary |
| S7 | Cumulative API spend during the batch exceeds the cap in §6 |
| S8 | You are about to implement something outside the requested batch |

On any stop: report what you completed, what is blocked, what you tried, and
what you recommend. Then wait. Do not proceed to the next sub-step.

---

## 5. Hard prohibitions

These hold in every batch, without exception.

1. **Never create, modify, populate, infer, or suggest values for anything
   under `data/gold/` except an unlabelled `candidates.csv`.** Every
   `label_*` column, `slice_tag` and `difficulty` stays empty. An
   agent-labelled gold set makes the entire evaluation worthless.
2. **Never weaken, delete, or skip a check to produce a passing result.**
3. **Never `git push`, `git reset --hard`, `git rebase`, force-push, or
   rewrite history.** Commit forward only.
4. **Never print, log, or commit the API key.**
5. **Never implement beyond the requested batch**, however obvious the next
   step seems.
6. **Never introduce a dependency** outside `SPEC.md` §3 without stopping first.

---

## 6. Cost discipline

Autonomous loops can burn API spend fast. During a build batch:

- Test against a maximum of **5 records**, never the full corpus
- Never run the full 60-item eval as part of a build loop — the eval runs
  once, at the end of the batch, when I ask for it
- Use `--dry-run` wherever the code path allows
- Log cumulative spend for the batch to `PROGRESS.md` after each sub-step
- **Batch spend cap: NZ$3.00.** Exceeding it is stop condition S7

---

## 7. Batch graph

Dependencies. Nothing starts until its predecessors are green.

```
  A1 skeleton + schemas
        |
  A2 store + fetch  ---- (S2 escape: feed fails -> switch adapter to EDGAR)
        |
  A3 normalise + doc_type map + stub adapter
        |
  A4 export candidates.csv (UNLABELLED)
        |
  === HUMAN GATE: I label the gold set ===
        |
  B1 classify + prompt v1
        |
  B2 guardrails G1 G2 G6 + synthetic fixtures
        |
  B3 eval harness + run manifest
        |
  B4 baselines (flag_all, rules, naive_prompt)
        |
  === HUMAN GATE: I read the v1 scorecard ===
        |
  C1 rank + brief + run CLI
        |
  C2 prompt v2 (needs my RUBRIC.md)   -> eval
        |
  C3 prompt v3 (contamination check)  -> eval
        |
  === HUMAN: README + failure taxonomy ===
```

`B2` and `B3` are independent of each other and may be built in either
order, but both must be green before `B4`.

---

## 8. Time budget

Report elapsed time per sub-step in `PROGRESS.md`.

| Batch | Budget | If exceeded |
|---|---|---|
| A | 2.5h | Stop. If `A2` is the blocker, switch the adapter to SEC EDGAR and tell me — do not keep grinding on the original feed |
| B | 3.0h | Stop and report which sub-step consumed it |
| C | 1.5h | Stop and report |

The time budgets are stop conditions, not targets. Hitting one is
information, not failure.

---

## 9. Reporting at batch end

When a batch completes, give me exactly this and nothing more:

1. Sub-steps completed, with check names and results
2. Anything blocked or skipped, with the reason
3. Cumulative API spend and elapsed time
4. The single command I run to verify the whole batch myself
5. Anything in `SPEC.md` you found ambiguous, wrong, or worth changing

No summary of the code you wrote. I can read the diff.
