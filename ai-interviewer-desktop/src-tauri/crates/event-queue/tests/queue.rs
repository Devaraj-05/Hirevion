//! The durable, sequenced queue.

use std::io::Write as _;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU32, Ordering};

use hv_event_queue::{EventDraft, EventName, EventQueue, Source};

static NEXT: AtomicU32 = AtomicU32::new(0);

struct TempDir(PathBuf);

impl TempDir {
    fn new() -> Self {
        let n = NEXT.fetch_add(1, Ordering::SeqCst);
        Self(std::env::temp_dir().join(format!("hv-queue-test-{}-{n}", std::process::id())))
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

const SESSION: &str = "6f1c2c1e-0000-4000-8000-0000000000aa";

fn draft(at: i64) -> EventDraft {
    EventDraft::new(EventName::ApplicationFocusChange, Source::Native, at).duration_ms(3_400)
}

#[test]
fn sequence_numbers_start_at_one_and_survive_a_restart() {
    let dir = TempDir::new();
    {
        let queue = EventQueue::open(&dir.0, SESSION).expect("open");
        assert_eq!(queue.seq_high(), 0);
        let seqs: Vec<u64> = (0..3)
            .map(|i| queue.append(draft(i)).expect("append").seq)
            .collect();
        assert_eq!(seqs, [1, 2, 3]);
    }
    let queue = EventQueue::open(&dir.0, SESSION).expect("reopen");
    assert_eq!(queue.seq_high(), 3);
    assert_eq!(queue.append(draft(9)).expect("append").seq, 4);
    let pending: Vec<u64> = queue.pending(0, 10).iter().map(|e| e.seq).collect();
    assert_eq!(pending, [1, 2, 3, 4], "nothing acknowledged yet");
}

#[test]
fn acknowledgements_persist_and_drop_sent_events() {
    let dir = TempDir::new();
    {
        let queue = EventQueue::open(&dir.0, SESSION).expect("open");
        for i in 0..5 {
            queue.append(draft(i)).expect("append");
        }
        queue.record_ack(3).expect("ack");
        assert_eq!(queue.acked_through(), 3);
        queue.record_ack(2).expect("an older ack never moves back");
        assert_eq!(queue.acked_through(), 3);
    }
    let queue = EventQueue::open(&dir.0, SESSION).expect("reopen");
    assert_eq!(queue.acked_through(), 3);
    let pending: Vec<u64> = queue
        .pending(queue.acked_through(), 10)
        .iter()
        .map(|e| e.seq)
        .collect();
    assert_eq!(pending, [4, 5]);
    assert_eq!(
        queue
            .events(&[2, 5, 99])
            .iter()
            .map(|e| e.seq)
            .collect::<Vec<_>>(),
        [5]
    );
}

#[test]
fn pending_batches_respect_the_limit() {
    let dir = TempDir::new();
    let queue = EventQueue::open(&dir.0, SESSION).expect("open");
    for i in 0..7 {
        queue.append(draft(i)).expect("append");
    }
    let first: Vec<u64> = queue.pending(0, 3).iter().map(|e| e.seq).collect();
    assert_eq!(first, [1, 2, 3]);
    let next: Vec<u64> = queue.pending(3, 3).iter().map(|e| e.seq).collect();
    assert_eq!(next, [4, 5, 6]);
}

#[test]
fn a_torn_last_line_is_dropped_and_its_number_reused_safely() {
    let dir = TempDir::new();
    let file = {
        let queue = EventQueue::open(&dir.0, SESSION).expect("open");
        queue.append(draft(1)).expect("append");
        queue.append(draft(2)).expect("append");
        queue.dir().join("events.jsonl")
    };
    // A crash in the middle of writing event 3: it was never sent.
    let mut handle = std::fs::OpenOptions::new()
        .append(true)
        .open(&file)
        .expect("events file");
    handle
        .write_all(br#"{"seq":3,"event":"APPLICATION_FO"#)
        .expect("torn write");
    drop(handle);

    let queue = EventQueue::open(&dir.0, SESSION).expect("reopen");
    assert_eq!(queue.seq_high(), 2);
    assert_eq!(queue.append(draft(3)).expect("append").seq, 3);
    drop(queue);
    let queue = EventQueue::open(&dir.0, SESSION).expect("reopen again");
    let seqs: Vec<u64> = queue.pending(0, 10).iter().map(|e| e.seq).collect();
    assert_eq!(seqs, [1, 2, 3], "the file is whole again");
}

#[test]
fn a_corrupt_complete_line_never_has_its_number_reused() {
    let dir = TempDir::new();
    let file = {
        let queue = EventQueue::open(&dir.0, SESSION).expect("open");
        queue.append(draft(1)).expect("append");
        queue.dir().join("events.jsonl")
    };
    let mut handle = std::fs::OpenOptions::new()
        .append(true)
        .open(&file)
        .expect("events file");
    handle
        .write_all(b"garbage that was once event 2\n")
        .expect("corrupt");
    drop(handle);

    let queue = EventQueue::open(&dir.0, SESSION).expect("reopen");
    assert_eq!(queue.append(draft(3)).expect("append").seq, 3);
}

#[test]
fn the_server_acknowledgement_raises_the_floor_of_a_fresh_queue() {
    let dir = TempDir::new();
    let queue = EventQueue::open(&dir.0, SESSION).expect("open");
    // The local queue was lost, but the server already holds 1..=40.
    queue.record_ack(40).expect("ack");
    assert_eq!(queue.append(draft(1)).expect("append").seq, 41);
}

#[test]
fn session_ids_cannot_escape_the_queue_directory() {
    let dir = TempDir::new();
    let queue = EventQueue::open(&dir.0, r"..\..\evil").expect("open");
    assert!(queue.dir().starts_with(&dir.0));
    assert!(EventQueue::open(&dir.0, "").is_err());
}

#[test]
fn purging_removes_the_session_directory() {
    let dir = TempDir::new();
    let queue = EventQueue::open(&dir.0, SESSION).expect("open");
    queue.append(draft(1)).expect("append");
    let path = queue.dir().to_owned();
    queue.purge().expect("purge");
    assert!(!path.exists());
}
