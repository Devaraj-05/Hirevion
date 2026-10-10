//! The upload loop: one segment at a time, oldest first, each failure on its own backoff.

use std::collections::{HashMap, HashSet};
use std::future::Future;
use std::pin::Pin;
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};
use std::time::Duration;

use hv_api_client::{ApiClient, ApiError};
use hv_segment_store::{Segment, SegmentState, SegmentStore, StoreError, Track};
use tokio::sync::{Notify, broadcast, watch};
use tokio::time::Instant;

use crate::backoff::{self, DEFAULT_BASE, DEFAULT_CAP};
use crate::bandwidth::Bandwidth;
use crate::{api, put, time};

/// A boxed future that yields an interview-session token.
pub type TokenFuture<'a> = Pin<Box<dyn Future<Output = Result<String, ApiError>> + Send + 'a>>;

/// What the uploader needs from the app: the DPoP client and the interview-session token.
pub trait RecordingSession: Send + Sync {
    /// The client that signs every call with the device key.
    fn api(&self) -> &ApiClient;
    /// A valid interview-session token for the interview being uploaded.
    fn token(&self) -> TokenFuture<'_>;
}

/// Tuning. The defaults follow the contracts README.
#[derive(Debug, Clone)]
pub struct UploaderConfig {
    /// The first retry waits about this long; each retry doubles it.
    pub backoff_base: Duration,
    /// No retry waits longer (except for a server's `Retry-After`).
    pub backoff_cap: Duration,
    /// The PUT body is paced in pieces of this size.
    pub chunk_bytes: usize,
    /// Allow `http://` upload URLs to the loopback address (a local blob emulator). Only
    /// debug builds allow it by default.
    pub allow_insecure_loopback: bool,
    /// [`Uploader::run`] looks at the store at least this often, even without a wake-up.
    pub idle_poll: Duration,
}

impl Default for UploaderConfig {
    fn default() -> Self {
        Self {
            backoff_base: DEFAULT_BASE,
            backoff_cap: DEFAULT_CAP,
            chunk_bytes: 64 * 1024,
            allow_insecure_loopback: cfg!(debug_assertions),
            idle_poll: Duration::from_secs(5),
        }
    }
}

/// What happened to segments, for `RECORDING_STATUS` and the candidate's indicator.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum UploadEvent {
    /// The server verified the segment; the local copy is deleted.
    Acknowledged { track: Track, seq: u64 },
    /// An attempt failed; the segment waits `delay` and tries again.
    Retrying {
        track: Track,
        seq: u64,
        code: String,
        delay: Duration,
    },
    /// The server refuses the segment for good (`segment-too-large`, `track-not-recorded`).
    Rejected {
        track: Track,
        seq: u64,
        code: String,
    },
    /// `track-not-recorded`: the interview doesn't record this track. Stop recording it.
    TrackRefused { track: Track },
    /// The local file is gone or unreadable; the server will see a gap.
    Lost {
        track: Track,
        seq: u64,
        reason: String,
    },
    /// The recovery listing couldn't be fetched; everything pending is uploaded anyway.
    RecoveryFailed { code: String },
}

/// What [`Uploader::recover`] found.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct RecoverySummary {
    /// Local segments the server already acknowledged, now deleted.
    pub already_acknowledged: usize,
    /// Local segments still to upload.
    pub to_upload: usize,
}

