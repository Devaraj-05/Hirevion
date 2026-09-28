//! Debug-only support for unattended spike runs (SP-00d):
//! `HV_SPIKE=<page>:<seconds>[:<params>]` opens that spike page, which runs by itself and
//! reports its measurements to Rust. The module is compiled into debug builds only.

/// An unattended run requested through `HV_SPIKE`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SpikeRun {
    pub page: String,
    pub seconds: u32,
    /// Extra page parameters, for example `faces=cpu`.
    pub params: String,
}

impl SpikeRun {
    /// Parses `<page>:<seconds>[:<params>]`: a lower-case page name, 1 to 3,600 seconds, and
    /// optional `name=value` pairs joined by `&` (lower-case letters, digits, `=` and `&`).
    #[must_use]
    pub fn parse(value: &str) -> Option<Self> {
        let mut parts = value.splitn(3, ':');
        let page = parts.next()?;
        let seconds: u32 = parts.next()?.parse().ok()?;
        let params = parts.next();
        let lower = |text: &str| !text.is_empty() && text.bytes().all(|b| b.is_ascii_lowercase());
        let valid_params = params.is_none_or(|text| {
            !text.is_empty()
                && text
                    .bytes()
                    .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'=' || b == b'&')
        });
        (lower(page) && valid_params && (1..=3_600).contains(&seconds)).then(|| Self {
            page: page.to_owned(),
            seconds,
            params: params.unwrap_or_default().to_owned(),
        })
    }

    /// The location hash that opens the page in unattended mode.
    #[must_use]
    pub fn hash(&self) -> String {
        if self.params.is_empty() {
            format!("#/{}?auto={}", self.page, self.seconds)
        } else {
            format!("#/{}?auto={}&{}", self.page, self.seconds, self.params)
        }
    }
}

pub use commands::*;

mod commands {
    use super::SpikeRun;
    use crate::perf;
    use serde::Serialize;
    use std::fs;
    use std::path::PathBuf;
    use std::time::{Instant, SystemTime, UNIX_EPOCH};
    use tauri::ipc::{InvokeBody, Request};
    use tauri::{AppHandle, State};

