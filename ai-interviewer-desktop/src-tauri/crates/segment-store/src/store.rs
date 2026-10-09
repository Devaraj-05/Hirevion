//! The store: encrypted files under `<root>/<interview>/<track>/<seq>.seg` and a SQLite
//! manifest at `<root>/manifest.sqlite3`.

use std::collections::HashMap;
use std::io::Write as _;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, MutexGuard, PoisonError};

use aes_gcm::aead::OsRng;
use aes_gcm::aead::rand_core::RngCore as _;
use hv_security::Vault;
use rusqlite::{Connection, OptionalExtension as _, Row, params};
use serde::Serialize;
use zeroize::Zeroizing;

use crate::contract::{MAX_SEGMENT_BYTES, MAX_SEGMENT_MS, canonical_interview_id, check_format};
use crate::file::{self, FileHeader, sha256_hex};
use crate::{Codec, Container, SegmentState, StoreError, Track};

/// The manifest's file name inside the store's root.
pub const MANIFEST_FILE: &str = "manifest.sqlite3";
const SEGMENT_EXTENSION: &str = "seg";
const TEMP_EXTENSION: &str = "tmp";
const UNREADABLE_EXTENSION: &str = "unreadable";

const SCHEMA: &str = "
CREATE TABLE IF NOT EXISTS segments (
    id            INTEGER PRIMARY KEY,
    interview_id  TEXT    NOT NULL,
    track         TEXT    NOT NULL,
    seq           INTEGER NOT NULL,
    started_at_ms INTEGER NOT NULL,
    duration_ms   INTEGER NOT NULL,
    bytes         INTEGER NOT NULL,
    sha256        TEXT    NOT NULL,
    container     TEXT    NOT NULL,
    codec         TEXT    NOT NULL,
    state         TEXT    NOT NULL,
    attempts      INTEGER NOT NULL DEFAULT 0,
    segment_id    TEXT,
    last_error    TEXT,
    updated_at_ms INTEGER NOT NULL,
    UNIQUE (interview_id, track, seq)
);
CREATE INDEX IF NOT EXISTS segments_by_state ON segments (interview_id, state);
";

const COLUMNS: &str = "id, interview_id, track, seq, started_at_ms, duration_ms, bytes, sha256, \
                       container, codec, state, attempts, segment_id, last_error";

/// A segment to store.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NewSegment {
    pub interview_id: String,
    pub track: Track,
    /// From 0 per track.
    pub seq: u64,
    /// The first frame's time, in server milliseconds since the Unix epoch.
    pub started_at_ms: i64,
    pub duration_ms: u32,
    pub container: Container,
    pub codec: Codec,
}

/// A manifest row.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Segment {
    /// The local row id.
    pub id: i64,
    pub interview_id: String,
    pub track: Track,
    pub seq: u64,
    pub started_at_ms: i64,
    pub duration_ms: u32,
    /// The plaintext's size.
    pub bytes: u64,
    /// The plaintext's SHA-256, lower-case hex.
    pub sha256: String,
    pub container: Container,
    pub codec: Codec,
    pub state: SegmentState,
    /// Failed upload attempts so far.
    pub attempts: u32,
    /// The server's id, once an upload URL was issued.
    pub segment_id: Option<String>,
    /// The last failure's code.
    pub last_error: Option<String>,
}

/// What [`SegmentStore::open`] repaired.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Recovery {
    /// Half-written files from an interrupted write (at most one per writer), deleted.
    pub temp_files_removed: usize,
    /// Complete files whose manifest row was never committed, added back from their header.
    pub adopted: usize,
    /// Files that couldn't be adopted (no key, not authentic); renamed to `*.unreadable`.
    pub unreadable: usize,
    /// Uploads that were under way, back in the queue.
    pub uploads_reset: usize,
    /// Acknowledged segments whose file was still on disk, now deleted.
    pub purged: usize,
    /// Pending segments whose file is gone, now `lost`.
    pub lost: usize,
}

/// Per-interview totals, for the recording status.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
pub struct Counts {
    pub pending: u64,
    pub pending_bytes: u64,
    /// Acknowledged or purged.
    pub acknowledged: u64,
    pub lost: u64,
    pub rejected: u64,
}

