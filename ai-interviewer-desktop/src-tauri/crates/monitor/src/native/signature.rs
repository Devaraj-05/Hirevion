//! Authenticode verification with `WinVerifyTrust`: the signature embedded in the file, or
//! else the system catalog that lists the file's hash (most of Windows itself is signed that
//! way). No revocation or network retrieval, so a check never waits on the network.

use std::ffi::c_void;
use std::os::windows::io::AsRawHandle;
use std::path::Path;

use windows::Win32::Foundation::{HANDLE, HWND, INVALID_HANDLE_VALUE};
use windows::Win32::Security::Cryptography::Catalog::{
    CATALOG_INFO, CryptCATAdminAcquireContext2, CryptCATAdminCalcHashFromFileHandle2,
    CryptCATAdminEnumCatalogFromHash, CryptCATAdminReleaseCatalogContext,
    CryptCATAdminReleaseContext, CryptCATCatalogInfoFromContext,
};
use windows::Win32::Security::Cryptography::{CERT_NAME_SIMPLE_DISPLAY_TYPE, CertGetNameStringW};
use windows::Win32::Security::WinTrust::{
    WINTRUST_ACTION_GENERIC_VERIFY_V2, WINTRUST_CATALOG_INFO, WINTRUST_DATA, WINTRUST_DATA_0,
    WINTRUST_FILE_INFO, WTD_CACHE_ONLY_URL_RETRIEVAL, WTD_CHOICE_CATALOG, WTD_CHOICE_FILE,
    WTD_REVOCATION_CHECK_NONE, WTD_REVOKE_NONE, WTD_STATEACTION_CLOSE, WTD_STATEACTION_VERIFY,
    WTD_UI_NONE, WTHelperGetProvCertFromChain, WTHelperGetProvSignerFromChain,
    WTHelperProvDataFromStateData, WinVerifyTrust,
};
use windows::core::{PCWSTR, w};

use super::{from_wide, to_wide};
use crate::file_cache::hex;
use crate::observation::{SignatureInfo, SignatureKind, SignatureStatus};

/// `WinVerifyTrust` results that mean "no embedded signature here" rather than "bad".
const TRUST_E_NOSIGNATURE: i32 = 0x800B_0100_u32 as i32;
const TRUST_E_SUBJECT_FORM_UNKNOWN: i32 = 0x800B_0003_u32 as i32;
const TRUST_E_PROVIDER_UNKNOWN: i32 = 0x800B_0001_u32 as i32;

/// The signature of the executable at `path`.
pub(crate) fn verify(path: &Path) -> SignatureInfo {
    let Ok(file) = std::fs::File::open(path) else {
        return SignatureInfo::default();
    };
    let handle = HANDLE(file.as_raw_handle());
    let wide_path = to_wide(path.as_os_str());

    let mut file_info = WINTRUST_FILE_INFO {
        cbStruct: struct_size::<WINTRUST_FILE_INFO>(),
        pcwszFilePath: PCWSTR(wide_path.as_ptr()),
        hFile: handle,
        pgKnownSubject: std::ptr::null_mut(),
    };
    let embedded = trust(WINTRUST_DATA {
        cbStruct: struct_size::<WINTRUST_DATA>(),
        dwUIChoice: WTD_UI_NONE,
        fdwRevocationChecks: WTD_REVOKE_NONE,
        dwUnionChoice: WTD_CHOICE_FILE,
        Anonymous: WINTRUST_DATA_0 {
            pFile: &raw mut file_info,
        },
        dwStateAction: WTD_STATEACTION_VERIFY,
        dwProvFlags: WTD_CACHE_ONLY_URL_RETRIEVAL | WTD_REVOCATION_CHECK_NONE,
        ..WINTRUST_DATA::default()
    });
    match embedded.status {
        0 => return embedded.info(SignatureKind::Embedded, SignatureStatus::Valid),
        TRUST_E_NOSIGNATURE | TRUST_E_SUBJECT_FORM_UNKNOWN | TRUST_E_PROVIDER_UNKNOWN => {}
        _ => return embedded.info(SignatureKind::Embedded, SignatureStatus::Invalid),
    }

    // SHA-256 catalogs first, then the SHA-1 ones older catalogs use.
    for algorithm in [w!("SHA256"), PCWSTR::null()] {
        if let Some(info) = verify_in_catalog(handle, &wide_path, algorithm) {
            return info;
        }
    }
    drop(file);
    SignatureInfo {
        status: SignatureStatus::Unsigned,
        ..SignatureInfo::default()
    }
}

