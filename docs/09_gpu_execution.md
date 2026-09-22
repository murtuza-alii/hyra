# Mini-Hyra GPU Execution

GPU support is task-specific. It accelerates tensor, matrix, image, simulation,
and model workloads, but is usually slower or irrelevant for lightweight
parsing, small algorithms, and shell-heavy tasks because data-transfer and
startup costs dominate.

## GPU policy

Add this field to a task contract:

```json
"gpu": {
  "enabled": true,
  "device_index": 0,
  "min_memory_mb": 4096,
  "memory_limit_mb": 5120,
  "require_cuda": true
}
```

`device_index` chooses the host-visible NVIDIA device. `min_memory_mb` is an
admission floor. `memory_limit_mb` is a requirement for the hardened launcher;
Mini-Hyra does not claim that an environment variable can enforce it. Use a
limit below physical VRAM to leave room for Windows and display workloads.

## Local hardware

Use the actual host inventory rather than hard-coding a device assumption:

```powershell
mini-hyra gpu-status
mini-hyra doctor
```

The current RTX 3050 Laptop GPU has 6 GB VRAM. Start tasks with a 4 GiB minimum
and a 5 GiB cap, then lower batch sizes or model sizes if Windows graphics use
causes contention.

## Safe rollout

1. Keep the evaluator deterministic and compare GPU work to the CPU baseline.
2. Begin with one GPU worker; do not use the default two concurrent proposal
   workers for two GPU jobs on a 6 GB device.
3. Score end-to-end latency or throughput, including transfer and warm-up costs.
4. Record CUDA/framework versions in package artifacts.
5. Configure a hardened launcher that restricts the assigned GPU before running
   untrusted proposal code in strict mode.

Good first GPU benchmarks are small inference throughput tests, image filters,
matrix kernels, and compact simulation steps. Large-model training, unrestricted
CUDA compilation, and GPU code from untrusted sources should wait for a tested
GPU-aware launcher and evaluator.
