# Traveling Salesperson Problem (TSP) Optimization Demo

This demo demonstrates how **Mini-Hyra** works as an autonomous search & optimization engine.

---

## 1. The Challenge

Given 25 cities on a 2D map, find a closed tour visiting every city exactly once and returning to the start with the **minimum possible total distance**.

- **The Metric**: `total_distance` (Direction: `minimize`)
- **The Naive Baseline**: Visits cities in arbitrary index order (0 -> 1 -> 2 ... -> 24 -> 0).
  - Distance: **2,539.26 units** (very inefficient, crosses back and forth).
- **The Optimized Goal**: An algorithm using Nearest Neighbor + 2-Opt local swaps.
  - Distance: **1,045.75 units** (**~58% shorter**).

---

## 2. Directory Structure

```text
examples/tsp_optimizer/
├── task.json                   # Versioned task contract defining objective & bounds
├── README.md                   # This walkthrough
├── baseline/                   # Naive reference solution
│   └── solution/
│       ├── solve.sh            # Canonical execution entrypoint
│       └── tsp_solver.py       # Naive sequential visitor
└── improved/                   # Optimized reference solution
    └── solution/
        ├── solve.sh            # Canonical execution entrypoint
        └── tsp_solver.py       # Heuristic solver (Nearest Neighbor + 2-Opt)
```

---

## 3. How to Run the Demo Step-by-Step

### Step 1: Validate the Task Contract
Check that the task specification, evaluation hashes, and constraints are strictly valid:

```powershell
mini-hyra validate-task examples/tsp_optimizer/task.json
```

### Step 2: Validate the Solution Packages
Verify package integrity, file paths, and compute the SHA-256 package hash without executing any code:

```powershell
mini-hyra validate-package examples/tsp_optimizer/baseline
mini-hyra validate-package examples/tsp_optimizer/improved
```

### Step 3: Run the Autonomous Optimization Loop

Run iterations where candidate solutions are executed inside isolated sandboxes, graded by the evaluator, and stored in the Experience Bank:

```powershell
# Run a quick test with the template agent:
mini-hyra run examples/tsp_optimizer/task.json --agent template --iterations 1 --non-strict

# Run an AI-driven session using your local Antigravity subscription:
mini-hyra run examples/tsp_optimizer/task.json --agent antigravity --iterations 3 --non-strict
```

### Step 4: Inspect the Experience Bank History
View all recorded attempts, pass/fail status, and objective metrics:

```powershell
mini-hyra history --task-id tsp-route-optimization
```

### Step 5: Query the Best Solution Found
Retrieve the single best-performing solution across all recorded iterations:

```powershell
mini-hyra best tsp-route-optimization sha256:1111111111111111111111111111111111111111111111111111111111111111 --direction minimize
```
