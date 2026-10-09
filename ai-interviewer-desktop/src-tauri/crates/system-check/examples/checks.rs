//! Prints this machine's native check results as JSON:
//!     cargo run -p hv-system-check --example checks

fn main() {
    let mut results = hv_system_check::native_checks();
    results.push(hv_system_check::screen_capture_probe());
    match serde_json::to_string_pretty(&results) {
        Ok(json) => println!("{json}"),
        Err(error) => eprintln!("could not serialise the results: {error}"),
    }
}
