//! The app's long-lived state: who it is (version, OS, device), and the candidate session,
//! either against the API or, in debug builds with `HV_DESKTOP_STUB=1`, the stub.

use std::path::Path;
use std::sync::Arc;

use hv_api_client::{ApiClient, SessionManager, Url, user_agent};
use hv_security::{Signer, Vault};

use super::interview::SessionTokens;
use super::services::Services;
use super::stub::Stub;
use super::views::AppInfoView;

/// The API root compiled into release builds (`HV_API_URL` at build time).
const DEFAULT_API_URL: &str = match option_env!("HV_API_URL") {
    Some(url) => url,
    None => "https://api.hirevion.localhost/api/v1/",
};
pub const CHANNEL: &str = "stable";

pub enum Backend {
    Live(Arc<SessionManager>),
    Stub(Stub),
}

pub struct AppState {
    pub info: AppInfoView,
    pub device_name: String,
    pub backend: Backend,
    /// Interview-session tokens, kept until the server rejects one. Shared with the uploaders.
    pub session_tokens: Arc<SessionTokens>,
    /// Monitoring, proctoring events and recordings during an interview.
    pub services: Services,
    /// `WEBVIEW2_*` variables that were set at launch, and whether a debugger was attached;
    /// the monitor reports them as `CLIENT_INTEGRITY_WARNING` events.
    pub integrity_variables: Vec<String>,
    pub debugger_present: bool,
}

/// The API root: the build-time default, which debug builds may override at run time.
pub fn api_url() -> Result<Url, String> {
    let configured = if cfg!(debug_assertions) {
        std::env::var("HV_API_URL").unwrap_or_else(|_| DEFAULT_API_URL.to_owned())
    } else {
        DEFAULT_API_URL.to_owned()
    };
    // The client resolves relative paths against the root, so it must end with a slash.
    let root = if configured.ends_with('/') {
        configured
    } else {
        format!("{configured}/")
    };
    Url::parse(&root).map_err(|error| format!("HV_API_URL is not a URL: {error}"))
}

fn arch() -> &'static str {
    match std::env::consts::ARCH {
        "x86_64" => "x64",
        "aarch64" => "arm64",
        other => other,
    }
}

#[cfg(windows)]
fn device_key() -> Result<Arc<dyn Signer>, String> {
    hv_security::NcryptKey::open_or_create(hv_security::DEVICE_KEY_NAME, true)
        .map(|key| Arc::new(key) as Arc<dyn Signer>)
        .map_err(|error| format!("the device key couldn't be opened: {error}"))
}

#[cfg(not(windows))]
fn device_key() -> Result<Arc<dyn Signer>, String> {
    Ok(Arc::new(hv_security::SoftwareKey::generate()))
}

impl AppState {
    pub fn new(
        version: &str,
        data_dir: &Path,
        integrity_variables: Vec<String>,
        debugger_present: bool,
    ) -> Result<Self, String> {
        let os = hv_system_check::os_description();
        let info = AppInfoView {
            version: version.to_owned(),
            channel: CHANNEL.to_owned(),
            arch: arch().to_owned(),
            os: os.clone(),
            debug: cfg!(debug_assertions),
        };
        let device_name = std::env::var("COMPUTERNAME").unwrap_or_else(|_| "Windows PC".to_owned());
        let stub = cfg!(debug_assertions)
            && std::env::var("HV_DESKTOP_STUB").is_ok_and(|value| value == "1");
        let session_tokens = Arc::new(SessionTokens::default());
        let (backend, services) = if stub {
            (Backend::Stub(Stub::from_env()), Services::disabled())
        } else {
            // The User-Agent wants the build ("26200.9457"), the last word of the description.
            let build = os.rsplit(' ').next().unwrap_or("unknown");
            let api = ApiClient::new(
                api_url()?,
                device_key()?,
                user_agent(version, build, arch()),
            )
            .map_err(|error| error.to_string())?;
            let session = Arc::new(SessionManager::new(api, Vault::new(data_dir.join("vault"))));
            // The recording store opens at launch; a crash's leftovers are repaired here and
            // uploaded after sign-in.
            let services =
                Services::live(version, data_dir, session.clone(), session_tokens.clone());
            (Backend::Live(session), services)
        };
        Ok(Self {
            info,
            device_name,
            backend,
            session_tokens,
            services,
            integrity_variables,
            debugger_present,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_api_root_ends_with_a_slash() {
        assert!(api_url().expect("a URL").as_str().ends_with('/'));
    }
}