/// Fatal uploader errors: the store failed, or the uploader couldn't be built. Network and
/// server failures are retried, never returned.
#[derive(Debug, thiserror::Error)]
pub enum UploadError {
    #[error(transparent)]
    Store(#[from] StoreError),
    #[error(transparent)]
    Api(#[from] ApiError),
    #[error("uploader setup: {0}")]
    Setup(String),
}

enum Step {
    Worked,
    Empty,
    Wait(Instant),
}

enum Outcome {
    Done,
    Retry(Duration),
}

/// Uploads one interview's segments from the [`SegmentStore`] (recordings contract):
/// upload URL → throttled PUT → hash-verified ack → delete the local copy.
pub struct Uploader {
    session: Arc<dyn RecordingSession>,
    store: Arc<SegmentStore>,
    config: UploaderConfig,
    http: reqwest::Client,
    bandwidth: Bandwidth,
    wake: Notify,
    events: broadcast::Sender<UploadEvent>,
    refused: Mutex<HashSet<(String, Track)>>,
    not_before: Mutex<HashMap<i64, Instant>>,
}

impl std::fmt::Debug for Uploader {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Uploader")
            .field("store", &self.store)
            .field("config", &self.config)
            .field("bandwidth", &self.bandwidth.limit())
            .finish_non_exhaustive()
    }
}

impl Uploader {
    pub fn new(
        session: Arc<dyn RecordingSession>,
        store: Arc<SegmentStore>,
        config: UploaderConfig,
    ) -> Result<Self, UploadError> {
        let http = put::http_client().map_err(UploadError::Setup)?;
        Ok(Self {
            session,
            store,
            config,
            http,
            bandwidth: Bandwidth::unlimited(),
            wake: Notify::new(),
            events: broadcast::channel(256).0,
            refused: Mutex::new(HashSet::new()),
            not_before: Mutex::new(HashMap::new()),
        })
    }

    /// The upload cap: lower it while live media needs the link, lift it afterwards.
    pub fn bandwidth(&self) -> &Bandwidth {
        &self.bandwidth
    }

    /// Call after storing a segment, so a waiting uploader starts at once.
    pub fn wake(&self) {
        self.wake.notify_one();
    }

    /// Events from now on.
    pub fn subscribe(&self) -> broadcast::Receiver<UploadEvent> {
        self.events.subscribe()
    }

    /// Asks the server what it already holds (`GET …/segments`): those local segments are
    /// settled and deleted, everything else is queued.
    pub async fn recover(&self, interview_id: &str) -> Result<RecoverySummary, UploadError> {
        let token = self.session.token().await?;
        let listing = api::listing(self.session.api(), &token, interview_id).await?;
        let mut summary = RecoverySummary::default();
        for segment in self.store.pending(interview_id)? {
            let held = listing
                .tracks
                .get(&segment.track.to_string())
                .is_some_and(|progress| progress.has(segment.seq));
            if held {
                self.settle(&segment)?;
                summary.already_acknowledged += 1;
            } else {
                if segment.state == SegmentState::Captured {
                    self.store.enqueue(segment.id)?;
                }
                summary.to_upload += 1;
            }
        }
        Ok(summary)
    }

    /// Recovers, then uploads until nothing of the interview is pending (waiting out
    /// backoffs). For the end of an interview and the next launch after a crash.
    pub async fn drain(&self, interview_id: &str) -> Result<(), UploadError> {
        self.recover_or_report(interview_id).await;
        loop {
            match self.step(interview_id).await? {
                Step::Worked => {}
                Step::Empty => return Ok(()),
                Step::Wait(until) => self.wait(until).await,
            }
        }
    }

    /// Recovers, then uploads as segments arrive until `stop` turns true. A segment cut off
    /// by the stop stays on disk and is resumed by the next [`Uploader::drain`] or `run`.
    pub async fn run(
        &self,
        interview_id: &str,
        mut stop: watch::Receiver<bool>,
    ) -> Result<(), UploadError> {
        tokio::select! {
            () = self.recover_or_report(interview_id) => {}
            _ = stop.wait_for(|stopped| *stopped) => return Ok(()),
        }
        loop {
            if *stop.borrow() {
                return Ok(());
            }
            let step = tokio::select! {
                step = self.step(interview_id) => step?,
                _ = stop.wait_for(|stopped| *stopped) => return Ok(()),
            };
            let idle = Instant::now() + self.config.idle_poll;
            let until = match step {
                Step::Worked => continue,
                Step::Empty => idle,
                Step::Wait(until) => until.min(idle),
            };
            tokio::select! {
                () = self.wait(until) => {}
                _ = stop.wait_for(|stopped| *stopped) => return Ok(()),
            }
        }
    }

