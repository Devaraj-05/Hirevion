//! Command-line options for the `capture_bench` example.

use hv_screen_capture::geometry::Size;
use std::path::PathBuf;

/// What to record and how.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BenchArgs {
    pub seconds: u64,
    pub fps: u32,
    pub segment_seconds: u32,
    pub max_size: Size,
    pub bitrate: u32,
    pub gop_seconds: u32,
    /// Constant-quality encoding (1-100); `None` (`--vbr`) uses a variable bit rate
    /// around `bitrate` instead.
    pub quality: Option<u32>,
    pub out: PathBuf,
    pub hardware: bool,
    pub border: bool,
    pub all_displays: bool,
}

impl Default for BenchArgs {
    fn default() -> Self {
        Self {
            seconds: 60,
            fps: 15,
            segment_seconds: 10,
            max_size: Size {
                width: 1920,
                height: 1080,
            },
            bitrate: 1_500_000,
            // One keyframe per segment and constant quality 50 (ADR-0006).
            gop_seconds: 10,
            quality: Some(50),
            out: PathBuf::from("capture-bench"),
            hardware: true,
            border: true,
            all_displays: true,
        }
    }
}

/// Parses `--name value` options and flags (the program name must already be removed).
pub fn parse(args: impl IntoIterator<Item = String>) -> Result<BenchArgs, String> {
    let mut parsed = BenchArgs::default();
    let mut args = args.into_iter();
    while let Some(option) = args.next() {
        match option.as_str() {
            "--software" => parsed.hardware = false,
            "--no-border" => parsed.border = false,
            "--primary-only" => parsed.all_displays = false,
            "--vbr" => parsed.quality = None,
            "--out" => parsed.out = PathBuf::from(value(&option, args.next())?),
            "--seconds" => parsed.seconds = positive(&option, args.next())?,
            "--fps" => parsed.fps = positive(&option, args.next())?,
            "--segment-seconds" => parsed.segment_seconds = positive(&option, args.next())?,
            "--max-width" => parsed.max_size.width = positive(&option, args.next())?,
            "--max-height" => parsed.max_size.height = positive(&option, args.next())?,
            "--bitrate" => parsed.bitrate = positive(&option, args.next())?,
            "--gop-seconds" => parsed.gop_seconds = positive(&option, args.next())?,
            "--quality" => parsed.quality = Some(quality(&option, args.next())?),
            _ => return Err(format!("unknown option {option}")),
        }
    }
    Ok(parsed)
}

fn value(option: &str, next: Option<String>) -> Result<String, String> {
    next.ok_or_else(|| format!("{option} needs a value"))
}

fn positive<T>(option: &str, next: Option<String>) -> Result<T, String>
where
    T: std::str::FromStr + PartialOrd + Default,
{
    let raw = value(option, next)?;
    match raw.parse::<T>() {
        Ok(number) if number > T::default() => Ok(number),
        _ => Err(format!(
            "{option} must be a positive whole number, not {raw:?}"
        )),
    }
}

fn quality(option: &str, next: Option<String>) -> Result<u32, String> {
    let level: u32 = positive(option, next)?;
    if level > 100 {
        return Err(format!("{option} must be between 1 and 100, not {level}"));
    }
    Ok(level)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse_all(args: &[&str]) -> Result<BenchArgs, String> {
        parse(args.iter().map(|arg| (*arg).to_owned()))
    }

    #[test]
    fn defaults_record_every_display_for_a_minute() {
        let args = parse_all(&[]).expect("defaults parse");
        assert_eq!(args, BenchArgs::default());
        assert_eq!(args.seconds, 60);
        assert_eq!(args.fps, 15);
        assert_eq!(args.segment_seconds, 10);
        assert_eq!(
            args.max_size,
            Size {
                width: 1920,
                height: 1080
            }
        );
        assert!(args.hardware && args.border && args.all_displays);
    }

    #[test]
    fn reads_every_option() {
        let args = parse_all(&[
            "--seconds",
            "5",
            "--fps",
            "30",
            "--segment-seconds",
            "2",
            "--max-width",
            "1280",
            "--max-height",
            "720",
            "--bitrate",
            "2000000",
            "--gop-seconds",
            "1",
            "--out",
            "D:\\bench",
            "--software",
            "--no-border",
            "--primary-only",
        ])
        .expect("valid options");
        assert_eq!(args.seconds, 5);
        assert_eq!(args.fps, 30);
        assert_eq!(args.segment_seconds, 2);
        assert_eq!(
            args.max_size,
            Size {
                width: 1280,
                height: 720
            }
        );
        assert_eq!(args.bitrate, 2_000_000);
        assert_eq!(args.gop_seconds, 1);
        assert_eq!(args.out, PathBuf::from("D:\\bench"));
        assert!(!args.hardware && !args.border && !args.all_displays);
    }

    #[test]
    fn rejects_missing_and_bad_values() {
        assert_eq!(parse_all(&["--fps"]).unwrap_err(), "--fps needs a value");
        assert!(parse_all(&["--fps", "fast"]).unwrap_err().contains("--fps"));
        assert!(parse_all(&["--fps", "0"]).unwrap_err().contains("--fps"));
    }

    #[test]
    fn rejects_unknown_options() {
        assert_eq!(parse_all(&["--wat"]).unwrap_err(), "unknown option --wat");
    }

    #[test]
    fn defaults_to_quality_50_with_one_keyframe_per_segment() {
        let args = parse_all(&[]).expect("defaults");
        assert_eq!(args.quality, Some(50));
        assert_eq!(args.gop_seconds, args.segment_seconds);
    }

    #[test]
    fn vbr_switches_to_a_variable_bit_rate() {
        assert_eq!(parse_all(&["--vbr"]).expect("vbr").quality, None);
        assert_eq!(parse_all(&["--vbr", "--quality", "60"]).expect("both").quality, Some(60));
    }

    #[test]
    fn reads_a_constant_quality_between_1_and_100() {
        let args = parse_all(&["--quality", "70"]).expect("valid quality");
        assert_eq!(args.quality, Some(70));
        assert!(
            parse_all(&["--quality", "101"])
                .unwrap_err()
                .contains("--quality")
        );
        assert!(
            parse_all(&["--quality", "0"])
                .unwrap_err()
                .contains("--quality")
        );
    }
}
