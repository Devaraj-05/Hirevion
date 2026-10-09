mod common;

use common::{INTERVIEW, TempDir, open, payload, screen};
use hv_security::Vault;
use hv_segment_store::{
    Codec, Container, MAX_SEGMENT_BYTES, NewSegment, SegmentState, SegmentStore, StoreError, Track,
    sha256_hex,
};

#[test]
fn a_segment_reads_back_exactly_as_it_was_stored() {
    let dir = TempDir::new();
    let (store, _) = open(dir.path());
    let plain = payload(0, 300_000);

    let stored = store.put(screen(0), &plain).expect("put");

    assert_eq!(stored.state, SegmentState::Captured);
    assert_eq!(stored.bytes, 300_000);
    assert_eq!(stored.attempts, 0);
    assert_eq!(stored.track, Track::Screen(1));
    assert_eq!(store.read(stored.id).expect("read"), plain);
}

#[test]
fn the_hash_is_the_sha256_of_the_plaintext() {
    let dir = TempDir::new();
    let (store, _) = open(dir.path());

    let stored = store.put(screen(0), b"abc").expect("put");

    assert_eq!(
        stored.sha256,
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    );
    assert_eq!(sha256_hex(b"abc"), stored.sha256);
}

#[test]
fn the_file_on_disk_is_encrypted() {
    let dir = TempDir::new();
    let (store, _) = open(dir.path());
    let mut plain = payload(1, 4_096);
    plain[1_000..1_032].copy_from_slice(b"PLAINTEXT-MARKER-THAT-MUST-HIDE!");

    let stored = store.put(screen(1), &plain).expect("put");
    let on_disk = std::fs::read(store.segment_path(&stored)).expect("file");

    assert!(
        on_disk.len() > plain.len(),
        "header, nonce and tag are added"
    );
    assert!(
        !on_disk
            .windows(32)
            .any(|w| w == b"PLAINTEXT-MARKER-THAT-MUST-HIDE!"),
        "plaintext leaked to disk"
    );
}

#[test]
fn each_interview_gets_its_own_key_in_the_vault() {
    let dir = TempDir::new();
    let (store, _) = open(dir.path());
    store.put(screen(0), b"one").expect("put");

    let vault = Vault::new(dir.path().join("vault"));
    let key = vault
        .get(&format!("rec-key-{INTERVIEW}"))
        .expect("vault readable")
        .expect("key stored");
    assert_eq!(key.len(), 32);
    // The vault file is DPAPI-sealed: the raw key never appears on disk.
    let sealed = std::fs::read(
        dir.path()
            .join("vault")
            .join(format!("rec-key-{INTERVIEW}.secret")),
    )
    .expect("sealed file");
    assert!(!sealed.windows(32).any(|w| w == key.as_slice()));
}

#[test]
fn without_the_key_a_segment_cannot_be_read() {
    let dir = TempDir::new();
    let (store, _) = open(dir.path());
    let stored = store.put(screen(0), b"secret video").expect("put");
    drop(store);

    let (other, _) = SegmentStore::open(
        dir.path().join("segments"),
        Vault::new(dir.path().join("another-vault")),
    )
    .expect("opens");
    let error = other.read(stored.id).expect_err("no key, no plaintext");
    assert!(matches!(error, StoreError::KeyMissing(_)), "{error:?}");
}

#[test]
fn a_tampered_file_is_refused() {
    let dir = TempDir::new();
    let (store, _) = open(dir.path());
    let stored = store.put(screen(0), &payload(0, 1_000)).expect("put");
    let path = store.segment_path(&stored);

    let mut bytes = std::fs::read(&path).expect("file");
    let last = bytes.len() - 1;
    bytes[last] ^= 0x01;
    std::fs::write(&path, &bytes).expect("rewrite");

    let error = store.read(stored.id).expect_err("tampered");
    assert!(matches!(error, StoreError::Corrupt(_)), "{error:?}");
}

