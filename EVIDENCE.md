# Compiler evidence

The source reproduction is intentionally the primary report. This file records
the compiler-level measurements behind it.

## The generated Rust is large but linear

`rustc --emit=mir` shows that Serde's generated `visit_map` grows linearly
with the number of fields:

| fields | `visit_map` MIR blocks | pre-optimization LLVM blocks |
| ---: | ---: | ---: |
| 16 | 306 | 1,929 |
| 32 | 594 | 2,649 |
| 64 | 1,170 | 4,089 |
| 96 | 1,746 | 5,529 |
| 128 | 2,322 | 6,969 |

The nonlinear compile time is therefore not caused by a nonlinear expansion in
the derive macro.

The LLVM IR for `visit_map` uses the scoped Windows personality
`__CxxFrameHandler3`. Because each `String` may need to be dropped if a
later field fails to deserialize, the function also contains a large chain of
Windows cleanup pads.

As a control, changing all 128 fields from `String` to `u64` reduced the
LLVM optimization time from about 13.0 seconds to 0.50 seconds.

## Repeated funclet coloring in LICM

LLVM's loop-invariant code-motion pass constructs an
`ICFLoopSafetyInfo` for each loop. Its current implementation immediately
calls `colorEHFunclets` over the whole containing function whenever the
function uses scoped exception handling:

- [LICM constructs the safety information](https://github.com/llvm/llvm-project/blob/52ed14fcd56afc30f9cccd8ca8ce237c2eef7e04/llvm/lib/Transforms/Scalar/LICM.cpp#L455-L456)
- [LoopSafetyInfo eagerly colors the function](https://github.com/llvm/llvm-project/blob/52ed14fcd56afc30f9cccd8ca8ce237c2eef7e04/llvm/lib/Analysis/MustExecute.cpp#L102-L109)
- [colorEHFunclets traverses the CFG](https://github.com/llvm/llvm-project/blob/52ed14fcd56afc30f9cccd8ca8ce237c2eef7e04/llvm/lib/IR/EHPersonalities.cpp#L115-L157)

Instrumentation in those functions produced:

| fields | colorings of `visit_map` | cumulative blocks | worklist pops | coloring time |
| ---: | ---: | ---: | ---: | ---: |
| 16 | 78 | 59,254 | 97,448 | 0.004 s |
| 32 | 168 | 226,548 | 368,676 | 0.045 s |
| 64 | 296 | 751,988 | 1,215,524 | 0.447 s |
| 96 | 424 | 1,582,580 | 2,551,844 | 1.613 s |
| 128 | 552 | 2,718,324 | 4,377,636 | 4.907 s |

Both the size of `visit_map` and the number of times it is colored grow with
the field count. Their product is the nonlinear work.

At 128 fields, LLVM's full `default<O3>` pipeline took 13.46 seconds. LICM
took 5.07 seconds, and 4.91 seconds were measured inside
`colorEHFunclets` for `visit_map` alone.

## Tested compiler-side change

The tested change makes block coloring lazy:

1. `computeLoopSafetyInfo` records the function but does not color it.
2. `getBlockColors` computes the map on first use.
3. LICM does not request the map while inspecting ordinary instructions; it
   requests it only for a call that may be sunk through a PHI, or when an
   exception-pad predecessor may be split.

For this reproduction, no color-dependent transformation is performed, so the
map is never computed:

| LLVM pipeline | wall time |
| --- | ---: |
| LLVM 22.1.8 baseline | 13.40 s |
| Lazy block coloring | 8.33 s |

The optimized LLVM IR from both runs is byte-for-byte identical
(`sha256:b5e1a7d1c70478ef365f7905438d9c69c1983b23f9e65cf8c9fb9c2bc15df5e4`).
The change also passed all 9,422 supported LLVM transform tests and all 148
supported LICM tests in this checkout.

This removes the largest confirmed repeated analysis. It does not remove all
cost of optimizing the unusually large generated function.
