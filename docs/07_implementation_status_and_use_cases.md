# Mini-Hyra Phase 1 Status and Practical Uses

## What is implemented

Mini-Hyra has a versioned task contract, canonical `solution/solve.sh` package
format, package/manifest validation, immutable solution persistence, a
deterministic evaluator interface, an append-only Experience Bank, bounded
proposal workers, and task-specific score comparison. The orchestrator records
every completed proposal attempt and returns the best valid result for the same
task and evaluator version.

Strict execution is fail-closed. It requires a real administrator-provided
`MINI_HYRA_HARDENED_LAUNCHER` executable; otherwise it returns a security
violation before running proposal code. This checkout therefore supports safe
contract validation and deterministic component testing immediately, but it
must not execute untrusted packages in strict mode until that launcher exists.

## Remaining scope before production use

The Experience Bank has atomic append and strict record validation, but its
advanced retention/pruning and semantic retrieval ranking are still a Phase 2
improvement. Antigravity is an optional adapter and needs fixture-based
end-to-end tests before a live subscription is relied on. A task-specific
evaluator remains the responsibility of each benchmark; Mini-Hyra deliberately
does not invent one from prose.

## Good uses now

- Optimize a deterministic algorithm, such as sorting, scheduling, parsing, or
  a numerical kernel, against a trusted runtime or score evaluator.
- Search small, reproducible parameter configurations for a local training or
  simulation benchmark.
- Compare generated implementation variants against regression tests and a
  measurable objective such as latency, memory use, throughput, or solution
  quality.
- Build an evidence-backed experimentation loop where every candidate, metric,
  log excerpt, and artifact manifest can be audited later.

## Not appropriate without more infrastructure

- Unrestricted internet research or tasks needing credentials.
- Large model training, long-running scientific workloads, or expensive GPU
  experiments without a task profile and a hardened execution backend.
- Safety-critical, financial, medical, or production deployment decisions
  without independently reviewed evaluators and stronger isolation.

## Minimal task shape

```text
TaskContract + trusted evaluator
  -> proposal writes solution/solve.sh
  -> hardened sandbox executes it
  -> evaluator checks validity and emits a numeric objective
  -> Experience Bank retains the attempt and best valid result
```

Start with a 10–30 iteration, deterministic micro-benchmark. It exercises the
full loop while keeping evaluation inexpensive and results comparable.
