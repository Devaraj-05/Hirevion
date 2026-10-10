//! The durable event queue: one directory per proctor session.
//!
//! - `events.jsonl` is append-only, one [`ProctorEvent`] per line, flushed to disk before
//!   `append` returns (and so before the event can be sent).
//! - `state.json` holds `acked_through`, replaced atomically.
//!
//! `seq` is assigned at append and never reused: on open the queue continues after the highest
//! number on disk. A torn last line (a crash mid-write) was never sent, so it is cut off and
//! its number may be given again; a complete line that doesn't parse keeps its (unknown)
//! number burnt.

use std::collections::BTreeMap;
use std::fs::{File, OpenOptions};
use std::io::{self, Write as _};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, PoisonError};

use serde::{Deserialize, Serialize};
use tokio::sync::Notify;

use crate::event::{EventDraft, ProctorEvent};

const EVENTS: &str = "events.jsonl";
const STATE: &str = "state.json";
const STATE_TMP: &str = "state.json.tmp";

#[derive(Debug, Default, Serialize, Deserialize)]
struct State {
    acked_through: u64,
}

struct Inner {
    file: File,
    next_seq: u64,
    acked_through: u64,
    /// Events not yet acknowledged, by `seq`.
    unacked: BTreeMap<u64, ProctorEvent>,
}

/// The events of one proctor session, on disk until the server acknowledges them.
pub struct EventQueue {
    dir: PathBuf,
    inner: Mutex<Inner>,
    appended: Arc<Notify>,
}

impl std::fmt::Debug for EventQueue {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("EventQueue")
            .field("dir", &self.dir)
            .field("seq_high", &self.seq_high())
            .field("acked_through", &self.acked_through())
            .finish()
    }
}

impl EventQueue {
    /// Opens (or creates) the queue of `proctor_session_id` under `root`.
    pub fn open(root: &Path, proctor_session_id: &str) -> io::Result<Self> {
        let name: String = proctor_session_id
            .chars()
            .map(|c| {
                if c.is_ascii_alphanumeric() || c == '-' {
                    c
                } else {
                    '_'
                }
            })
            .collect();
        if name.trim_matches('_').is_empty() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "the proctor session id is empty",
            ));
        }
        let dir = root.join(name);
        std::fs::create_dir_all(&dir)?;

        let state: State = match std::fs::read(dir.join(STATE)) {
            Ok(bytes) => serde_json::from_slice(&bytes).unwrap_or_default(),
            Err(e) if e.kind() == io::ErrorKind::NotFound => State::default(),
            Err(e) => return Err(e),
        };

        let path = dir.join(EVENTS);
        let text = match std::fs::read(&path) {
            Ok(text) => text,
            Err(e) if e.kind() == io::ErrorKind::NotFound => Vec::new(),
            Err(e) => return Err(e),
        };
        // Cut a torn last line off before anything is appended after it. (An append-only
        // handle may not truncate on Windows, so this uses a write handle of its own.)
        let whole = text.iter().rposition(|&b| b == b'\n').map_or(0, |i| i + 1);
        if whole < text.len() {
            let file = OpenOptions::new().write(true).open(&path)?;
            file.set_len(u64::try_from(whole).unwrap_or(0))?;
            file.sync_data()?;
        }
        let file = OpenOptions::new().append(true).create(true).open(&path)?;

        let mut highest = 0u64;
        let mut burnt = 0u64;
        let mut unacked = BTreeMap::new();
        for line in text[..whole].split(|&b| b == b'\n') {
            if line.iter().all(u8::is_ascii_whitespace) {
                continue;
            }
            match serde_json::from_slice::<ProctorEvent>(line) {
                Ok(event) => {
                    highest = highest.max(event.seq);
                    if event.seq > state.acked_through {
                        unacked.insert(event.seq, event);
                    }
                }
                Err(_) => burnt += 1,
            }
        }
        let next_seq = (highest + burnt).max(state.acked_through) + 1;
        Ok(Self {
            dir,
            inner: Mutex::new(Inner {
                file,
                next_seq,
                acked_through: state.acked_through,
                unacked,
            }),
            appended: Arc::new(Notify::new()),
        })
    }

    /// The session's directory.
    pub fn dir(&self) -> &Path {
        &self.dir
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, Inner> {
        self.inner.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// Numbers the draft, writes it to disk and wakes the uploader.
    pub fn append(&self, draft: EventDraft) -> io::Result<ProctorEvent> {
        let event = {
            let mut inner = self.lock();
            let event = draft.into_event(inner.next_seq);
            let mut line = serde_json::to_vec(&event).map_err(io::Error::other)?;
            line.push(b'\n');
            inner.file.write_all(&line)?;
            inner.file.sync_data()?;
            inner.next_seq += 1;
            inner.unacked.insert(event.seq, event.clone());
            event
        };
        self.appended.notify_one();
        Ok(event)
    }

    /// Appends several drafts in order.
    pub fn append_all(
        &self,
        drafts: impl IntoIterator<Item = EventDraft>,
    ) -> io::Result<Vec<ProctorEvent>> {
        drafts.into_iter().map(|d| self.append(d)).collect()
    }

    /// The highest `seq` given out (`0` when none).
    pub fn seq_high(&self) -> u64 {
        self.lock().next_seq - 1
    }

    /// The highest `seq` the server acknowledged with everything before it.
    pub fn acked_through(&self) -> u64 {
        self.lock().acked_through
    }

    /// Records the server's `acked_through`: drops what it covers and persists it. The next
    /// `seq` is never at or below it, even when the local queue was lost.
    pub fn record_ack(&self, acked_through: u64) -> io::Result<()> {
        let mut inner = self.lock();
        if acked_through <= inner.acked_through {
            return Ok(());
        }
        inner.acked_through = acked_through;
        inner.next_seq = inner.next_seq.max(acked_through + 1);
        inner.unacked = inner.unacked.split_off(&(acked_through + 1));
        let tmp = self.dir.join(STATE_TMP);
        let mut file = File::create(&tmp)?;
        file.write_all(&serde_json::to_vec(&State { acked_through }).map_err(io::Error::other)?)?;
        file.sync_data()?;
        drop(file);
        std::fs::rename(tmp, self.dir.join(STATE))
    }

    /// Up to `limit` unacknowledged events numbered above `after`, in order.
    pub fn pending(&self, after: u64, limit: usize) -> Vec<ProctorEvent> {
        self.lock()
            .unacked
            .range(after + 1..)
            .take(limit)
            .map(|(_, e)| e.clone())
            .collect()
    }

    /// The unacknowledged events among `seqs` (what the server listed as missing).
    pub fn events(&self, seqs: &[u64]) -> Vec<ProctorEvent> {
        let inner = self.lock();
        seqs.iter()
            .filter_map(|seq| inner.unacked.get(seq).cloned())
            .collect()
    }

    /// Whether every event was acknowledged.
    pub fn is_drained(&self) -> bool {
        self.lock().unacked.is_empty()
    }

    /// Notified on every append (the uploader waits on it).
    pub fn appended(&self) -> Arc<Notify> {
        self.appended.clone()
    }

    /// Deletes the session's files (after the interview completes and everything was sent).
    pub fn purge(self) -> io::Result<()> {
        let dir = self.dir.clone();
        drop(self);
        std::fs::remove_dir_all(dir)
    }
}