#[test]
fn a_tampered_header_is_refused() {
    let dir = TempDir::new();
    let (store, _) = open(dir.path());
    let stored = store.put(screen(7), &payload(7, 1_000)).expect("put");
    let path = store.segment_path(&stored);

    // Rewrite "seq":7 as "seq":8 in the authenticated header.
    let bytes = std::fs::read(&path).expect("file");
    let needle = b"\"seq\":7";
    let at = bytes
        .windows(needle.len())
        .position(|w| w == needle)
        .expect("seq in header");
    let mut changed = bytes.clone();
    changed[at + needle.len() - 1] = b'8';
    std::fs::write(&path, &changed).expect("rewrite");

    assert!(matches!(store.read(stored.id), Err(StoreError::Corrupt(_))));
}

#[test]
fn storing_the_same_segment_twice_is_idempotent() {
    let dir = TempDir::new();
    let (store, _) = open(dir.path());
    let first = store.put(screen(3), b"same bytes").expect("put");
    let again = store.put(screen(3), b"same bytes").expect("put again");
    assert_eq!(first.id, again.id);

    let error = store.put(screen(3), b"other bytes").expect_err("conflict");
    assert!(matches!(error, StoreError::Conflict(_)), "{error:?}");
}

#[test]
fn segments_must_match_the_contract() {
    let dir = TempDir::new();
    let (store, _) = open(dir.path());

    let webm_screen = NewSegment {
        container: Container::Webm,
        codec: Codec::Vp8,
        ..screen(0)
    };
    assert!(matches!(
        store.put(webm_screen, b"x"),
        Err(StoreError::Contract(_))
    ));

    let too_long = NewSegment {
        duration_ms: 60_001,
        ..screen(0)
    };
    assert!(matches!(
        store.put(too_long, b"x"),
        Err(StoreError::Contract(_))
    ));

    let other_interview = NewSegment {
        interview_id: "../../etc".to_owned(),
        ..screen(0)
    };
    assert!(matches!(
        store.put(other_interview, b"x"),
        Err(StoreError::Contract(_))
    ));

    assert!(matches!(
        store.put(screen(0), b""),
        Err(StoreError::Contract(_))
    ));
    let too_big = vec![0u8; MAX_SEGMENT_BYTES + 1];
    assert!(matches!(
        store.put(screen(0), &too_big),
        Err(StoreError::Contract(_))
    ));

    let camera_webm = NewSegment {
        track: Track::Camera,
        container: Container::Webm,
        codec: Codec::Vp8,
        ..screen(0)
    };
    store
        .put(camera_webm, b"vp8")
        .expect("camera may be WebM/VP8");
    let mic_aac = NewSegment {
        track: Track::Mic,
        container: Container::Mp4,
        codec: Codec::Aac,
        ..screen(0)
    };
    store.put(mic_aac, b"aac").expect("mic may be MP4/AAC");
}

#[test]
fn a_segment_walks_the_upload_states_in_order() {
    let dir = TempDir::new();
    let (store, _) = open(dir.path());
    let stored = store.put(screen(0), b"bytes").expect("put");
    let path = store.segment_path(&stored);

    let queued = store.enqueue(stored.id).expect("queue");
    assert_eq!(queued.state, SegmentState::Queued);
    let uploading = store.start_upload(stored.id, "seg-1").expect("upload");
    assert_eq!(uploading.state, SegmentState::Uploading);
    assert_eq!(uploading.segment_id.as_deref(), Some("seg-1"));
    let uploaded = store
        .transition(stored.id, SegmentState::Uploaded)
        .expect("uploaded");
    assert_eq!(uploaded.state, SegmentState::Uploaded);
    let acknowledged = store.acknowledge(stored.id).expect("ack");
    assert_eq!(acknowledged.state, SegmentState::Acknowledged);
    assert!(path.exists(), "the file stays until it is purged");

    let purged = store.purge(stored.id).expect("purge");
    assert_eq!(purged.state, SegmentState::Purged);
    assert!(!path.exists(), "purging deletes the file");
}

