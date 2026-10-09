//! RFC 3339 timestamps with milliseconds, in UTC (`2026-10-12T05:03:20.000Z`), as the
//! recordings contract sends `started_at` and `expires_at`.

/// Formats Unix milliseconds as `YYYY-MM-DDTHH:MM:SS.mmmZ`.
#[must_use]
pub fn format_ms(unix_ms: i64) -> String {
    let days = unix_ms.div_euclid(86_400_000);
    let in_day = unix_ms.rem_euclid(86_400_000);
    let (year, month, day) = civil_from_days(days);
    format!(
        "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}.{:03}Z",
        in_day / 3_600_000,
        in_day / 60_000 % 60,
        in_day / 1_000 % 60,
        in_day % 1_000
    )
}

/// Parses `YYYY-MM-DDTHH:MM:SS[.fraction](Z|±HH:MM)` into Unix milliseconds.
#[must_use]
pub fn parse_ms(text: &str) -> Option<i64> {
    let bytes = text.as_bytes();
    if bytes.len() < 20 || bytes[4] != b'-' || bytes[7] != b'-' || !matches!(bytes[10], b'T' | b't')
    {
        return None;
    }
    let number = |range: std::ops::Range<usize>| -> Option<i64> {
        let part = text.get(range)?;
        part.bytes()
            .all(|b| b.is_ascii_digit())
            .then(|| part.parse().ok())?
    };
    let (year, month, day) = (number(0..4)?, number(5..7)?, number(8..10)?);
    if bytes[13] != b':' || bytes[16] != b':' {
        return None;
    }
    let (hour, minute, second) = (number(11..13)?, number(14..16)?, number(17..19)?);
    if !(1..=12).contains(&month) || !(1..=31).contains(&day) || hour > 23 || minute > 59 {
        return None;
    }
    if second > 60 {
        return None;
    }
    let mut rest = &text[19..];
    let mut millis = 0;
    if let Some(fraction) = rest.strip_prefix('.') {
        let digits = fraction.bytes().take_while(u8::is_ascii_digit).count();
        if digits == 0 {
            return None;
        }
        let padded = format!("{:0<3}", &fraction[..digits.min(3)]);
        millis = padded.parse::<i64>().ok()?;
        rest = &fraction[digits..];
    }
    let offset_minutes = match rest {
        "Z" | "z" => 0,
        _ if rest.len() == 6 && rest.as_bytes()[3] == b':' => {
            let sign = match rest.as_bytes()[0] {
                b'+' => 1,
                b'-' => -1,
                _ => return None,
            };
            let hours: i64 = rest[1..3].parse().ok()?;
            let minutes: i64 = rest[4..6].parse().ok()?;
            sign * (hours * 60 + minutes)
        }
        _ => return None,
    };
    let days = days_from_civil(year, month, day);
    Some(
        days * 86_400_000 + hour * 3_600_000 + minute * 60_000 + second * 1_000 + millis
            - offset_minutes * 60_000,
    )
}

/// Days since 1970-01-01 → (year, month, day), proleptic Gregorian (Howard Hinnant).
fn civil_from_days(days: i64) -> (i64, i64, i64) {
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + i64::from(month <= 2);
    (year, month, day)
}

/// (year, month, day) → days since 1970-01-01.
fn days_from_civil(year: i64, month: i64, day: i64) -> i64 {
    let year = if month <= 2 { year - 1 } else { year };
    let era = year.div_euclid(400);
    let yoe = year.rem_euclid(400);
    let mp = if month > 2 { month - 3 } else { month + 9 };
    let doy = (153 * mp + 2) / 5 + day - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146_097 + doe - 719_468
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn formats_known_instants() {
        assert_eq!(format_ms(0), "1970-01-01T00:00:00.000Z");
        assert_eq!(format_ms(946_684_800_000), "2000-01-01T00:00:00.000Z");
        assert_eq!(format_ms(951_782_400_000), "2000-02-29T00:00:00.000Z");
        assert_eq!(format_ms(1_700_000_000_123), "2023-11-14T22:13:20.123Z");
        assert_eq!(format_ms(-1), "1969-12-31T23:59:59.999Z");
    }

    #[test]
    fn round_trips() {
        for ms in [0, 1, 951_782_400_000, 1_700_000_000_123, 4_102_444_800_000] {
            assert_eq!(parse_ms(&format_ms(ms)), Some(ms), "{ms}");
        }
    }

    #[test]
    fn parses_offsets_and_fractions() {
        assert_eq!(
            parse_ms("2023-11-15T03:43:20+05:30"),
            Some(1_700_000_000_000)
        );
        assert_eq!(parse_ms("2023-11-14T22:13:20.1Z"), Some(1_700_000_000_100));
        assert_eq!(
            parse_ms("2023-11-14T22:13:20.123456Z"),
            Some(1_700_000_000_123)
        );
    }

    #[test]
    fn rejects_garbage() {
        for text in [
            "",
            "tomorrow",
            "2023-11-14 22:13:20Z",
            "2023-13-14T22:13:20Z",
            "2023-11-14T22:13:20",
            "2023-11-14T22:13:20.Z",
            "2023-11-14T22:13:20+0530",
        ] {
            assert_eq!(parse_ms(text), None, "{text}");
        }
    }
}
