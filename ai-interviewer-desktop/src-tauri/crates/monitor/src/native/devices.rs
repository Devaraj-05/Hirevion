//! Cameras and microphones as Media Foundation lists them (§63).

use std::marker::PhantomData;

use windows::Win32::Media::MediaFoundation::{
    IMFActivate, IMFAttributes, MF_DEVSOURCE_ATTRIBUTE_FRIENDLY_NAME,
    MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE, MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_AUDCAP_ENDPOINT_ID,
    MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_AUDCAP_GUID, MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_GUID,
    MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_SYMBOLIC_LINK, MF_VERSION, MFCreateAttributes,
    MFEnumDeviceSources, MFSTARTUP_LITE, MFShutdown, MFStartup,
};
use windows::Win32::System::Com::{
    COINIT_MULTITHREADED, CoInitializeEx, CoTaskMemFree, CoUninitialize,
};
use windows::core::{GUID, PWSTR};

use crate::observation::{CaptureDevice, DeviceKind};

/// COM (multithreaded) and Media Foundation for the calling thread, shut down on drop. Not
/// `Send`: it must end on the thread that started it.
pub(crate) struct MediaSession {
    _not_send: PhantomData<*const ()>,
}

impl MediaSession {
    pub(crate) fn start() -> windows::core::Result<Self> {
        // SAFETY: no reserved pointer; COINIT_MULTITHREADED is a valid mode.
        unsafe { CoInitializeEx(None, COINIT_MULTITHREADED) }.ok()?;
        // SAFETY: COM is initialised on this thread; balanced by MFShutdown in Drop.
        if let Err(error) = unsafe { MFStartup(MF_VERSION, MFSTARTUP_LITE) } {
            // SAFETY: balances the CoInitializeEx above on the same thread.
            unsafe { CoUninitialize() };
            return Err(error);
        }
        Ok(Self {
            _not_send: PhantomData,
        })
    }

    /// Every camera and microphone. `None` when the list couldn't be read.
    pub(crate) fn enumerate(&self) -> Option<Vec<CaptureDevice>> {
        let mut devices = list(
            DeviceKind::Camera,
            MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_GUID,
            MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_SYMBOLIC_LINK,
        )?;
        devices.extend(list(
            DeviceKind::Microphone,
            MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_AUDCAP_GUID,
            MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_AUDCAP_ENDPOINT_ID,
        )?);
        Some(devices)
    }
}

impl Drop for MediaSession {
    fn drop(&mut self) {
        // SAFETY: balances the successful MFStartup and CoInitializeEx in `start`, on the
        // same thread (the type is not Send); no Media Foundation object outlives `list`.
        unsafe {
            let _ = MFShutdown();
            CoUninitialize();
        }
    }
}

fn list(kind: DeviceKind, source_type: GUID, id_key: GUID) -> Option<Vec<CaptureDevice>> {
    let mut attributes: Option<IMFAttributes> = None;
    // SAFETY: `attributes` is a live out-parameter.
    unsafe { MFCreateAttributes(&raw mut attributes, 1) }.ok()?;
    let attributes = attributes?;
    // SAFETY: both GUIDs are live constants for the duration of the call.
    unsafe { attributes.SetGUID(&MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE, &source_type) }.ok()?;

    let mut activates: *mut Option<IMFActivate> = std::ptr::null_mut();
    let mut count = 0u32;
    // SAFETY: both out-pointers refer to live locals; the array is freed below.
    unsafe { MFEnumDeviceSources(&attributes, &raw mut activates, &raw mut count) }.ok()?;
    let mut devices = Vec::new();
    if !activates.is_null() {
        let found = usize::try_from(count).unwrap_or(0);
        // SAFETY: MFEnumDeviceSources returned `count` initialised entries at `activates`.
        let entries = unsafe { std::slice::from_raw_parts_mut(activates, found) };
        for entry in entries.iter_mut() {
            if let Some(activate) = entry.take() {
                let name = string(&activate, &MF_DEVSOURCE_ATTRIBUTE_FRIENDLY_NAME);
                let id = string(&activate, &id_key);
                if let (Some(name), Some(id)) = (name, id) {
                    devices.push(CaptureDevice { kind, id, name });
                }
                // `activate` drops here, releasing its reference.
            }
        }
        // SAFETY: the array came from MFEnumDeviceSources and every entry was taken (and
        // released) above, so only the array itself is left to free.
        unsafe { CoTaskMemFree(Some(activates.cast_const().cast())) };
    }
    Some(devices)
}

fn string(activate: &IMFActivate, key: &GUID) -> Option<String> {
    let mut value = PWSTR::null();
    let mut length = 0u32;
    // SAFETY: both out-pointers refer to live locals; the string is freed below.
    unsafe { activate.GetAllocatedString(key, &raw mut value, &raw mut length) }.ok()?;
    if value.is_null() {
        return None;
    }
    // SAFETY: GetAllocatedString returned a NUL-terminated string at `value`.
    let text = unsafe { value.to_string() }.ok();
    // SAFETY: the string was allocated with CoTaskMemAlloc by GetAllocatedString.
    unsafe { CoTaskMemFree(Some(value.0.cast_const().cast())) };
    text
}
