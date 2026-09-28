//! Frame-size arithmetic.

/// A frame size in physical pixels.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct Size {
    pub width: u32,
    pub height: u32,
}

/// Scales `src` down to fit inside `max`, keeping its aspect ratio, and rounds both
/// dimensions down to even numbers (NV12 and H.264 need even sizes). Never upscales.
#[must_use]
pub fn fit_even(src: Size, max: Size) -> Size {
    if src.width == 0 || src.height == 0 {
        return Size {
            width: 0,
            height: 0,
        };
    }
    let (width, height) = if src.width <= max.width && src.height <= max.height {
        (src.width, src.height)
    } else {
        let (src_w, src_h) = (u64::from(src.width), u64::from(src.height));
        let (max_w, max_h) = (u64::from(max.width), u64::from(max.height));
        if src_w * max_h > src_h * max_w {
            (max.width, scale(src_h, max_w, src_w))
        } else {
            (scale(src_w, max_h, src_h), max.height)
        }
    };
    Size {
        width: width & !1,
        height: height & !1,
    }
}

/// `value * numerator / denominator`, rounded down; the result is never larger than
/// `numerator`, so it always fits in a `u32`.
fn scale(value: u64, numerator: u64, denominator: u64) -> u32 {
    u32::try_from(value * numerator / denominator).unwrap_or(u32::MAX)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn size(width: u32, height: u32) -> Size {
        Size { width, height }
    }

    const FULL_HD: Size = Size {
        width: 1920,
        height: 1080,
    };

    #[test]
    fn scales_down_to_fit_and_keeps_the_aspect_ratio() {
        assert_eq!(fit_even(size(3840, 2160), FULL_HD), size(1920, 1080));
        assert_eq!(fit_even(size(2560, 1600), FULL_HD), size(1728, 1080));
        assert_eq!(fit_even(size(1080, 1920), FULL_HD), size(606, 1080));
    }

    #[test]
    fn never_upscales() {
        assert_eq!(fit_even(size(1366, 768), FULL_HD), size(1366, 768));
    }

    #[test]
    fn rounds_down_to_even_dimensions() {
        assert_eq!(fit_even(size(1921, 1081), FULL_HD), size(1918, 1080));
        assert_eq!(fit_even(size(1365, 767), FULL_HD), size(1364, 766));
    }

    #[test]
    fn empty_sources_stay_empty() {
        assert_eq!(fit_even(size(0, 1080), FULL_HD), size(0, 0));
    }
}