/// The encrypted local queue of recording segments (PRD §51).
///
/// - Every segment is AES-256-GCM encrypted with a random per-interview key that lives only
///   in the DPAPI [`Vault`] (`rec-key-<interview>`).
/// - A segment's file is written to a temporary name, flushed and renamed before its manifest
///   row is committed, so a crash never leaves a row without a complete file. On open, temp
///   files are deleted and complete files without a row are adopted from their header.
/// - The local file is deleted only by [`SegmentStore::purge`], which requires the server's
///   acknowledgement.
///
/// All methods are synchronous and short (one file, one transaction); the store is `Sync`.
pub struct SegmentStore {
    root: PathBuf,
    vault: Vault,
    db: Mutex<Connection>,
    keys: Mutex<HashMap<String, Zeroizing<[u8; 32]>>>,
}

impl std::fmt::Debug for SegmentStore {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("SegmentStore")
            .field("root", &self.root)
            .finish_non_exhaustive()
    }
}

impl SegmentStore {
    /// Opens (or creates) the store in `root`, then repairs whatever a crash left behind.
    pub fn open(root: impl Into<PathBuf>, vault: Vault) -> Result<(Self, Recovery), StoreError> {
        let root = root.into();
        std::fs::create_dir_all(&root)?;
        let db = Connection::open(root.join(MANIFEST_FILE))?;
        // WAL with FULL sync: a committed transaction survives a power loss.
        db.pragma_update(None, "journal_mode", "WAL")?;
        db.pragma_update(None, "synchronous", "FULL")?;
        db.busy_timeout(std::time::Duration::from_secs(5))?;
        db.execute_batch(SCHEMA)?;
        let store = Self {
            root,
            vault,
            db: Mutex::new(db),
            keys: Mutex::new(HashMap::new()),
        };
        let recovery = store.recover()?;
        Ok((store, recovery))
    }

    /// Encrypts and stores a segment, durably, in state `captured`.
    ///
    /// Storing the same segment again (same interview, track, seq and bytes) returns the
    /// existing row; different bytes under the same name are a [`StoreError::Conflict`].
    pub fn put(&self, new: NewSegment, plain: &[u8]) -> Result<Segment, StoreError> {
        let interview_id = canonical_interview_id(&new.interview_id).ok_or_else(|| {
            StoreError::Contract(format!("{:?} isn't an interview id", new.interview_id))
        })?;
        check_format(new.track, new.container, new.codec).map_err(StoreError::Contract)?;
        if plain.is_empty() || plain.len() > MAX_SEGMENT_BYTES {
            return Err(StoreError::Contract(format!(
                "a segment is 1 to {MAX_SEGMENT_BYTES} bytes, not {}",
                plain.len()
            )));
        }
        if !(1..=MAX_SEGMENT_MS).contains(&new.duration_ms) {
            return Err(StoreError::Contract(format!(
                "a segment lasts 1 to {MAX_SEGMENT_MS} ms, not {}",
                new.duration_ms
            )));
        }
        let seq =
            i64::try_from(new.seq).map_err(|_| StoreError::Contract("seq out of range".into()))?;

        let header = FileHeader {
            interview_id,
            track: new.track,
            seq: new.seq,
            started_at_ms: new.started_at_ms,
            duration_ms: new.duration_ms,
            bytes: plain.len() as u64,
            sha256: sha256_hex(plain),
            container: new.container,
            codec: new.codec,
        };
        if let Some(existing) = self.find(&header.interview_id, &header.track, new.seq)? {
            return if existing.sha256 == header.sha256 && existing.bytes == header.bytes {
                Ok(existing)
            } else {
                Err(StoreError::Conflict(format!(
                    "{}/{}/{}",
                    header.interview_id, header.track, header.seq
                )))
            };
        }

        let key = self.key(&header.interview_id, true)?;
        let sealed = file::seal(&key, &header, plain)?;
        let path = self.path_of(&header.interview_id, header.track, header.seq);
        write_atomically(&path, &sealed)?;

        let id = {
            let db = self.db();
            db.execute(
                "INSERT INTO segments (interview_id, track, seq, started_at_ms, duration_ms, \
                 bytes, sha256, container, codec, state, updated_at_ms) \
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)",
                params![
                    header.interview_id,
                    header.track.to_string(),
                    seq,
                    header.started_at_ms,
                    header.duration_ms,
                    i64::try_from(header.bytes).unwrap_or(i64::MAX),
                    header.sha256,
                    header.container.as_str(),
                    header.codec.as_str(),
                    SegmentState::Captured.as_str(),
                    now_ms(),
                ],
            )
            .map_err(|error| match error {
                rusqlite::Error::SqliteFailure(e, _)
                    if e.code == rusqlite::ErrorCode::ConstraintViolation =>
                {
                    StoreError::Conflict(format!(
                        "{}/{}/{}",
                        header.interview_id, header.track, header.seq
                    ))
                }
                other => other.into(),
            })?;
            db.last_insert_rowid()
        };
        self.get(id)?.ok_or(StoreError::NotFound(id))
    }

