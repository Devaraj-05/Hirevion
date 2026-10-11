fn main() {
    // Windows N editions ship without Media Foundation. Delay-loading its DLLs lets the app
    // start there and show the system check's "install the Media Feature Pack" message,
    // instead of Windows refusing to launch it.
    let msvc = std::env::var("CARGO_CFG_TARGET_ENV").is_ok_and(|env| env == "msvc");
    if msvc {
        println!("cargo:rustc-link-arg-bins=/DELAYLOAD:mfplat.dll");
        println!("cargo:rustc-link-arg-bins=delayimp.lib");
        // Integration-test executables that build a Tauri app need the Common Controls v6
        // manifest too (see test.manifest). The app binary already has one from tauri_build.
        let manifest =
            std::path::Path::new(&std::env::var("CARGO_MANIFEST_DIR").unwrap_or_default())
                .join("test.manifest");
        println!("cargo:rustc-link-arg-tests=/MANIFEST:EMBED");
        println!(
            "cargo:rustc-link-arg-tests=/MANIFESTINPUT:{}",
            manifest.display()
        );
        println!("cargo:rerun-if-changed=test.manifest");
    }
    tauri_build::build()
}
