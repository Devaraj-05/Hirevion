//! Which WebView2 permission requests the app grants: the camera and microphone for the
//! app's own pages, nothing else, and nothing at all for any other origin. Granting them
//! here means candidates never see WebView2's permission prompt.

/// The permission a page asked for.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    Camera,
    Microphone,
    Geolocation,
    Notifications,
    ClipboardRead,
    Other,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Decision {
    Allow,
    Deny,
}

/// The app's own origin in release builds (Tauri's asset protocol on Windows).
pub const APP_ORIGIN: &str = "http://tauri.localhost";

/// The ASCII origin (`scheme://host[:port]`) of `uri`, or `None` for opaque or invalid URIs.
#[must_use]
pub fn origin(uri: &str) -> Option<String> {
    let url = url::Url::parse(uri).ok()?;
    let origin = url.origin();
    origin.is_tuple().then(|| origin.ascii_serialization())
}

/// Allows the camera and microphone for exactly the listed origins; denies everything else.
#[must_use]
pub fn decide(kind: Kind, uri: &str, allowed_origins: &[&str]) -> Decision {
    let media = matches!(kind, Kind::Camera | Kind::Microphone);
    match origin(uri) {
        Some(origin) if media && allowed_origins.contains(&origin.as_str()) => Decision::Allow,
        _ => Decision::Deny,
    }
}

/// The origins allowed to use the camera and microphone: the app itself, plus the Vite dev
/// server in debug builds only.
#[must_use]
pub fn allowed_origins(config: &tauri::Config) -> Vec<String> {
    let mut allowed = vec![String::from(APP_ORIGIN)];
    if cfg!(debug_assertions)
        && let Some(dev_url) = &config.build.dev_url
    {
        allowed.push(dev_url.origin().ascii_serialization());
    }
    allowed
}

/// Applies [`decide`] to every WebView2 permission request of `window`, and turns off the
/// status bar (and, in release builds, the default context menu).
#[cfg(windows)]
pub fn install<R: tauri::Runtime>(
    window: &tauri::WebviewWindow<R>,
    allowed: Vec<String>,
) -> tauri::Result<()> {
    use webview2_com::Microsoft::Web::WebView2::Win32::{
        COREWEBVIEW2_PERMISSION_KIND, COREWEBVIEW2_PERMISSION_KIND_CAMERA,
        COREWEBVIEW2_PERMISSION_KIND_CLIPBOARD_READ, COREWEBVIEW2_PERMISSION_KIND_GEOLOCATION,
        COREWEBVIEW2_PERMISSION_KIND_MICROPHONE, COREWEBVIEW2_PERMISSION_KIND_NOTIFICATIONS,
        COREWEBVIEW2_PERMISSION_STATE_ALLOW, COREWEBVIEW2_PERMISSION_STATE_DENY,
    };
    use webview2_com::{PermissionRequestedEventHandler, take_pwstr};
    use windows_core::PWSTR;

    fn kind_of(kind: COREWEBVIEW2_PERMISSION_KIND) -> Kind {
        match kind {
            COREWEBVIEW2_PERMISSION_KIND_CAMERA => Kind::Camera,
            COREWEBVIEW2_PERMISSION_KIND_MICROPHONE => Kind::Microphone,
            COREWEBVIEW2_PERMISSION_KIND_GEOLOCATION => Kind::Geolocation,
            COREWEBVIEW2_PERMISSION_KIND_NOTIFICATIONS => Kind::Notifications,
            COREWEBVIEW2_PERMISSION_KIND_CLIPBOARD_READ => Kind::ClipboardRead,
            _ => Kind::Other,
        }
    }

    window.with_webview(move |webview| {
        let handler = PermissionRequestedEventHandler::create(Box::new(move |_, args| {
            let Some(args) = args else {
                return Ok(());
            };
            let mut uri = PWSTR::null();
            let mut kind = COREWEBVIEW2_PERMISSION_KIND::default();
            // SAFETY: WebView2 fills both out-parameters; `take_pwstr` frees the string.
            let uri = unsafe {
                args.Uri(&raw mut uri)?;
                args.PermissionKind(&raw mut kind)?;
                take_pwstr(uri)
            };
            let allowed: Vec<&str> = allowed.iter().map(String::as_str).collect();
            let state = match decide(kind_of(kind), &uri, &allowed) {
                Decision::Allow => COREWEBVIEW2_PERMISSION_STATE_ALLOW,
                Decision::Deny => COREWEBVIEW2_PERMISSION_STATE_DENY,
            };
            // SAFETY: plain setter on the event arguments, on the WebView2 UI thread.
            unsafe { args.SetState(state) }
        }));
        // SAFETY: called on the WebView2 UI thread with the webview's own controller.
        unsafe {
            let Ok(core) = webview.controller().CoreWebView2() else {
                return;
            };
            let mut token = 0i64;
            let _ = core.add_PermissionRequested(&handler, &raw mut token);
            if let Ok(settings) = core.Settings() {
                let _ = settings.SetIsStatusBarEnabled(false);
                if !cfg!(debug_assertions) {
                    let _ = settings.SetAreDefaultContextMenusEnabled(false);
                }
            }
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    const RELEASE: &str = "http://tauri.localhost";
    const DEV: &str = "http://localhost:1420";

    #[test]
    fn allows_camera_and_microphone_for_the_app_origin() {
        let allowed = [RELEASE];
        assert_eq!(
            decide(Kind::Camera, "http://tauri.localhost/#/media", &allowed),
            Decision::Allow
        );
        assert_eq!(
            decide(Kind::Microphone, "http://tauri.localhost/", &allowed),
            Decision::Allow
        );
    }

    #[test]
    fn allows_the_dev_server_only_when_it_is_listed() {
        assert_eq!(
            decide(Kind::Camera, "http://localhost:1420/", &[RELEASE, DEV]),
            Decision::Allow
        );
        assert_eq!(
            decide(Kind::Camera, "http://localhost:1420/", &[RELEASE]),
            Decision::Deny
        );
    }

    #[test]
    fn denies_other_origins_including_lookalikes() {
        let allowed = [RELEASE];
        for uri in [
            "https://evil.example/",
            "http://tauri.localhost.evil.com/",
            "https://tauri.localhost/",
            "http://tauri.localhost:8080/",
            "not a url",
            "",
        ] {
            assert_eq!(decide(Kind::Camera, uri, &allowed), Decision::Deny, "{uri}");
        }
    }

    #[test]
    fn denies_every_other_permission_even_for_the_app() {
        for kind in [
            Kind::Geolocation,
            Kind::Notifications,
            Kind::ClipboardRead,
            Kind::Other,
        ] {
            assert_eq!(
                decide(kind, "http://tauri.localhost/", &[RELEASE]),
                Decision::Deny,
                "{kind:?}"
            );
        }
    }

    #[test]
    fn origins_are_scheme_host_and_port() {
        assert_eq!(
            origin("http://tauri.localhost/#/media?x=1").as_deref(),
            Some(RELEASE)
        );
        assert_eq!(
            origin("HTTP://Tauri.LocalHost:80/").as_deref(),
            Some(RELEASE)
        );
        assert_eq!(
            origin("http://localhost:1420/index.html").as_deref(),
            Some(DEV)
        );
        assert_eq!(origin("javascript:alert(1)"), None);
        assert_eq!(origin("not a url"), None);
    }
}