    /// Decrypts a segment and checks it against its manifest row.
    pub fn read(&self, id: i64) -> Result<Vec<u8>, StoreError> {
        let row = self.get(id)?.ok_or(StoreError::NotFound(id))?;
        let path = self.segment_path(&row);
        let key = self.key(&row.interview_id, false)?;
        let bytes = match std::fs::read(&path) {
            Ok(bytes) => bytes,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                return Err(StoreError::FileMissing(path.display().to_string()));
            }
            Err(error) => return Err(error.into()),
        };
        let (header, plain) = file::open(&key, &bytes)?;
        let matches_row = header.interview_id == row.interview_id
            && header.track == row.track
            && header.seq == row.seq
            && header.sha256 == row.sha256
            && header.bytes == row.bytes;
        if !matches_row {
            return Err(StoreError::Corrupt(format!(
                "{} doesn't belong to segment {id}",
                path.display()
            )));
        }
        Ok(plain)
    }

    /// The row with this id.
    pub fn get(&self, id: i64) -> Result<Option<Segment>, StoreError> {
        let db = self.db();
        let sql = format!("SELECT {COLUMNS} FROM segments WHERE id = ?1");
        Ok(db.query_row(&sql, params![id], row_to_segment).optional()?)
    }

    /// The row for one interview, track and seq.
    pub fn find(
        &self,
        interview_id: &str,
        track: &Track,
        seq: u64,
    ) -> Result<Option<Segment>, StoreError> {
        let Ok(seq) = i64::try_from(seq) else {
            return Ok(None);
        };
        let db = self.db();
        let sql = format!(
            "SELECT {COLUMNS} FROM segments WHERE interview_id = ?1 AND track = ?2 AND seq = ?3"
        );
        Ok(db
            .query_row(
                &sql,
                params![interview_id, track.to_string(), seq],
                row_to_segment,
            )
            .optional()?)
    }

    /// Segments that still need the server, oldest first.
    pub fn pending(&self, interview_id: &str) -> Result<Vec<Segment>, StoreError> {
        self.select(
            "WHERE interview_id = ?1 AND state IN ('captured', 'queued', 'uploading', 'uploaded') \
             ORDER BY started_at_ms, track, seq",
            interview_id,
        )
    }

    /// Every row of an interview, in the order they were stored.
    pub fn all(&self, interview_id: &str) -> Result<Vec<Segment>, StoreError> {
        self.select("WHERE interview_id = ?1 ORDER BY id", interview_id)
    }

    /// Interviews with segments still to upload (for the next launch after a crash).
    pub fn interviews_with_pending(&self) -> Result<Vec<String>, StoreError> {
        let db = self.db();
        let mut statement = db.prepare(
            "SELECT DISTINCT interview_id FROM segments \
             WHERE state IN ('captured', 'queued', 'uploading', 'uploaded') ORDER BY interview_id",
        )?;
        let ids = statement
            .query_map([], |row| row.get::<_, String>(0))?
            .collect::<Result<Vec<_>, _>>()?;
        Ok(ids)
    }

    /// Totals per state for an interview.
    pub fn counts(&self, interview_id: &str) -> Result<Counts, StoreError> {
        let db = self.db();
        let mut statement = db.prepare(
            "SELECT state, COUNT(*), COALESCE(SUM(bytes), 0) FROM segments \
             WHERE interview_id = ?1 GROUP BY state",
        )?;
        let mut counts = Counts::default();
        let rows = statement.query_map(params![interview_id], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, i64>(1)?,
                row.get::<_, i64>(2)?,
            ))
        })?;
        for row in rows {
            let (state, count, bytes) = row?;
            let count = u64::try_from(count).unwrap_or(0);
            match state.parse::<SegmentState>() {
                Ok(state) if state.is_pending() => {
                    counts.pending += count;
                    counts.pending_bytes += u64::try_from(bytes).unwrap_or(0);
                }
                Ok(SegmentState::Acknowledged | SegmentState::Purged) => {
                    counts.acknowledged += count;
                }
                Ok(SegmentState::Lost) => counts.lost += count,
                Ok(SegmentState::Rejected) => counts.rejected += count,
                _ => {}
            }
        }
        Ok(counts)
    }

    /// Moves a segment to `to`, if the state machine allows it.
    pub fn transition(&self, id: i64, to: SegmentState) -> Result<Segment, StoreError> {
        self.update(id, to, |_| Update::default())
    }

    /// `captured → queued`: the uploader has taken the segment.
    pub fn enqueue(&self, id: i64) -> Result<Segment, StoreError> {
        self.transition(id, SegmentState::Queued)
    }

    /// `queued → uploading`, remembering the server's segment id.
    pub fn start_upload(&self, id: i64, segment_id: &str) -> Result<Segment, StoreError> {
        let segment_id = segment_id.to_owned();
        self.update(id, SegmentState::Uploading, move |_| Update {
            segment_id: Some(segment_id),
            ..Update::default()
        })
    }

    /// A failed attempt: back to `queued` (from `uploading` or `uploaded`), or still `queued`,
    /// with the attempt counted and `error` remembered.
    pub fn retry(&self, id: i64, error: &str) -> Result<Segment, StoreError> {
        let error = error.to_owned();
        self.update(id, SegmentState::Queued, move |_| Update {
            failed: Some(error),
            same_state_ok: true,
            ..Update::default()
        })
    }

    /// The server acknowledged the segment (or already had it).
    pub fn acknowledge(&self, id: i64) -> Result<Segment, StoreError> {
        self.transition(id, SegmentState::Acknowledged)
    }

    /// The server refuses this segment for good (`code` is the problem code).
    pub fn reject(&self, id: i64, code: &str) -> Result<Segment, StoreError> {
        let code = code.to_owned();
        self.update(id, SegmentState::Rejected, move |_| Update {
            note: Some(code),
            ..Update::default()
        })
    }

    /// The segment's file is gone or unreadable.
    pub fn mark_lost(&self, id: i64, why: &str) -> Result<Segment, StoreError> {
        let why = why.to_owned();
        self.update(id, SegmentState::Lost, move |_| Update {
            note: Some(why),
            ..Update::default()
        })
    }

    /// Deletes an acknowledged segment's file and marks it `purged`. Refused for anything the
    /// server hasn't acknowledged.
    pub fn purge(&self, id: i64) -> Result<Segment, StoreError> {
        let row = self.get(id)?.ok_or(StoreError::NotFound(id))?;
        if !row.state.allows(SegmentState::Purged) {
            return Err(StoreError::InvalidTransition {
                id,
                from: row.state,
                to: SegmentState::Purged,
            });
        }
        remove_if_present(&self.segment_path(&row))?;
        self.transition(id, SegmentState::Purged)
    }

    /// Once nothing of the interview is pending, deletes its key (making any remaining files
    /// unreadable) and its folder. Returns whether it did.
    pub fn forget_interview(&self, interview_id: &str) -> Result<bool, StoreError> {
        let Some(interview_id) = canonical_interview_id(interview_id) else {
            return Ok(false);
        };
        if !self.pending(&interview_id)?.is_empty() {
            return Ok(false);
        }
        self.vault.delete(&key_name(&interview_id))?;
        self.keys_lock().remove(&interview_id);
        match std::fs::remove_dir_all(self.root.join(&interview_id)) {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(error.into()),
        }
        Ok(true)
    }

    /// Where a segment's encrypted file lives.
    #[must_use]
    pub fn segment_path(&self, segment: &Segment) -> PathBuf {
        self.path_of(&segment.interview_id, segment.track, segment.seq)
    }

    fn path_of(&self, interview_id: &str, track: Track, seq: u64) -> PathBuf {
        self.root
            .join(interview_id)
            .join(track.to_string())
            .join(format!("{seq:010}.{SEGMENT_EXTENSION}"))
    }

    fn select(&self, clause: &str, interview_id: &str) -> Result<Vec<Segment>, StoreError> {
        let db = self.db();
        let sql = format!("SELECT {COLUMNS} FROM segments {clause}");
        let mut statement = db.prepare(&sql)?;
        let rows = statement
            .query_map(params![interview_id], row_to_segment)?
            .collect::<Result<Vec<_>, _>>()?;
        Ok(rows)
    }

    fn update(
        &self,
        id: i64,
        to: SegmentState,
        change: impl FnOnce(&Segment) -> Update,
    ) -> Result<Segment, StoreError> {
        {
            let mut db = self.db();
            let tx = db.transaction()?;
            let sql = format!("SELECT {COLUMNS} FROM segments WHERE id = ?1");
            let row = tx
                .query_row(&sql, params![id], row_to_segment)
                .optional()?
                .ok_or(StoreError::NotFound(id))?;
            let update = change(&row);
            let stays = update.same_state_ok && row.state == to;
            if !stays && !row.state.allows(to) {
                return Err(StoreError::InvalidTransition {
                    id,
                    from: row.state,
                    to,
                });
            }
            let attempts = row.attempts + u32::from(update.failed.is_some());
            let last_error = update
                .failed
                .or(update.note)
                .or_else(|| row.last_error.clone());
            let segment_id = update.segment_id.or_else(|| row.segment_id.clone());
            tx.execute(
                "UPDATE segments SET state = ?2, attempts = ?3, last_error = ?4, segment_id = ?5, \
                 updated_at_ms = ?6 WHERE id = ?1",
                params![id, to.as_str(), attempts, last_error, segment_id, now_ms()],
            )?;
            tx.commit()?;
        }
        self.get(id)?.ok_or(StoreError::NotFound(id))
    }

    /// The interview's key from the cache or the vault; a new random one when `create`.
    fn key(&self, interview_id: &str, create: bool) -> Result<Zeroizing<[u8; 32]>, StoreError> {
        let mut keys = self.keys_lock();
        if let Some(key) = keys.get(interview_id) {
            return Ok(key.clone());
        }
        let name = key_name(interview_id);
        let key = match self.vault.get(&name)? {
            Some(saved) => {
                let saved = Zeroizing::new(saved);
                let key: [u8; 32] = saved.as_slice().try_into().map_err(|_| {
                    StoreError::Corrupt(format!("the vault entry {name} isn't a 256-bit key"))
                })?;
                Zeroizing::new(key)
            }
            None if create => {
                let mut key = Zeroizing::new([0u8; 32]);
                OsRng.fill_bytes(key.as_mut());
                self.vault.put(&name, key.as_ref())?;
                key
            }
            None => return Err(StoreError::KeyMissing(interview_id.to_owned())),
        };
        keys.insert(interview_id.to_owned(), key.clone());
        Ok(key)
    }

    fn recover(&self) -> Result<Recovery, StoreError> {
        let mut recovery = Recovery::default();
        self.scan_files(&mut recovery)?;

        {
            let db = self.db();
            recovery.uploads_reset = db.execute(
                "UPDATE segments SET state = 'queued', updated_at_ms = ?1 WHERE state = 'uploading'",
                params![now_ms()],
            )?;
        }
        for interview_id in self.interview_ids()? {
            for row in self.all(&interview_id)? {
                let path = self.segment_path(&row);
                if row.state == SegmentState::Acknowledged {
                    self.purge(row.id)?;
                    recovery.purged += 1;
                } else if row.state.is_pending() && !path.exists() {
                    self.mark_lost(row.id, "file-missing")?;
                    recovery.lost += 1;
                }
            }
        }
        Ok(recovery)
    }

    /// Deletes temp files and adopts complete files that have no manifest row.
    fn scan_files(&self, recovery: &mut Recovery) -> Result<(), StoreError> {
        for interview in read_dirs(&self.root)? {
            for track_dir in read_dirs(&interview)? {
                for entry in std::fs::read_dir(&track_dir)? {
                    let path = entry?.path();
                    let extension = path.extension().and_then(|e| e.to_str());
                    if extension == Some(TEMP_EXTENSION) {
                        remove_if_present(&path)?;
                        recovery.temp_files_removed += 1;
                    } else if extension == Some(SEGMENT_EXTENSION) {
                        match self.adopt(&path) {
                            Ok(true) => recovery.adopted += 1,
                            Ok(false) => {}
                            Err(_) => {
                                std::fs::rename(&path, path.with_extension(UNREADABLE_EXTENSION))?;
                                recovery.unreadable += 1;
                            }
                        }
                    }
                }
            }
        }
        Ok(())
    }

    /// Adds a row for a complete segment file that has none. `Ok(false)` when it has one.
    fn adopt(&self, path: &Path) -> Result<bool, StoreError> {
        let bytes = std::fs::read(path)?;
        let (header, _) = file::peek_header(&bytes)?;
        if self.path_of(&header.interview_id, header.track, header.seq) != path {
            return Err(StoreError::Corrupt(format!(
                "{} isn't where its header says",
                path.display()
            )));
        }
        if self
            .find(&header.interview_id, &header.track, header.seq)?
            .is_some()
        {
            return Ok(false);
        }
        let key = self.key(&header.interview_id, false)?;
        let (header, _) = file::open(&key, &bytes)?;
        let db = self.db();
        db.execute(
            "INSERT INTO segments (interview_id, track, seq, started_at_ms, duration_ms, bytes, \
             sha256, container, codec, state, updated_at_ms) \
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, 'captured', ?10)",
            params![
                header.interview_id,
                header.track.to_string(),
                i64::try_from(header.seq).unwrap_or(i64::MAX),
                header.started_at_ms,
                header.duration_ms,
                i64::try_from(header.bytes).unwrap_or(i64::MAX),
                header.sha256,
                header.container.as_str(),
                header.codec.as_str(),
                now_ms(),
            ],
        )?;
        Ok(true)
    }

    fn interview_ids(&self) -> Result<Vec<String>, StoreError> {
        let db = self.db();
        let mut statement = db.prepare("SELECT DISTINCT interview_id FROM segments")?;
        let ids = statement
            .query_map([], |row| row.get::<_, String>(0))?
            .collect::<Result<Vec<_>, _>>()?;
        Ok(ids)
    }

    fn db(&self) -> MutexGuard<'_, Connection> {
        self.db.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn keys_lock(&self) -> MutexGuard<'_, HashMap<String, Zeroizing<[u8; 32]>>> {
        self.keys.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

