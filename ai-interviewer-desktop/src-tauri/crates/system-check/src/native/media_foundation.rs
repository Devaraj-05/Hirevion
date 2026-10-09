//! Whether Media Foundation is installed and has an H.264 video encoder for recording.

use super::com::Mta;
use super::describe;
use crate::classify::{MediaFoundationProbe, classify_media_foundation};
use crate::result::CheckResult;
use std::ffi::OsString;
use std::os::windows::ffi::OsStringExt;
use std::path::PathBuf;
use windows::Win32::Media::MediaFoundation::{
    IMFActivate, MF_VERSION, MFMediaType_Video, MFSTARTUP_LITE, MFShutdown, MFStartup,
    MFT_CATEGORY_VIDEO_ENCODER, MFT_ENUM_FLAG, MFT_ENUM_FLAG_ASYNCMFT, MFT_ENUM_FLAG_HARDWARE,
    MFT_ENUM_FLAG_LOCALMFT, MFT_ENUM_FLAG_SORTANDFILTER, MFT_ENUM_FLAG_SYNCMFT,
    MFT_REGISTER_TYPE_INFO, MFTEnumEx, MFVideoFormat_H264,
};
use windows::Win32::System::Com::CoTaskMemFree;
use windows::Win32::System::SystemInformation::GetSystemDirectoryW;

/// Runs on its own thread: it joins the COM multithreaded apartment for the probe.
pub(super) fn check() -> CheckResult {
    classify_media_foundation(&probe())
}

fn probe() -> MediaFoundationProbe {
    // Windows N editions without the Media Feature Pack have no mfplat.dll. Look before
    // calling into it, so an app that delay-loads Media Foundation can report it.
    if !system_library_present("mfplat.dll") {
        return MediaFoundationProbe::Missing;
    }
    let _com = match Mta::join() {
        Ok(com) => com,
        Err(error) => return MediaFoundationProbe::Failed(describe(&error)),
    };
    // SAFETY: COM is initialised on this thread; MFStartup is reference-counted and the
    // MFShutdown below balances it.
    if let Err(error) = unsafe { MFStartup(MF_VERSION, MFSTARTUP_LITE) } {
        return MediaFoundationProbe::Failed(describe(&error));
    }
    // Hardware enumeration can fail on a machine without GPU drivers; software can't be
    // missing on a working install, so only its failure counts.
    let hardware =
        count_h264_encoders(MFT_ENUM_FLAG_HARDWARE | MFT_ENUM_FLAG_SORTANDFILTER).unwrap_or(0);
    let software = count_h264_encoders(
        MFT_ENUM_FLAG_SYNCMFT
            | MFT_ENUM_FLAG_ASYNCMFT
            | MFT_ENUM_FLAG_LOCALMFT
            | MFT_ENUM_FLAG_SORTANDFILTER,
    );
    // SAFETY: balances the successful MFStartup above; nothing from MF is still alive.
    let _ = unsafe { MFShutdown() };
    match software {
        Ok(software) => MediaFoundationProbe::Encoders { hardware, software },
        Err(_) if hardware > 0 => MediaFoundationProbe::Encoders {
            hardware,
            software: 0,
        },
        Err(error) => MediaFoundationProbe::Failed(describe(&error)),
    }
}

/// The H.264 video encoders Media Foundation lists for `flags`.
fn count_h264_encoders(flags: MFT_ENUM_FLAG) -> windows::core::Result<usize> {
    let output = MFT_REGISTER_TYPE_INFO {
        guidMajorType: MFMediaType_Video,
        guidSubtype: MFVideoFormat_H264,
    };
    let mut activates: *mut Option<IMFActivate> = std::ptr::null_mut();
    let mut count = 0u32;
    // SAFETY: the output type and both out-pointers refer to live locals for the call.
    unsafe {
        MFTEnumEx(
            MFT_CATEGORY_VIDEO_ENCODER,
            flags,
            None,
            Some(&raw const output),
            &raw mut activates,
            &raw mut count,
        )
    }?;
    let found = usize::try_from(count).unwrap_or(0);
    if !activates.is_null() {
        // SAFETY: MFTEnumEx returned an array of `count` activation objects, which the
        // caller owns; nothing else refers to it.
        let entries = unsafe { std::slice::from_raw_parts_mut(activates, found) };
        for entry in entries {
            // Dropping the interface releases the reference the array held.
            drop(entry.take());
        }
        // SAFETY: MFTEnumEx allocated the array with CoTaskMemAlloc and its entries are
        // released above, so it is freed exactly once here.
        unsafe { CoTaskMemFree(Some(activates.cast_const().cast())) };
    }
    Ok(found)
}

/// Whether `name` exists in the Windows system folder. When the folder can't be read the
/// answer is yes, and Media Foundation itself decides.
fn system_library_present(name: &str) -> bool {
    let mut buffer = [0u16; 260];
    // SAFETY: the buffer is a live local and its length goes with it.
    let length = unsafe { GetSystemDirectoryW(Some(&mut buffer)) };
    let length = usize::try_from(length).unwrap_or(0);
    if length == 0 || length >= buffer.len() {
        return true;
    }
    PathBuf::from(OsString::from_wide(&buffer[..length]))
        .join(name)
        .is_file()
}
