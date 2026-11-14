//! One picture of a display for evidence snapshots (SP-14): JPEG encoding by WIC, scaled to
//! fit. The real capture needs an interactive desktop and a GPU, so it is ignored by default;
//! run it on the development PC with
//!     cargo test -p hv-screen-capture --test still -- --ignored

#![cfg(windows)]

use std::time::Duration;

use hv_screen_capture::geometry::Size;
use hv_screen_capture::still::{Still, capture_primary, encode_jpeg};

const MAX: Size = Size {
    width: 1280,
    height: 720,
};

/// A BGRA gradient, so the encoder has something to compress.
fn gradient(width: u32, height: u32) -> Still {
    let mut bgra = Vec::with_capacity((width * height * 4) as usize);
    for y in 0..height {
        for x in 0..width {
            bgra.extend([(x % 256) as u8, (y % 256) as u8, ((x + y) % 256) as u8, 255]);
        }
    }
    Still {
        size: Size { width, height },
        stride: width * 4,
        bgra,
    }
}

/// The frame size in a JPEG's start-of-frame marker.
fn jpeg_size(bytes: &[u8]) -> Size {
    assert_eq!(&bytes[..2], &[0xFF, 0xD8], "starts with SOI");
    assert_eq!(&bytes[bytes.len() - 2..], &[0xFF, 0xD9], "ends with EOI");
    let mut at = 2;
    while at + 9 < bytes.len() {
        assert_eq!(bytes[at], 0xFF, "a marker at {at}");
        let marker = bytes[at + 1];
        let length = usize::from(u16::from_be_bytes([bytes[at + 2], bytes[at + 3]]));
        if (0xC0..=0xC2).contains(&marker) {
            return Size {
                height: u32::from(u16::from_be_bytes([bytes[at + 5], bytes[at + 6]])),
                width: u32::from(u16::from_be_bytes([bytes[at + 7], bytes[at + 8]])),
            };
        }
        at += 2 + length;
    }
    panic!("no start-of-frame marker");
}

#[test]
fn a_small_frame_is_encoded_at_its_own_size() {
    let jpeg = encode_jpeg(&gradient(640, 360), MAX).expect("a JPEG");
    assert_eq!(
        jpeg_size(&jpeg),
        Size {
            width: 640,
            height: 360
        }
    );
}

#[test]
fn a_large_frame_is_scaled_to_fit_keeping_its_shape() {
    let jpeg = encode_jpeg(&gradient(2560, 1440), MAX).expect("a JPEG");
    assert_eq!(jpeg_size(&jpeg), MAX);
    // A super-wide display keeps its proportions.
    let wide = encode_jpeg(&gradient(3840, 1080), MAX).expect("a JPEG");
    assert_eq!(
        jpeg_size(&wide),
        Size {
            width: 1280,
            height: 360
        }
    );
    assert!(
        wide.len() < 2 * 1024 * 1024,
        "well under the server's limit"
    );
}

#[test]
fn a_padded_stride_is_honoured() {
    // GPU read-backs pad rows; the padding must not shear the picture or fail.
    let mut still = gradient(100, 50);
    let padded_stride = 100 * 4 + 64;
    let mut bgra = Vec::new();
    for row in still.bgra.chunks(100 * 4) {
        bgra.extend_from_slice(row);
        bgra.extend(std::iter::repeat_n(0u8, 64));
    }
    still.stride = padded_stride;
    still.bgra = bgra;
    let jpeg = encode_jpeg(&still, MAX).expect("a JPEG");
    assert_eq!(
        jpeg_size(&jpeg),
        Size {
            width: 100,
            height: 50
        }
    );
}

#[test]
fn malformed_frames_are_refused() {
    let mut short = gradient(64, 64);
    short.bgra.truncate(100);
    assert!(encode_jpeg(&short, MAX).is_err());
    let mut narrow = gradient(64, 64);
    narrow.stride = 10;
    assert!(encode_jpeg(&narrow, MAX).is_err());
    let empty = Still {
        size: Size::default(),
        stride: 0,
        bgra: Vec::new(),
    };
    assert!(encode_jpeg(&empty, MAX).is_err());
}

#[test]
#[ignore = "needs an interactive desktop and a GPU"]
fn the_primary_display_is_captured_once() {
    let still = capture_primary(Duration::from_secs(2)).expect("a frame");
    assert!(still.size.width > 0 && still.size.height > 0);
    let jpeg = encode_jpeg(&still, MAX).expect("a JPEG");
    let size = jpeg_size(&jpeg);
    assert!(size.width <= MAX.width && size.height <= MAX.height);
}
