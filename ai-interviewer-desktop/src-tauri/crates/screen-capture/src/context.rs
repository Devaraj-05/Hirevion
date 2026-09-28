//! Names the failing step in Windows errors ("create video processor: The parameter is
//! incorrect.") while keeping the original HRESULT.

use windows_core::{Error, Result};

pub trait Context<T> {
    /// Prefixes the error message with `step`; the HRESULT is unchanged.
    fn context(self, step: &str) -> Result<T>;
}

impl<T> Context<T> for Result<T> {
    fn context(self, step: &str) -> Result<T> {
        self.map_err(|error| Error::new(error.code(), format!("{step}: {}", error.message())))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use windows::Win32::Foundation::E_INVALIDARG;
    use windows_core::Error;

    #[test]
    fn prefixes_the_step_and_keeps_the_code() {
        let failed: windows_core::Result<()> = Err(Error::new(E_INVALIDARG, "bad size"));
        let error = failed.context("create video processor").unwrap_err();
        assert_eq!(error.code(), E_INVALIDARG);
        assert_eq!(error.message(), "create video processor: bad size");
    }

    #[test]
    fn leaves_success_alone() {
        let ok: windows_core::Result<u32> = Ok(7);
        assert_eq!(ok.context("anything").unwrap(), 7);
    }
}
