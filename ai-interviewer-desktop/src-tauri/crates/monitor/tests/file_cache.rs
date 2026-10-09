//! The hash and signature cache.

use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};

use hv_monitor::file_cache::{FileCache, sha256_file};
use hv_monitor::{SignatureInfo, SignatureStatus};

fn temp_file(name: &str, contents: &[u8]) -> std::path::PathBuf {
    let dir = std::env::temp_dir().join(format!("hv-monitor-cache-{}-{name}", std::process::id()));
    std::fs::create_dir_all(&dir).expect("dir");
    let path = dir.join("file.bin");
    std::fs::write(&path, contents).expect("write");
    path
}

#[test]
fn sha256_of_a_known_file() {
    let path = temp_file("known", b"abc");
    assert_eq!(
        sha256_file(&path).expect("hash"),
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    );
    let _ = std::fs::remove_dir_all(path.parent().expect("parent"));
}

#[test]
fn facts_are_cached_until_the_file_changes() {
    let path = temp_file("cached", b"first");
    let checks = Arc::new(AtomicUsize::new(0));
    let counter = checks.clone();
    let mut cache = FileCache::new(move |_| {
        counter.fetch_add(1, Ordering::SeqCst);
        SignatureInfo {
            status: SignatureStatus::Unsigned,
            ..SignatureInfo::default()
        }
    });

    let first = cache.facts(&path);
    let again = cache.facts(&path);
    assert_eq!(first, again);
    assert_eq!(checks.load(Ordering::SeqCst), 1);
    assert_eq!(first.signature.status, SignatureStatus::Unsigned);

    std::fs::write(&path, b"second, and longer").expect("rewrite");
    let changed = cache.facts(&path);
    assert_ne!(changed.sha256, first.sha256);
    assert_eq!(checks.load(Ordering::SeqCst), 2);
    assert_eq!(cache.len(), 1);

    let missing = cache.facts(&path.with_file_name("missing.bin"));
    assert_eq!(missing.sha256, None);
    assert_eq!(missing.signature.status, SignatureStatus::Unknown);
    let _ = std::fs::remove_dir_all(path.parent().expect("parent"));
}
