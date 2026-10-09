//! The secret vault (DPAPI on Windows).

use std::path::PathBuf;

use hv_security::Vault;

/// A fresh directory under the system temp dir, removed on drop.
struct TempDir(PathBuf);

impl TempDir {
    fn new() -> Self {
        let dir = std::env::temp_dir().join(format!("hv-vault-test-{}", uuid::Uuid::new_v4()));
        Self(dir)
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

#[test]
fn round_trip_overwrite_and_delete() {
    let dir = TempDir::new();
    // The directory doesn't exist yet: the vault creates it on first write.
    let vault = Vault::new(dir.0.join("vault"));

    vault.put("refresh-token", b"rt_first").expect("put");
    assert_eq!(
        vault.get("refresh-token").expect("get").as_deref(),
        Some(&b"rt_first"[..])
    );

    vault.put("refresh-token", b"rt_second").expect("overwrite");
    assert_eq!(
        vault.get("refresh-token").expect("get").as_deref(),
        Some(&b"rt_second"[..])
    );

    vault.delete("refresh-token").expect("delete");
    assert_eq!(vault.get("refresh-token").expect("get"), None);
    // Deleting a missing secret is not an error.
    vault.delete("refresh-token").expect("delete again");

    // No temporary files are left behind.
    let leftovers: Vec<_> = std::fs::read_dir(dir.0.join("vault"))
        .expect("dir")
        .map(|e| e.expect("entry").file_name())
        .collect();
    assert!(leftovers.is_empty(), "left behind: {leftovers:?}");
}

#[test]
fn missing_name_is_none() {
    let dir = TempDir::new();
    let vault = Vault::new(&dir.0);
    assert_eq!(vault.get("never-written").expect("get"), None);
}

#[test]
fn names_are_isolated() {
    let dir = TempDir::new();
    let vault = Vault::new(&dir.0);
    vault.put("a", b"one").expect("put a");
    vault.put("b", b"two").expect("put b");
    assert_eq!(vault.get("a").expect("a").as_deref(), Some(&b"one"[..]));
    assert_eq!(vault.get("b").expect("b").as_deref(), Some(&b"two"[..]));
}

#[test]
fn rejects_names_that_could_escape_the_directory() {
    let dir = TempDir::new();
    let vault = Vault::new(&dir.0);
    for name in ["", "..", "../x", "a/b", "a\\b", ".hidden", "C:x", "a b"] {
        assert!(vault.put(name, b"x").is_err(), "accepted {name:?}");
        assert!(vault.get(name).is_err(), "accepted {name:?}");
    }
}

#[cfg(windows)]
#[test]
fn secrets_are_not_stored_in_plain_text() {
    let dir = TempDir::new();
    let vault = Vault::new(&dir.0);
    let secret = b"rt_plaintext_marker_0123456789";
    vault.put("refresh-token", secret).expect("put");

    let files: Vec<_> = std::fs::read_dir(&dir.0)
        .expect("dir")
        .map(|e| e.expect("entry").path())
        .collect();
    assert_eq!(files.len(), 1, "one file per secret");
    let stored = std::fs::read(&files[0]).expect("read");
    assert!(
        !stored.windows(secret.len()).any(|w| w == secret),
        "the secret appears in plain text"
    );
}

#[cfg(windows)]
#[test]
fn a_tampered_file_is_an_error_not_a_secret() {
    let dir = TempDir::new();
    let vault = Vault::new(&dir.0);
    vault.put("refresh-token", b"rt_value").expect("put");
    let file = std::fs::read_dir(&dir.0)
        .expect("dir")
        .next()
        .expect("one file")
        .expect("entry")
        .path();
    let mut bytes = std::fs::read(&file).expect("read");
    let last = bytes.len() - 1;
    bytes[last] ^= 0xff;
    std::fs::write(&file, bytes).expect("write");
    assert!(vault.get("refresh-token").is_err());
}