    /// Where spike output goes: `ai-interviewer-desktop/spike-results/` (gitignored).
    fn results_dir() -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("spike-results")
    }

    pub struct SpikeState {
        run: Option<SpikeRun>,
        livekit_token: Option<String>,
        livekit_url: String,
        started: Instant,
        cpu_start: u64,
    }

    impl SpikeState {
        /// Reads `HV_SPIKE`, `HV_SPIKE_TOKEN` and `HV_SPIKE_LIVEKIT_URL`.
        pub fn from_env() -> Self {
            Self {
                run: std::env::var("HV_SPIKE")
                    .ok()
                    .and_then(|value| SpikeRun::parse(&value)),
                livekit_token: std::env::var("HV_SPIKE_TOKEN").ok(),
                livekit_url: std::env::var("HV_SPIKE_LIVEKIT_URL")
                    .unwrap_or_else(|_| String::from("wss://livekit.hirevion.localhost")),
                started: Instant::now(),
                cpu_start: perf::tree_cpu_ticks(),
            }
        }
    }

    #[derive(Serialize)]
    #[serde(rename_all = "camelCase")]
    pub struct SpikeConfig {
        run_hash: Option<String>,
        livekit_token: Option<String>,
        livekit_url: String,
    }

    #[tauri::command]
    pub fn spike_config(state: State<'_, SpikeState>) -> SpikeConfig {
        SpikeConfig {
            run_hash: state.run.as_ref().map(SpikeRun::hash),
            livekit_token: state.livekit_token.clone(),
            livekit_url: state.livekit_url.clone(),
        }
    }

    /// Saves a page's measurements with the CPU use of the app's whole process tree (app
    /// plus WebView2) since start-up, then exits if this was an unattended run.
    #[tauri::command]
    pub fn spike_report(
        app: AppHandle,
        state: State<'_, SpikeState>,
        page: String,
        results: serde_json::Value,
    ) -> Result<String, String> {
        if page.is_empty() || !page.bytes().all(|byte| byte.is_ascii_lowercase()) {
            return Err(format!("bad page name {page:?}"));
        }
        let wall = state.started.elapsed();
        let cpu_ticks = perf::tree_cpu_ticks().saturating_sub(state.cpu_start);
        let report = serde_json::json!({
            "page": page,
            "wallSeconds": wall.as_secs_f64(),
            "processTreeCpuPercent": perf::cpu_percent(cpu_ticks, wall),
            "results": results,
        });
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_or(0, |d| d.as_secs());
        let dir = results_dir();
        fs::create_dir_all(&dir).map_err(|error| error.to_string())?;
        let path = dir.join(format!("{page}-{stamp}.json"));
        let text = serde_json::to_string_pretty(&report).map_err(|error| error.to_string())?;
        fs::write(&path, text).map_err(|error| error.to_string())?;
        if state.run.is_some() {
            app.exit(0);
        }
        Ok(path.display().to_string())
    }

    #[derive(Serialize)]
    pub struct SavedSegment {
        bytes: usize,
        micros: u128,
    }

    /// Receives a finished media segment as raw IPC bytes (headers `x-hv-kind` and
    /// `x-hv-seq`) and writes it to `spike-results/media/`.
    #[tauri::command]
    pub fn spike_save_segment(request: Request<'_>) -> Result<SavedSegment, String> {
        let started = Instant::now();
        let InvokeBody::Raw(bytes) = request.body() else {
            return Err(String::from("expected the segment as raw bytes"));
        };
        let header = |name: &str| {
            request
                .headers()
                .get(name)
                .and_then(|value| value.to_str().ok())
                .map(str::to_owned)
                .ok_or_else(|| format!("missing header {name}"))
        };
        let kind = header("x-hv-kind")?;
        if kind.is_empty() || !kind.bytes().all(|byte| byte.is_ascii_lowercase()) {
            return Err(format!("bad segment kind {kind:?}"));
        }
        let seq: u32 = header("x-hv-seq")?
            .parse()
            .map_err(|_| String::from("bad x-hv-seq"))?;
        let dir = results_dir().join("media");
        fs::create_dir_all(&dir).map_err(|error| error.to_string())?;
        fs::write(dir.join(format!("{kind}-{seq:06}.mp4")), bytes)
            .map_err(|error| error.to_string())?;
        Ok(SavedSegment {
            bytes: bytes.len(),
            micros: started.elapsed().as_micros(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reads_page_and_duration() {
        assert_eq!(
            SpikeRun::parse("media:60"),
            Some(SpikeRun {
                page: String::from("media"),
                seconds: 60,
                params: String::new(),
            })
        );
        assert_eq!(
            SpikeRun::parse("livekit:5"),
            Some(SpikeRun {
                page: String::from("livekit"),
                seconds: 5,
                params: String::new(),
            })
        );
    }

    #[test]
    fn rejects_malformed_values() {
        for value in [
            "",
            "media",
            "media:",
            ":60",
            "media:0",
            "media:abc",
            "media:3601",
            "Media:60",
            "me dia:5",
            "media:45:",
            "media:45:faces=CPU",
            "media:45:faces=<x>",
        ] {
            assert_eq!(SpikeRun::parse(value), None, "{value:?}");
        }
    }

    #[test]
    fn builds_the_page_hash() {
        let run = SpikeRun {
            page: String::from("media"),
            seconds: 60,
            params: String::new(),
        };
        assert_eq!(run.hash(), "#/media?auto=60");
    }

    #[test]
    fn passes_extra_page_parameters_through() {
        let run = SpikeRun::parse("media:45:faces=cpu").expect("valid run");
        assert_eq!(run.params, "faces=cpu");
        assert_eq!(run.hash(), "#/media?auto=45&faces=cpu");
    }
}