/// The catalog signature of the open file, when a catalog lists its hash.
fn verify_in_catalog(file: HANDLE, wide_path: &[u16], algorithm: PCWSTR) -> Option<SignatureInfo> {
    let mut admin: isize = 0;
    // SAFETY: `admin` is a live out-parameter; a null algorithm selects SHA-1.
    unsafe { CryptCATAdminAcquireContext2(&raw mut admin, None, algorithm, None, None) }.ok()?;
    let admin = CatAdmin(admin);

    let mut size = 0u32;
    // SAFETY: the first call only reports the hash size into `size`.
    unsafe { CryptCATAdminCalcHashFromFileHandle2(admin.0, file, &raw mut size, None, None) }
        .ok()?;
    let mut hash = vec![0u8; usize::try_from(size).ok()?];
    // SAFETY: `hash` holds `size` bytes and outlives the call.
    unsafe {
        CryptCATAdminCalcHashFromFileHandle2(
            admin.0,
            file,
            &raw mut size,
            Some(hash.as_mut_ptr()),
            None,
        )
    }
    .ok()?;
    hash.truncate(usize::try_from(size).ok()?);

    // SAFETY: `admin` is an open catalog admin context and `hash` a computed file hash.
    let catalog = unsafe { CryptCATAdminEnumCatalogFromHash(admin.0, &hash, None, None) };
    if catalog == 0 {
        return None;
    }
    let catalog = CatInfo {
        admin: admin.0,
        info: catalog,
    };
    let mut info = CATALOG_INFO {
        cbStruct: struct_size::<CATALOG_INFO>(),
        ..CATALOG_INFO::default()
    };
    // SAFETY: `catalog.info` is a catalog context from the enumeration above; `info` is a
    // live CATALOG_INFO whose cbStruct is set.
    unsafe { CryptCATCatalogInfoFromContext(catalog.info, &raw mut info, 0) }.ok()?;

    let tag = to_wide(std::ffi::OsStr::new(&hex(&hash).to_uppercase()));
    let mut catalog_info = WINTRUST_CATALOG_INFO {
        cbStruct: struct_size::<WINTRUST_CATALOG_INFO>(),
        dwCatalogVersion: 0,
        pcwszCatalogFilePath: PCWSTR(info.wszCatalogFile.as_ptr()),
        pcwszMemberTag: PCWSTR(tag.as_ptr()),
        pcwszMemberFilePath: PCWSTR(wide_path.as_ptr()),
        hMemberFile: file,
        pbCalculatedFileHash: hash.as_mut_ptr(),
        cbCalculatedFileHash: size,
        pcCatalogContext: std::ptr::null_mut(),
        hCatAdmin: admin.0,
    };
    let checked = trust(WINTRUST_DATA {
        cbStruct: struct_size::<WINTRUST_DATA>(),
        dwUIChoice: WTD_UI_NONE,
        fdwRevocationChecks: WTD_REVOKE_NONE,
        dwUnionChoice: WTD_CHOICE_CATALOG,
        Anonymous: WINTRUST_DATA_0 {
            pCatalog: &raw mut catalog_info,
        },
        dwStateAction: WTD_STATEACTION_VERIFY,
        dwProvFlags: WTD_CACHE_ONLY_URL_RETRIEVAL | WTD_REVOCATION_CHECK_NONE,
        ..WINTRUST_DATA::default()
    });
    let status = if checked.status == 0 {
        SignatureStatus::Valid
    } else {
        SignatureStatus::Invalid
    };
    drop(catalog);
    drop(admin);
    Some(checked.info(SignatureKind::Catalog, status))
}

/// The outcome of one `WinVerifyTrust` call and the signer it found.
struct Trust {
    status: i32,
    signer: Option<String>,
    signer_cert_sha256: Option<String>,
}

impl Trust {
    fn info(self, kind: SignatureKind, status: SignatureStatus) -> SignatureInfo {
        SignatureInfo {
            status,
            kind: Some(kind),
            signer: self.signer,
            signer_cert_sha256: self.signer_cert_sha256,
        }
    }
}