#[test]
fn invalid_transitions_are_refused() {
    let dir = TempDir::new();
    let (store, _) = open(dir.path());
    let stored = store.put(screen(0), b"bytes").expect("put");

    let skip = store.transition(stored.id, SegmentState::Uploaded);
    assert!(
        matches!(skip, Err(StoreError::InvalidTransition { .. })),
        "{skip:?}"
    );
    // Only an acknowledged segment may be purged: the file must survive until the ack.
    assert!(matches!(
        store.purge(stored.id),
        Err(StoreError::InvalidTransition { .. })
    ));
    assert!(store.segment_path(&stored).exists());

    store
        .acknowledge(stored.id)
        .expect("409 acknowledges from any pending state");
    assert!(matches!(
        store.transition(stored.id, SegmentState::Queued),
        Err(StoreError::InvalidTransition { .. })
    ));
}

#[test]
fn a_failed_attempt_goes_back_to_the_queue_and_is_counted() {
    let dir = TempDir::new();
    let (store, _) = open(dir.path());
    let stored = store.put(screen(0), b"bytes").expect("put");
    store.enqueue(stored.id).expect("queue");
    store.start_upload(stored.id, "seg-1").expect("upload");

    let retried = store.retry(stored.id, "network").expect("retry");
    assert_eq!(retried.state, SegmentState::Queued);
    assert_eq!(retried.attempts, 1);
    assert_eq!(retried.last_error.as_deref(), Some("network"));

    store
        .start_upload(stored.id, "seg-1")
        .expect("upload again");
    store
        .transition(stored.id, SegmentState::Uploaded)
        .expect("uploaded");
    let mismatch = store.retry(stored.id, "hash-mismatch").expect("re-upload");
    assert_eq!(mismatch.state, SegmentState::Queued);
    assert_eq!(mismatch.attempts, 2);
}

#[test]
fn a_refused_segment_stops_for_good() {
    let dir = TempDir::new();
    let (store, _) = open(dir.path());
    let stored = store.put(screen(0), b"bytes").expect("put");
    store.enqueue(stored.id).expect("queue");

    let rejected = store
        .reject(stored.id, "track-not-recorded")
        .expect("reject");
    assert_eq!(rejected.state, SegmentState::Rejected);
    assert!(store.pending(INTERVIEW).expect("pending").is_empty());
    assert!(matches!(
        store.transition(stored.id, SegmentState::Queued),
        Err(StoreError::InvalidTransition { .. })
    ));
}

#[test]
fn pending_lists_unacknowledged_segments_oldest_first() {
    let dir = TempDir::new();
    let (store, _) = open(dir.path());
    let late = store.put(screen(2), b"two").expect("put");
    let early = store.put(screen(0), b"zero").expect("put");
    let middle = store
        .put(
            NewSegment {
                track: Track::Camera,
                ..screen(1)
            },
            b"camera one",
        )
        .expect("put");
    let done = store.put(screen(1), b"one").expect("put");
    store.acknowledge(done.id).expect("ack");

    let ids: Vec<i64> = store
        .pending(INTERVIEW)
        .expect("pending")
        .iter()
        .map(|s| s.id)
        .collect();
    assert_eq!(ids, [early.id, middle.id, late.id]);
    assert_eq!(
        store.interviews_with_pending().expect("interviews"),
        [INTERVIEW]
    );

    let counts = store.counts(INTERVIEW).expect("counts");
    assert_eq!(counts.pending, 3);
    assert_eq!(counts.acknowledged, 1);
    assert_eq!(counts.pending_bytes, 3 + 4 + 10);
}

#[test]
fn the_key_is_forgotten_only_when_every_segment_is_done() {
    let dir = TempDir::new();
    let (store, _) = open(dir.path());
    let stored = store.put(screen(0), b"bytes").expect("put");
    let vault = Vault::new(dir.path().join("vault"));
    let key_name = format!("rec-key-{INTERVIEW}");

    assert!(!store.forget_interview(INTERVIEW).expect("still pending"));
    assert!(vault.get(&key_name).expect("vault").is_some());

    store.acknowledge(stored.id).expect("ack");
    store.purge(stored.id).expect("purge");
    assert!(store.forget_interview(INTERVIEW).expect("all done"));
    assert!(vault.get(&key_name).expect("vault").is_none());
}
