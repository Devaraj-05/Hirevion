//! A structural check that a buffer is a complete MP4 file.

/// True when `bytes` is a sequence of well-formed top-level MP4 boxes that starts with
/// `ftyp` and includes `moov` (so the file was finalized). Box contents are not parsed.
#[must_use]
pub fn looks_like_mp4(bytes: &[u8]) -> bool {
    let mut offset = 0usize;
    let mut kinds = Vec::new();
    while offset < bytes.len() {
        let Some(header) = bytes.get(offset..offset + 8) else {
            return false;
        };
        let size32 = u32::from_be_bytes([header[0], header[1], header[2], header[3]]);
        let kind = [header[4], header[5], header[6], header[7]];
        let size = match size32 {
            0 => bytes.len() - offset,
            1 => match bytes.get(offset + 8..offset + 16) {
                Some(large) => {
                    let mut raw = [0u8; 8];
                    raw.copy_from_slice(large);
                    match usize::try_from(u64::from_be_bytes(raw)) {
                        Ok(size) if size >= 16 => size,
                        _ => return false,
                    }
                }
                None => return false,
            },
            size if size >= 8 => size as usize,
            _ => return false,
        };
        let Some(end) = offset.checked_add(size) else {
            return false;
        };
        if end > bytes.len() {
            return false;
        }
        kinds.push(kind);
        offset = end;
    }
    kinds.first() == Some(b"ftyp") && kinds.contains(b"moov")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn mp4_box(kind: &[u8; 4], payload: &[u8]) -> Vec<u8> {
        let size = u32::try_from(8 + payload.len()).expect("small box");
        let mut bytes = size.to_be_bytes().to_vec();
        bytes.extend_from_slice(kind);
        bytes.extend_from_slice(payload);
        bytes
    }

    fn minimal_mp4() -> Vec<u8> {
        let mut bytes = mp4_box(b"ftyp", b"isom\0\0\0\0");
        bytes.extend(mp4_box(b"mdat", &[1, 2, 3]));
        bytes.extend(mp4_box(b"moov", &[]));
        bytes
    }

    #[test]
    fn accepts_a_complete_file() {
        assert!(looks_like_mp4(&minimal_mp4()));
    }

    #[test]
    fn accepts_a_final_box_that_runs_to_the_end() {
        let mut bytes = minimal_mp4();
        let mut last = mp4_box(b"free", &[0; 4]);
        last[..4].copy_from_slice(&0u32.to_be_bytes());
        bytes.extend(last);
        assert!(looks_like_mp4(&bytes));
    }

    #[test]
    fn rejects_random_bytes() {
        assert!(!looks_like_mp4(b"definitely not an mp4 file"));
        assert!(!looks_like_mp4(&[]));
    }

    #[test]
    fn rejects_a_truncated_file() {
        let bytes = minimal_mp4();
        assert!(!looks_like_mp4(&bytes[..bytes.len() - 2]));
    }

    #[test]
    fn rejects_a_file_without_moov() {
        let mut bytes = mp4_box(b"ftyp", b"isom\0\0\0\0");
        bytes.extend(mp4_box(b"mdat", &[1, 2, 3]));
        assert!(!looks_like_mp4(&bytes));
    }
}