/// What an [`SegmentStore::update`] changes besides the state.
#[derive(Default)]
struct Update {
    segment_id: Option<String>,
    /// A failed attempt with this error code: counts the attempt.
    failed: Option<String>,
    /// A reason to remember without counting an attempt.
    note: Option<String>,
    /// Staying in the same state is fine (a retry while still queued).
    same_state_ok: bool,
}

fn key_name(interview_id: &str) -> String {
    format!("rec-key-{interview_id}")
}

fn row_to_segment(row: &Row<'_>) -> rusqlite::Result<Segment> {
    fn parsed<T: std::str::FromStr<Err = String>>(
        row: &Row<'_>,
        index: usize,
    ) -> rusqlite::Result<T> {
        row.get::<_, String>(index)?.parse::<T>().map_err(|error| {
            rusqlite::Error::FromSqlConversionFailure(
                index,
                rusqlite::types::Type::Text,
                error.into(),
            )
        })
    }
    Ok(Segment {
        id: row.get(0)?,
        interview_id: row.get(1)?,
        track: parsed(row, 2)?,
        seq: u64::try_from(row.get::<_, i64>(3)?).unwrap_or(0),
        started_at_ms: row.get(4)?,
        duration_ms: row.get(5)?,
        bytes: u64::try_from(row.get::<_, i64>(6)?).unwrap_or(0),
        sha256: row.get(7)?,
        container: parsed(row, 8)?,
        codec: parsed(row, 9)?,
        state: parsed(row, 10)?,
        attempts: row.get(11)?,
        segment_id: row.get(12)?,
        last_error: row.get(13)?,
    })
}

