# Applying Mini-Hyra to Existing E: Projects

Mini-Hyra should be applied as a benchmark harness around one measurable,
reproducible subsystem at a time. It should not rewrite or execute an entire
project directory automatically.

## Recommended order

### 1. `E:\trading\Vibe-Trading`

Best first candidate for a CPU/GPU comparison because it already has a Python
package, backtesting, numerical libraries, and agent workflows. Start with a
read-only benchmark for one indicator/factor pipeline or a small backtest:

- metric: wall time, throughput, and peak memory;
- baseline: existing implementation on a fixed dataset;
- GPU variant: only a bounded NumPy/CuPy/PyTorch kernel or inference step;
- keep network and broker/market-data access disabled;
- do not use the harness to make or approve trades.

Use one GPU worker on the RTX 3050 and a 4–5 GiB VRAM ceiling in the launcher.

### 2. `E:\OllamaModels`

This is a good inference benchmark source. Benchmark a fixed prompt set and
model with warm-up excluded and included as separate metrics. Record model
digest, quantization, context length, tokens/second, first-token latency, and
VRAM use. Keep prompts and outputs local; do not put private data into an
external evaluator.

### 3. `E:\strix`

Use CPU-first benchmarks for scanner throughput, parsing, report generation,
and tool latency. GPU is appropriate only for a clearly isolated local model
inference component. Do not give a proposal unrestricted access to scan targets,
credentials, Docker, or network tools.

### 4. `E:\Piks-Focus` and `E:\piks-focus-web`

The Flutter/Next.js application paths are primarily UI, API, and database work;
GPU optimization will not improve ordinary page rendering or CRUD latency. Use
Mini-Hyra for deterministic image transforms, recommendation/ranking logic, or
local embedding/inference only after extracting that component into a fixed
benchmark. Keep Supabase, payment, email, and production credentials out of the
sandbox.

### 5. `E:\campusbites`

This is a frontend/backend JavaScript application. Benchmark API response time,
query behavior, bundle size, or deterministic recommendation logic on fixtures.
GPU is unlikely to help unless a separate ML or image-processing service is
introduced.

### 6. `E:\discordbot`

Use CPU benchmarks for command dispatch and message parsing. GPU only makes
sense for a local inference feature; benchmark that feature separately and keep
tokens, credentials, and network access outside the proposal sandbox.

## Safe per-project workflow

```text
choose one pure/deterministic subsystem
  -> copy only fixtures and a wrapper into a proposal package
  -> create a task contract with a frozen evaluator version
  -> validate the package without execution
  -> run CPU baseline
  -> run one GPU worker with a declared VRAM policy
  -> compare end-to-end metrics and retain the best artifact
```

Do not point `solution/solve.sh` at a whole existing project checkout. Create a
small adapter package that imports or copies only the code and fixtures needed
for the benchmark. This keeps results reproducible and prevents secrets,
databases, browser profiles, and deployment configuration from crossing the
sandbox boundary.
