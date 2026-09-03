#!/usr/bin/env python3
"""Generate the repetitive Rust fields used by this compiler reproduction."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COUNT = 128


def fields(start: int, stop: int) -> str:
    return "\n".join(f"    pub field_{i:04}: String," for i in range(start, stop))


def manifest(name: str, dependencies: str) -> str:
    return f'''[package]
name = "{name}"
version = "0.0.0"
edition.workspace = true
rust-version.workspace = true
publish = false

[dependencies]
{dependencies}'''


def write_crate(name: str, source: str, dependencies: str) -> None:
    crate = ROOT / name
    (crate / "src").mkdir(parents=True, exist_ok=True)
    (crate / "Cargo.toml").write_text(manifest(name, dependencies))
    (crate / "src/lib.rs").write_text(source)


parsers = '''
#[inline(never)]
pub fn parse_str(input: &str) -> Result<Wide, serde_json::Error> {
    serde_json::from_str(input)
}

#[inline(never)]
pub fn parse_slice(input: &[u8]) -> Result<Wide, serde_json::Error> {
    serde_json::from_slice(input)
}
'''

monolithic_type = f'''#[derive(serde::Deserialize)]
pub struct Wide {{
{fields(0, COUNT)}
}}
'''

groups = []
members = []
conversions = []
for group in range(4):
    start = group * 32
    groups.append(f'''#[derive(serde::Deserialize)]
struct Group{group} {{
{fields(start, start + 32)}
}}
''')
    members.append(f"    #[serde(flatten)]\n    group_{group}: Group{group},")
    conversions.extend(
        f"            field_{i:04}: wire.group_{group}.field_{i:04},"
        for i in range(start, start + 32)
    )
flattened_type = "\n".join(groups) + f'''\n#[derive(serde::Deserialize)]
struct Wire {{
{chr(10).join(members)}
}}

pub struct Wide {{
{fields(0, COUNT)}
}}

impl From<Wire> for Wide {{
    fn from(wire: Wire) -> Self {{
        Self {{
{chr(10).join(conversions)}
        }}
    }}
}}

impl<'de> serde::Deserialize<'de> for Wide {{
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {{
        <Wire as serde::Deserialize>::deserialize(deserializer).map(Into::into)
    }}
}}
'''

serde_dependencies = "serde.workspace = true\nserde_json.workspace = true\n"
write_crate(
    "primer",
    "pub fn primer() {\n    let _ = serde_json::Value::Null;\n}\n",
    serde_dependencies,
)
write_crate("monolithic", monolithic_type + parsers, serde_dependencies)
write_crate("flattened", flattened_type + parsers, serde_dependencies)
write_crate("model_only", monolithic_type, "serde.workspace = true\n")
write_crate("boundary_model", monolithic_type + parsers, serde_dependencies)
write_crate(
    "direct_consumer",
    '''#[inline(never)]
pub fn parse_str(input: &str) -> Result<model_only::Wide, serde_json::Error> {
    serde_json::from_str(input)
}

#[inline(never)]
pub fn parse_slice(input: &[u8]) -> Result<model_only::Wide, serde_json::Error> {
    serde_json::from_slice(input)
}
''',
    "model_only = { path = \"../model_only\" }\nserde_json.workspace = true\n",
)
write_crate(
    "boundary_consumer",
    '''#[inline(never)]
pub fn parse_str(input: &str) -> Result<boundary_model::Wide, serde_json::Error> {
    boundary_model::parse_str(input)
}

#[inline(never)]
pub fn parse_slice(input: &[u8]) -> Result<boundary_model::Wide, serde_json::Error> {
    boundary_model::parse_slice(input)
}
''',
    "boundary_model = { path = \"../boundary_model\" }\nserde_json.workspace = true\n",
)

bench_source = '''use std::hint::black_box;
use std::time::Instant;

fn main() {
    let input = serde_json::Value::Object(
        (0..128)
            .map(|i| {
                (
                    format!("field_{i:04}"),
                    serde_json::Value::String("value".into()),
                )
            })
            .collect(),
    )
    .to_string();
    const ITERATIONS: usize = 1_000;

    let start = Instant::now();
    for _ in 0..ITERATIONS {
        let wide = black_box(monolithic::parse_str(black_box(&input))).unwrap();
        assert_eq!(wide.field_0000, "value");
        assert_eq!(wide.field_0127, "value");
    }
    let monolithic_ms = start.elapsed().as_secs_f64() * 1_000.0;
    println!("monolithic_ms={monolithic_ms:.3}");

    let start = Instant::now();
    for _ in 0..ITERATIONS {
        let wide = black_box(flattened::parse_str(black_box(&input))).unwrap();
        assert_eq!(wide.field_0000, "value");
        assert_eq!(wide.field_0127, "value");
    }
    let flattened_ms = start.elapsed().as_secs_f64() * 1_000.0;
    println!("flattened_ms={flattened_ms:.3}");
    println!(
        "flattened_over_monolithic={:.3}",
        flattened_ms / monolithic_ms
    );
}
'''
crate = ROOT / "runtime_bench"
(crate / "src").mkdir(parents=True, exist_ok=True)
(crate / "Cargo.toml").write_text(manifest(
    "runtime_bench",
    "monolithic = { path = \"../monolithic\" }\nflattened = { path = \"../flattened\" }\nserde_json.workspace = true\n",
))
(crate / "src/main.rs").write_text(bench_source)
lib = crate / "src/lib.rs"
if lib.exists():
    lib.unlink()

print(f"Generated {COUNT}-field reproduction under {ROOT}")