/// Verifies, reads the signer while the state is open, then closes the state.
fn trust(mut data: WINTRUST_DATA) -> Trust {
    let mut action = WINTRUST_ACTION_GENERIC_VERIFY_V2;
    let no_ui = HWND(INVALID_HANDLE_VALUE.0);
    // SAFETY: `data` is a fully initialised WINTRUST_DATA whose union member points at a live
    // info struct (owned by the caller for the duration of this function).
    let status =
        unsafe { WinVerifyTrust(no_ui, &raw mut action, (&raw mut data).cast::<c_void>()) };
    let (signer, signer_cert_sha256) = signer_of(data.hWVTStateData);
    data.dwStateAction = WTD_STATEACTION_CLOSE;
    // SAFETY: closes the state the verify call above opened, with the same data.
    let _ = unsafe { WinVerifyTrust(no_ui, &raw mut action, (&raw mut data).cast::<c_void>()) };
    Trust {
        status,
        signer,
        signer_cert_sha256,
    }
}

/// The first signer's certificate subject and SHA-256, from open verification state.
fn signer_of(state: HANDLE) -> (Option<String>, Option<String>) {
    if state.is_invalid() || state.0.is_null() {
        return (None, None);
    }
    // SAFETY: `state` is the open state of a WinVerifyTrust call that hasn't been closed.
    let provider = unsafe { WTHelperProvDataFromStateData(state) };
    if provider.is_null() {
        return (None, None);
    }
    // SAFETY: `provider` came from the open state above; index 0 is the primary signer.
    let signer = unsafe { WTHelperGetProvSignerFromChain(provider, 0, false, 0) };
    if signer.is_null() {
        return (None, None);
    }
    // SAFETY: `signer` came from the same provider data; index 0 is the leaf certificate.
    let certificate = unsafe { WTHelperGetProvCertFromChain(signer, 0) };
    if certificate.is_null() {
        return (None, None);
    }
    // SAFETY: `certificate` points into provider data that lives until the state closes.
    let context = unsafe { (*certificate).pCert };
    if context.is_null() {
        return (None, None);
    }
    // SAFETY: `context` is a valid CERT_CONTEXT; this call only reports the needed length.
    let length =
        unsafe { CertGetNameStringW(context, CERT_NAME_SIMPLE_DISPLAY_TYPE, 0, None, None) };
    let mut name = vec![0u16; usize::try_from(length).unwrap_or(0).max(1)];
    // SAFETY: `name` holds `length` UTF-16 units and outlives the call.
    unsafe {
        CertGetNameStringW(
            context,
            CERT_NAME_SIMPLE_DISPLAY_TYPE,
            0,
            None,
            Some(&mut name),
        )
    };
    let name = from_wide(&name);
    // SAFETY: a CERT_CONTEXT's encoded certificate is `cbCertEncoded` bytes at
    // `pbCertEncoded`, alive as long as the context.
    let encoded = unsafe {
        let context = &*context;
        std::slice::from_raw_parts(
            context.pbCertEncoded,
            usize::try_from(context.cbCertEncoded).unwrap_or(0),
        )
    };
    use sha2::Digest as _;
    let digest = hex(&sha2::Sha256::digest(encoded));
    ((!name.is_empty()).then_some(name), Some(digest))
}

/// A catalog admin context, released on drop.
struct CatAdmin(isize);

impl Drop for CatAdmin {
    fn drop(&mut self) {
        // SAFETY: the context was acquired by CryptCATAdminAcquireContext2 and is released
        // once, after every catalog context taken from it (`CatInfo` is dropped first).
        let _ = unsafe { CryptCATAdminReleaseContext(self.0, 0) };
    }
}

/// A catalog context, released on drop.
struct CatInfo {
    admin: isize,
    info: isize,
}

impl Drop for CatInfo {
    fn drop(&mut self) {
        // SAFETY: `info` came from CryptCATAdminEnumCatalogFromHash on `admin`, which is
        // still open, and is released once.
        let _ = unsafe { CryptCATAdminReleaseCatalogContext(self.admin, self.info, 0) };
    }
}

fn struct_size<T>() -> u32 {
    u32::try_from(size_of::<T>()).unwrap_or(u32::MAX)
}