    async fn recover_or_report(&self, interview_id: &str) {
        if let Err(error) = self.recover(interview_id).await {
            let code = match &error {
                UploadError::Api(api) => api.code().to_owned(),
                other => other.to_string(),
            };
            self.emit(UploadEvent::RecoveryFailed { code });
        }
    }

    async fn wait(&self, until: Instant) {
        tokio::select! {
            () = tokio::time::sleep_until(until) => {}
            () = self.wake.notified() => {}
        }
    }

    /// Works on the oldest segment that isn't waiting out a backoff.
    async fn step(&self, interview_id: &str) -> Result<Step, UploadError> {
        let pending = self.store.pending(interview_id)?;
        if pending.is_empty() {
            return Ok(Step::Empty);
        }
        let now = Instant::now();
        let mut earliest: Option<Instant> = None;
        for segment in pending {
            if self.is_refused(&segment) {
                self.reject(&segment, "track-not-recorded")?;
                return Ok(Step::Worked);
            }
            if let Some(&until) = self.backoffs().get(&segment.id)
                && until > now
            {
                earliest = Some(earliest.map_or(until, |e| e.min(until)));
                continue;
            }
            let id = segment.id;
            match self.process(segment).await? {
                Outcome::Done => {
                    self.backoffs().remove(&id);
                }
                Outcome::Retry(delay) => {
                    self.backoffs().insert(id, Instant::now() + delay);
                }
            }
            return Ok(Step::Worked);
        }
        Ok(earliest.map_or(Step::Worked, Step::Wait))
    }

    async fn process(&self, segment: Segment) -> Result<Outcome, UploadError> {
        let mut segment = segment;
        match segment.state {
            SegmentState::Captured => segment = self.store.enqueue(segment.id)?,
            // Cut off earlier in this run (a stop); the upload starts over.
            SegmentState::Uploading => {
                segment = self.store.transition(segment.id, SegmentState::Queued)?;
            }
            SegmentState::Uploaded => match segment.segment_id.clone() {
                Some(segment_id) => return self.ack(&segment, &segment_id).await,
                None => segment = self.store.transition(segment.id, SegmentState::Queued)?,
            },
            _ => {}
        }

        let token = match self.session.token().await {
            Ok(token) => token,
            Err(error) => return self.failed(&segment, error.code(), error.retry_after()),
        };
        let api = self.session.api();
        let ticket = match api::request_upload(api, &token, &segment).await {
            Ok(ticket) => ticket,
            Err(error) if error.is_problem("segment-acknowledged") => {
                self.settle(&segment)?;
                return Ok(Outcome::Done);
            }
            Err(error) if error.is_problem("track-not-recorded") => {
                self.refuse_track(&segment)?;
                return Ok(Outcome::Done);
            }
            Err(error) if error.is_problem("segment-too-large") || error.status() == Some(413) => {
                self.reject(&segment, "segment-too-large")?;
                return Ok(Outcome::Done);
            }
            Err(error) => return self.failed(&segment, error.code(), error.retry_after()),
        };
        let url =
            match put::check_upload_url(&ticket.upload_url, self.config.allow_insecure_loopback) {
                Ok(url) => url,
                Err(error) => return self.failed(&segment, &error.code(), None),
            };
        let expired = ticket
            .expires_at
            .as_deref()
            .and_then(time::parse_ms)
            .is_some_and(|expires| expires <= api.server_now_ms());
        if expired {
            return self.failed(&segment, "upload-url-expired", None);
        }

        let segment = self.store.start_upload(segment.id, &ticket.segment_id)?;
        let plain = match self.store.read(segment.id) {
            Ok(plain) => plain,
            Err(
                error @ (StoreError::Corrupt(_)
                | StoreError::FileMissing(_)
                | StoreError::KeyMissing(_)),
            ) => {
                let reason = error.to_string();
                self.store.mark_lost(segment.id, &reason)?;
                self.emit(UploadEvent::Lost {
                    track: segment.track,
                    seq: segment.seq,
                    reason,
                });
                return Ok(Outcome::Done);
            }
            Err(error) => return Err(error.into()),
        };
        if let Err(error) = put::put(
            &self.http,
            url,
            &ticket.headers,
            plain,
            &self.bandwidth,
            self.config.chunk_bytes,
        )
        .await
        {
            return self.failed(&segment, &error.code(), None);
        }
        let segment = self.store.transition(segment.id, SegmentState::Uploaded)?;
        self.ack(&segment, &ticket.segment_id).await
    }

