use std::hint::black_box;
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
