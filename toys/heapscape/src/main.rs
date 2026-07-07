// heapscape — five memory allocators fed the same trace, racing to not
// fragment. `cargo run -p heapscape` for the live TUI; `--bench` for tables
// and PNGs. See the README for how each allocator works.

mod alloc;
mod bench;
mod harness;
mod rng;
mod tui;
mod viz;
mod workload;

use std::path::PathBuf;

use workload::{Kind, KINDS};

fn main() -> std::io::Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let mut is_bench = false;
    let mut seed: u64 = 42;
    let mut ops: u64 = 400_000;
    let mut kind = Kind::Churn;
    let mut out = PathBuf::from("toys/heapscape/examples");

    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "--bench" => is_bench = true,
            "--seed" => seed = it.next().and_then(|v| v.parse().ok()).unwrap_or(seed),
            "--ops" => ops = it.next().and_then(|v| v.parse().ok()).unwrap_or(ops),
            "--out" => out = it.next().map(PathBuf::from).unwrap_or(out),
            "--workload" => {
                let name = it.next().cloned().unwrap_or_default();
                kind = KINDS
                    .iter()
                    .copied()
                    .find(|k| k.name() == name)
                    .unwrap_or_else(|| {
                        eprintln!("unknown workload '{name}' (churn|spike|ramp|stripes|shift)");
                        std::process::exit(2);
                    });
            }
            "--help" | "-h" => {
                println!(
                    "heapscape — watch five allocators fragment under the same trace\n\n\
                     usage:\n  heapscape [--workload churn|spike|ramp|stripes|shift] [--seed N]   live TUI\n  \
                     heapscape --bench [--ops N] [--seed N] [--out DIR]                 tables + PNGs"
                );
                return Ok(());
            }
            other => {
                eprintln!("unknown arg '{other}' (try --help)");
                std::process::exit(2);
            }
        }
    }

    if is_bench {
        bench::run(ops, seed, &out)
    } else {
        tui::run(harness::Harness::new(kind, seed))
    }
}