/// Writes `bytes` to a temporary file next to `path`, flushes it to disk and renames it into
/// place, so `path` is either absent or complete.
fn write_atomically(path: &Path, bytes: &[u8]) -> Result<(), StoreError> {
    let parent = path
        .parent()
        .ok_or_else(|| StoreError::Corrupt("segment path has no folder".into()))?;
    std::fs::create_dir_all(parent)?;
    let stem = path
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("segment");
    let temp = parent.join(format!(
        ".{stem}.{}.{TEMP_EXTENSION}",
        uuid::Uuid::new_v4().simple()
    ));
    let written = (|| {
        let mut file = std::fs::File::create(&temp)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        drop(file);
        std::fs::rename(&temp, path)
    })();
    if let Err(error) = written {
        let _ = std::fs::remove_file(&temp);
        return Err(error.into());
    }
    Ok(())
}

fn remove_if_present(path: &Path) -> Result<(), StoreError> {
    match std::fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error.into()),
    }
}

fn read_dirs(dir: &Path) -> Result<Vec<PathBuf>, StoreError> {
    let mut dirs = Vec::new();
    for entry in std::fs::read_dir(dir)? {
        let entry = entry?;
        if entry.file_type()?.is_dir() {
            dirs.push(entry.path());
        }
    }
    Ok(dirs)
}

fn now_ms() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |d| i64::try_from(d.as_millis()).unwrap_or(i64::MAX))
}
