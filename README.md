# Rust/Serde wide-struct compile-time reproduction

This is a source-only reduction of a Rust 1.98 / LLVM 22 compile-time hotspot
in wide Serde deserializers targeting Windows MSVC.

The baseline is a 128-field struct deriving `serde::Deserialize`, with concrete
`serde_json::from_str` and `from_slice` entry points. Two avoidance patterns are
included:

1. Split a private wire representation into four 32-field structs flattened
   into the same JSON object, then convert into the original flat public type.
   This preserves JSON keys and public field access, at the cost of buffering
   the flattened map during deserialization.
2. Keep the struct unchanged, but place concrete JSON parsing in its owning
   crate behind `#[inline(never)]`. Downstream crates call that function instead
   of instantiating `serde_json::from_str::<Wide>` again.

Run all cases sequentially with Rust 1.98 and detailed compiler profiling:

```shell
python3 profile.py
```

The script writes Cargo wall time, rustc phase times, self-profile data, and LLVM
time traces under `profiles/`. For the two-crate cases it prebuilds the model
crate so the consumer measurement does not include its dependency. It sets
`RUSTC_BOOTSTRAP=1` only to enable diagnostic profiling flags on the stable
compiler. The compiled code itself uses stable Rust.

On any host with Rust's Windows standard library installed, the same compiler
binary can cross-codegen the rlib for Windows without a Windows linker:

```shell
rustup target add x86_64-pc-windows-msvc --toolchain 1.98.0
python3 profile_windows_target.py
```

This profiles the Windows target with unwind and abort panic strategies. The
comparison also profiles the private chunked wire representation, and isolates
LLVM target behavior from Windows runner hardware.

For the smallest upstream reproduction, build only `monolithic`:

```shell
RUSTC_BOOTSTRAP=1 cargo +1.98.0 rustc --release -p monolithic -- \
  -Ztime-passes -Zllvm-time-trace -Zself-profile=profiles/monolithic
```

`generate.py` is checked in together with its generated sources so the field
count can be varied without hand-editing repetitive code.

## Example result

On an Apple Silicon Mac with rustc 1.98.0 / LLVM 22.1.8, a sequential run gave:

| Case | rustc total | LLVM LICM |
| --- | ---: | ---: |
| Native monolithic | 16.301 s | 0.035 s |
| Native private chunked wire | 1.651 s | 0.007 s |
| Windows-target monolithic | 27.567 s | 9.159 s |
| Windows-target monolithic, panic abort | 14.053 s | 4.594 s |
| Windows-target private chunked wire | 1.624 s | 0.012 s |

For the monolithic Windows target, 1,932 of 2,621 LICM invocations belong to
the generated `visit_map` functions for `StrRead` and `SliceRead`. Both
functions use the scoped Windows EH personality `__CxxFrameHandler3`. An
8-second stack sample caught 1,558 samples in LICM's loop-safety setup; 1,516
of those (97.3%) were in `llvm::colorEHFunclets`, usually scanning the first
non-PHI instruction in every basic block.

LLVM 22.1.8 calls `computeLoopSafetyInfo` from LICM for each loop. That calls
`computeBlockColors`, which calls `colorEHFunclets` across the whole function
when it has a scoped EH personality. This repeated whole-function scan is the
Windows-specific multiplier exposed by the giant generated visitor.

## Instrumented compiler confirmation

`llvm-instrumentation.patch` applies to the LLVM 22.1.8 submodule in the exact
Rust 1.98.0 source release (`88d9e12ae178fab0fb5cc050a94da85685d449ea`).
It counts calls and whole-function basic-block scans in
`LoopSafetyInfo::computeBlockColors`, measures time spent in
`colorEHFunclets`, and provides a diagnostic-only bypass. The bypass is not a
valid compiler fix: block colors are required for correct transformations
across Windows EH funclets. It exists only to attribute elapsed time while
holding the compiler, source, flags, and standard library constant.

The 128-field Windows-target monolithic case produced:

| Exact Rust 1.98 compiler | rustc total | LLVM passes | ThinLTO | `colorEHFunclets` time |
| --- | ---: | ---: | ---: | ---: |
| Instrumented normally | 28.606 s | 1.501 s | 26.651 s | 9.771 s |
| Same binary, diagnostic bypass | 18.752 s | 0.980 s | 17.323 s | 0 s |

Both executions entered `computeBlockColors` 2,621 times and the scoped-EH
path 2,316 times. Each execution therefore attempted 9,880,591 basic-block
visits through whole-function coloring. The bypass saved 9.854 seconds, within
83 milliseconds of the 9.771 seconds measured inside `colorEHFunclets`.
Together with the sampled call stack, this identifies the repeated coloring as
the elapsed-time cause rather than merely a property correlated with the slow
function.

The generic Serde/LLVM compile-time problem was previously reported in
[serde-rs/json#313](https://github.com/serde-rs/json/issues/313). The exact
repeated Windows funclet-coloring concern was raised on
[llvm-dev in 2017](https://groups.google.com/g/llvm-dev/c/sm_IMDODl3U), but the
eager call remains in LLVM 22.1.8.
