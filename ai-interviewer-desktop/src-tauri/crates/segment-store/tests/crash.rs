//! Crash safety: whatever the moment of a crash, reopening the store keeps every acknowledged
//! row and every completed segment; only the segment being written may be lost.

mod common;

use std::io::{BufRead, BufReader};
use std::process::{Command, Stdio};

use common::{INTERVIEW, TempDir, open, payload, screen};
use hv_segment_store::{MANIFEST_FILE, SegmentState};

#[test]
fn reopening_resumes_uploads_and_purges_acknowledged_files() {
    let dir = TempDir::new();
    let (store, _) = open(dir.path());
    let captured = store.put(screen(0), b"zero").expect("put");
    let uploading = store.put(screen(1), b"one").expect("put");
    store.enqueue(uploading.id).expect("queue");
    store.start_upload(uploading.id, "seg-1").expect("upload");
    let acknowledged = store.put(screen(2), b"two").expect("put");
    store.acknowledge(acknowledged.id).expect("ack");
    let acknowledged_path = store.segment_path(&acknowledged);
    drop(store); // the app dies here, before purging

    let (store, recovery) = open(dir.path());

    assert_eq!(recovery.uploads_reset, 1);
    assert_eq!(recovery.purged, 1);
    let state = |id| store.get(id).expect("get").expect("row").state;
    assert_eq!(state(captured.id), SegmentState::Captured);
    assert_eq!(state(uploading.id), SegmentState::Queued);
    assert_eq!(state(acknowledged.id), SegmentState::Purged);
    assert!(!acknowledged_path.exists());
    assert_eq!(store.read(captured.id).expect("read"), b"zero");
}

#[test]
fn a_half_written_segment_is_discarded() {
    let dir = TempDir::new();
    let (store, _) = open(dir.path());
    let kept = store.put(screen(0), b"complete").expect("put");
    let partial = store
        .segment_path(&kept)
        .with_file_name(".0000000001.deadbeef.tmp");
    std::fs::write(&partial, b"half a segm").expect("partial file");
    drop(store);

    let (store, recovery) = open(dir.path());

    assert_eq!(recovery.temp_files_removed, 1);
    assert!(!partial.exists());
    assert_eq!(store.read(kept.id).expect("read"), b"complete");
}

#[test]
fn a_segment_whose_manifest_row_was_never_written_is_adopted() {
    let dir = TempDir::new();
    let (store, _) = open(dir.path());
    let plain = payload(5, 10_000);
    let stored = store.put(screen(5), &plain).expect("put");
    drop(store);
    // The crash came after the file was renamed into place but before the row was committed.
    let manifest = rusqlite::Connection::open(dir.path().join("segments").join(MANIFEST_FILE))
        .expect("manifest");
    manifest
        .execute("DELETE FROM segments", [])
        .expect("drop row");
    drop(manifest);

    let (store, recovery) = open(dir.path());

    assert_eq!(recovery.adopted, 1);
    let adopted = store
        .find(INTERVIEW, &stored.track, 5)
        .expect("find")
        .expect("row is back");
    assert_eq!(adopted.state, SegmentState::Captured);
    assert_eq!(adopted.sha256, stored.sha256);
    assert_eq!(adopted.started_at_ms, stored.started_at_ms);
    assert_eq!(store.read(adopted.id).expect("read"), plain);
}

#[test]
fn a_missing_file_is_reported_as_lost() {
    let dir = TempDir::new();
    let (store, _) = open(dir.path());
    let stored = store.put(screen(0), b"bytes").expect("put");
    std::fs::remove_file(store.segment_path(&stored)).expect("remove");
    drop(store);

    let (store, recovery) = open(dir.path());

    assert_eq!(recovery.lost, 1);
    assert_eq!(
        store.get(stored.id).expect("get").expect("row").state,
        SegmentState::Lost
    );
}

const CHILD_ENV: &str = "HV_SEGMENT_STORE_CHILD_ROOT";
const SEGMENT_BYTES: usize = 512 * 1024;

/// Run only as the child of the test below: stores segments until it is killed, printing
/// each one once it is durable. Every third one is acknowledged straight away.
#[test]
fn child_writer() {
    let Ok(root) = std::env::var(CHILD_ENV) else {
        return;
    };
    let (store, _) = open(std::path::Path::new(&root));
    for seq in 0..u64::MAX {
        let stored = store
            .put(screen(seq), &payload(seq, SEGMENT_BYTES))
            .expect("put");
        if seq % 3 == 0 {
            store.acknowledge(stored.id).expect("ack");
            println!("stored {seq} acknowledged");
        } else {
            println!("stored {seq} captured");
        }
    }
}

#[test]
fn a_killed_writer_loses_at_most_the_segment_in_flight() {
    let dir = TempDir::new();
    let mut child = Command::new(std::env::current_exe().expect("test binary"))
        .args(["--exact", "child_writer", "--nocapture", "--test-threads=1"])
        .env(CHILD_ENV, dir.path())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .expect("child starts");
    let mut lines = BufReader::new(child.stdout.take().expect("stdout")).lines();
    let mut reported = Vec::new();
    let parse = |line: String, reported: &mut Vec<(u64, bool)>| {
        let mut words = line.split_whitespace();
        if words.next() == Some("stored") {
            let seq: u64 = words.next().expect("seq").parse().expect("number");
            reported.push((seq, words.next() == Some("acknowledged")));
        }
    };
    while reported.len() < 8 {
        let line = lines
            .next()
            .expect("the child keeps writing")
            .expect("line");
        parse(line, &mut reported);
    }
    child.kill().expect("kill");
    let _ = child.wait();
    // Lines already in the pipe were durable before the kill too.
    for line in lines {
        parse(line.expect("line"), &mut reported);
    }

    let (store, recovery) = open(dir.path());

    for &(seq, acknowledged) in &reported {
        let row = store
            .find(INTERVIEW, &screen(seq).track, seq)
            .expect("find")
            .unwrap_or_else(|| panic!("segment {seq} was durable but is gone"));
        if acknowledged {
            assert!(
                matches!(row.state, SegmentState::Purged | SegmentState::Acknowledged),
                "segment {seq} lost its acknowledgement: {:?}",
                row.state
            );
        } else {
            assert_eq!(
                store.read(row.id).expect("readable"),
                payload(seq, SEGMENT_BYTES),
                "segment {seq}"
            );
        }
    }
    let all = store.all(INTERVIEW).expect("rows");
    assert!(
        all.len() <= reported.len() + 1,
        "at most one segment beyond the reported ones: {} rows, {} reported",
        all.len(),
        reported.len()
    );
    assert_eq!(recovery.lost, 0);
    for row in all {
        if !matches!(row.state, SegmentState::Purged | SegmentState::Acknowledged) {
            store.read(row.id).expect("every kept segment decrypts");
        }
    }
}
