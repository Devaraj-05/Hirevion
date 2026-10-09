//! COM apartment membership for the threads that use Media Foundation and capture.

use std::marker::PhantomData;
use std::sync::Once;
use windows::Win32::System::Com::{
    COINIT_MULTITHREADED, CoIncrementMTAUsage, CoInitializeEx, CoUninitialize,
};

/// The current thread's membership of the multithreaded apartment, left when dropped.
/// It can't move to another thread, so the uninitialise happens where the initialise did.
pub(super) struct Mta {
    _not_send: PhantomData<*const ()>,
}

impl Mta {
    /// Joins the multithreaded apartment. Fails if the thread is already single-threaded.
    pub(super) fn join() -> windows::core::Result<Self> {
        keep_the_apartment_alive();
        // SAFETY: no reserved pointer is passed and COINIT_MULTITHREADED is a valid mode.
        unsafe { CoInitializeEx(None, COINIT_MULTITHREADED) }.ok()?;
        Ok(Self {
            _not_send: PhantomData,
        })
    }
}

impl Drop for Mta {
    fn drop(&mut self) {
        // SAFETY: balances the successful CoInitializeEx in `join`, on the same thread
        // (`Mta` is not `Send`). Every COM object the thread made is dropped before this.
        unsafe { CoUninitialize() };
    }
}

/// Windows Graphics Capture finishes closing a session on its own threads after `Close`
/// returns. If the last thread then left the apartment, COM would tear it down and unload
/// code those threads still run (an access violation a moment later). One usage reference,
/// held for the life of the process, keeps the apartment up.
fn keep_the_apartment_alive() {
    static KEEP: Once = Once::new();
    KEEP.call_once(|| {
        // SAFETY: takes no input. The cookie is deliberately never passed to
        // CoDecrementMTAUsage, so the apartment lasts as long as the process.
        let _cookie = unsafe { CoIncrementMTAUsage() };
    });
}