    async fn ack(&self, segment: &Segment, segment_id: &str) -> Result<Outcome, UploadError> {
        let token = match self.session.token().await {
            Ok(token) => token,
            Err(error) => return self.failed(segment, error.code(), error.retry_after()),
        };
        match api::acknowledge(self.session.api(), &token, segment_id, &segment.sha256).await {
            Ok(()) => {
                self.settle(segment)?;
                Ok(Outcome::Done)
            }
            Err(error) if error.is_problem("segment-acknowledged") => {
                self.settle(segment)?;
                Ok(Outcome::Done)
            }
            Err(error) if error.is_problem("hash-mismatch") || error.is_problem("blob-missing") => {
                // Upload again, with a new URL.
                let requeued = self.store.retry(segment.id, error.code())?;
                Ok(self.retrying(&requeued, error.code(), None))
            }
            Err(error) => self.failed(segment, error.code(), error.retry_after()),
        }
    }

    /// Counts a failed attempt and schedules the retry. An uploaded segment keeps its upload
    /// (only the ack is retried); anything else goes back to the queue.
    fn failed(
        &self,
        segment: &Segment,
        code: &str,
        retry_after: Option<u64>,
    ) -> Result<Outcome, UploadError> {
        let updated = if segment.state == SegmentState::Uploaded {
            self.store.record_failure(segment.id, code)?
        } else {
            self.store.retry(segment.id, code)?
        };
        Ok(self.retrying(&updated, code, retry_after))
    }

    fn retrying(&self, segment: &Segment, code: &str, retry_after: Option<u64>) -> Outcome {
        let delay = backoff::retry_delay(
            retry_after,
            segment.attempts.saturating_sub(1),
            self.config.backoff_base,
            self.config.backoff_cap,
            backoff::jitter(),
        );
        self.emit(UploadEvent::Retrying {
            track: segment.track,
            seq: segment.seq,
            code: code.to_owned(),
            delay,
        });
        Outcome::Retry(delay)
    }

    /// Acknowledged by the server: mark it, delete the local copy.
    fn settle(&self, segment: &Segment) -> Result<(), UploadError> {
        self.store.acknowledge(segment.id)?;
        self.store.purge(segment.id)?;
        self.emit(UploadEvent::Acknowledged {
            track: segment.track,
            seq: segment.seq,
        });
        Ok(())
    }

    fn reject(&self, segment: &Segment, code: &str) -> Result<(), UploadError> {
        self.store.reject(segment.id, code)?;
        self.emit(UploadEvent::Rejected {
            track: segment.track,
            seq: segment.seq,
            code: code.to_owned(),
        });
        Ok(())
    }

    /// `track-not-recorded`: reject everything pending on the track and tell the app to stop
    /// recording it. Later segments of the track are rejected without asking again.
    fn refuse_track(&self, segment: &Segment) -> Result<(), UploadError> {
        self.refused_tracks()
            .insert((segment.interview_id.clone(), segment.track));
        for pending in self.store.pending(&segment.interview_id)? {
            if pending.track == segment.track {
                self.reject(&pending, "track-not-recorded")?;
            }
        }
        self.emit(UploadEvent::TrackRefused {
            track: segment.track,
        });
        Ok(())
    }

    fn is_refused(&self, segment: &Segment) -> bool {
        self.refused_tracks()
            .contains(&(segment.interview_id.clone(), segment.track))
    }

    fn emit(&self, event: UploadEvent) {
        // No subscriber is fine.
        let _ = self.events.send(event);
    }

    fn backoffs(&self) -> MutexGuard<'_, HashMap<i64, Instant>> {
        self.not_before
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
    }

    fn refused_tracks(&self) -> MutexGuard<'_, HashSet<(String, Track)>> {
        self.refused.lock().unwrap_or_else(PoisonError::into_inner)
    }
}
