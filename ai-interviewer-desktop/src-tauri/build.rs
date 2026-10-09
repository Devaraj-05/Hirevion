fn main() {
    // Windows N editions ship without Media Foundation. Delay-loading its DLLs lets the app
    // start there and show the system check's "install the Media Feature Pack" message,
    // instead of Windows refusing to launch it.
    let msvc = std::env::var("CARGO_CFG_TARGET_ENV").is_ok_and(|env| env == "msvc");
    if msvc {
        println!("cargo:rustc-link-arg-bins=/DELAYLOAD:mfplat.dll");
        println!("cargo:rustc-link-arg-bins=delayimp.lib");
    }
    tauri_build::build()
}
