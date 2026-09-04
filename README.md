# Slow compilation of a wide Serde deserializer

This repository reproduces unexpectedly nonlinear compile time when a large
Rust struct derives `serde::Deserialize` and is deserialized concretely with
`serde_json`.

The repository is one library crate. Its generated `src/lib.rs` contains a
128-field struct and one call to `serde_json::from_str`.

## Reproduce

Install Rust's Windows standard library once:

```shell
rustup target add x86_64-pc-windows-msvc --toolchain 1.98.0
```

Then time the same crate at several field counts:

```shell
python3 repro.py --bench
```

The build targets Windows MSVC but only produces an rlib, so it can be run on
Windows, macOS, or Linux and does not need a Windows linker.

One run on an Apple Silicon Mac produced:

| fields | wall time |
| ---: | ---: |
| 16 | 0.378 s |
| 32 | 0.702 s |
| 64 | 2.463 s |
| 96 | 6.942 s |
| 128 | 13.735 s |

The number of fields increased by 8x while compile time increased by 36x.

To generate one particular size and build it directly:

```shell
python3 repro.py 128
cargo build --release --target x86_64-pc-windows-msvc --lib
```

Rust is pinned by `rust-toolchain.toml`, and dependency versions are pinned in
`Cargo.toml`.
