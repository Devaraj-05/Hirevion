//! The proctor-session policy and the §61 application-rule matcher.

use std::collections::BTreeMap;

use hv_monitor::{ProcessInfo, Watch};
use serde::{Deserialize, Serialize};

/// The answer to `POST /proctoring/session`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SessionPolicy {
    pub proctor_session_id: String,
    pub policy_version: u32,
    #[serde(default)]
    pub level: String,
    /// What to watch (`focus`, `processes`, `displays`, plus the camera checks).
    #[serde(default)]
    pub checks: Vec<String>,
    /// Per event name.
    #[serde(default)]
    pub thresholds: BTreeMap<String, Threshold>,
    #[serde(default)]
    pub app_rules: AppRules,
    #[serde(default)]
    pub single_display: bool,
    #[serde(default = "default_heartbeat_seconds")]
    pub heartbeat_seconds: u64,
    #[serde(default = "default_batch_max_events")]
    pub batch_max_events: usize,
    #[serde(default)]
    pub accommodations: Vec<String>,
    /// The highest `seq` the server already holds (proposed contract addition): a client that
    /// lost its local queue continues after it instead of reusing numbers.
    #[serde(default)]
    pub acked_through: Option<u64>,
}

fn default_heartbeat_seconds() -> u64 {
    5
}

fn default_batch_max_events() -> usize {
    100
}

impl SessionPolicy {
    /// Which native watchers run. `focus`, `processes` and `displays` follow `checks` (all
    /// three when `checks` is empty); devices, capture-excluded windows, remote sessions, the
    /// hypervisor and integrity always run: they protect the interview itself.
    pub fn monitor_watch(&self) -> Watch {
        let has = |check: &str| self.checks.is_empty() || self.checks.iter().any(|c| c == check);
        Watch {
            processes: has("processes"),
            focus: has("focus"),
            displays: has("displays"),
            devices: true,
            windows: true,
            remote_session: true,
            virtual_machine: true,
            integrity: true,
        }
    }
}

/// Thresholds for one event, in milliseconds.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct Threshold {
    #[serde(default)]
    pub warn_after_ms: Option<u64>,
    #[serde(default)]
    pub critical_after_ms: Option<u64>,
}

/// `app_rules`: blocked and allowed applications.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct AppRules {
    #[serde(default)]
    pub blocked: Vec<AppRule>,
    #[serde(default)]
    pub allowed: Vec<AppRule>,
}

/// One rule: a primary condition, optional further conditions that must all hold too, and a
/// category (blocked rules).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AppRule {
    #[serde(rename = "match")]
    pub kind: MatchKind,
    pub value: String,
    #[serde(default)]
    pub category: Option<String>,
    /// Extra conditions (proposed contract addition): the only way a blocked name rule fires.
    #[serde(default)]
    pub with: Vec<Condition>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Condition {
    #[serde(rename = "match")]
    pub kind: MatchKind,
    pub value: String,
}

/// What a condition compares.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MatchKind {
    /// The executable file name, ignoring case; `.exe` may be left out.
    Name,
    /// The full path, ignoring case and slash direction; a value ending in `\` is a folder.
    Path,
    /// The signer's subject name, ignoring case; needs a valid signature.
    Publisher,
    /// The SHA-256 of the signer certificate (hex); needs a valid signature.
    Signature,
    /// The SHA-256 of the executable (hex).
    Hash,
    /// Part of a visible window title, ignoring case.
    WindowTitle,
    /// A kind this client doesn't know: never matches.
    #[serde(other)]
    Unknown,
}

impl MatchKind {
    /// How hard the attribute is to fake: an allow rule only overrides a block that is no
    /// stronger than itself.
    fn strength(self) -> u8 {
        match self {
            Self::Hash => 6,
            Self::Signature => 5,
            Self::Publisher => 4,
            Self::Path => 3,
            Self::WindowTitle => 2,
            Self::Name => 1,
            Self::Unknown => 0,
        }
    }

    /// The wire name.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Name => "name",
            Self::Path => "path",
            Self::Publisher => "publisher",
            Self::Signature => "signature",
            Self::Hash => "hash",
            Self::WindowTitle => "window_title",
            Self::Unknown => "unknown",
        }
    }
}

/// The severity the device suggests; the server decides (§64).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SeverityHint {
    Info,
    Warning,
    Critical,
}

/// A process matched a blocked rule that no allow rule overrides.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BlockMatch {
    /// Index into `app_rules.blocked`.
    pub rule_index: usize,
    /// The strongest attribute of the rule.
    pub matched_by: MatchKind,
    pub category: Option<String>,
    /// CRITICAL for a blocked category, WARNING otherwise (master plan §6.12).
    pub severity_hint: SeverityHint,
}

struct CompiledRule {
    index: usize,
    conditions: Vec<(MatchKind, String)>,
    category: Option<String>,
    strongest: MatchKind,
}

/// Matches processes against `app_rules`.
pub struct PolicyMatcher {
    blocked: Vec<CompiledRule>,
    allowed: Vec<CompiledRule>,
    ignored_name_only: usize,
}

impl std::fmt::Debug for PolicyMatcher {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("PolicyMatcher")
            .field("blocked", &self.blocked.len())
            .field("allowed", &self.allowed.len())
            .field("ignored_name_only", &self.ignored_name_only)
            .finish()
    }
}

impl PolicyMatcher {
    pub fn new(rules: &AppRules) -> Self {
        let compile = |(index, rule): (usize, &AppRule)| {
            let conditions: Vec<(MatchKind, String)> = std::iter::once((rule.kind, &rule.value))
                .chain(rule.with.iter().map(|c| (c.kind, &c.value)))
                .map(|(kind, value)| (kind, normalise(kind, value)))
                .collect();
            let strongest = conditions
                .iter()
                .map(|(kind, _)| *kind)
                .max_by_key(|kind| kind.strength())
                .unwrap_or(MatchKind::Unknown);
            CompiledRule {
                index,
                conditions,
                category: rule.category.clone(),
                strongest,
            }
        };
        let mut ignored_name_only = 0;
        let blocked = rules
            .blocked
            .iter()
            .enumerate()
            .map(compile)
            .filter(|rule| {
                // §61: never block on the name alone.
                let name_only = rule.conditions.iter().all(|(k, _)| *k == MatchKind::Name);
                ignored_name_only += usize::from(name_only);
                !name_only
            })
            .collect();
        let allowed = rules.allowed.iter().enumerate().map(compile).collect();
        Self {
            blocked,
            allowed,
            ignored_name_only,
        }
    }

    /// Blocked rules ignored because they match on the name alone.
    pub fn ignored_name_only_rules(&self) -> usize {
        self.ignored_name_only
    }

    /// The strongest blocked rule `process` matches, unless an allow rule at least as strong
    /// also matches. The interview app never matches.
    pub fn evaluate(&self, process: &ProcessInfo) -> Option<BlockMatch> {
        if process.interview_app {
            return None;
        }
        let block = self
            .blocked
            .iter()
            .filter(|rule| rule_matches(rule, process))
            .max_by_key(|rule| (rule.strongest.strength(), std::cmp::Reverse(rule.index)))?;
        let strength = block.strongest.strength();
        let allowed = self
            .allowed
            .iter()
            .any(|rule| rule.strongest.strength() >= strength && rule_matches(rule, process));
        if allowed {
            return None;
        }
        Some(BlockMatch {
            rule_index: block.index,
            matched_by: block.strongest,
            category: block.category.clone(),
            severity_hint: if block.category.is_some() {
                SeverityHint::Critical
            } else {
                SeverityHint::Warning
            },
        })
    }
}

fn rule_matches(rule: &CompiledRule, process: &ProcessInfo) -> bool {
    !rule.conditions.is_empty()
        && rule
            .conditions
            .iter()
            .all(|(kind, value)| condition_matches(*kind, value, process))
}

/// Lower-case, and for paths with backslashes; hex values without separators.
fn normalise(kind: MatchKind, value: &str) -> String {
    let lower = value.trim().to_lowercase();
    match kind {
        MatchKind::Path => lower.replace('/', "\\"),
        MatchKind::Hash | MatchKind::Signature => {
            lower.chars().filter(char::is_ascii_hexdigit).collect()
        }
        _ => lower,
    }
}

fn condition_matches(kind: MatchKind, value: &str, process: &ProcessInfo) -> bool {
    if value.is_empty() {
        return false;
    }
    let valid = process.signature.is_valid();
    match kind {
        MatchKind::Name => {
            let name = process.name.to_lowercase();
            name == value || name.strip_suffix(".exe") == Some(value)
        }
        MatchKind::Path => process.path.as_deref().is_some_and(|path| {
            let path = path.to_lowercase().replace('/', "\\");
            if value.ends_with('\\') {
                path.starts_with(value)
            } else {
                path == value
            }
        }),
        MatchKind::Publisher => {
            valid
                && process
                    .signature
                    .signer
                    .as_deref()
                    .is_some_and(|s| s.to_lowercase() == value)
        }
        MatchKind::Signature => {
            valid
                && process
                    .signature
                    .signer_cert_sha256
                    .as_deref()
                    .is_some_and(|s| s.eq_ignore_ascii_case(value))
        }
        MatchKind::Hash => process
            .sha256
            .as_deref()
            .is_some_and(|s| s.eq_ignore_ascii_case(value)),
        MatchKind::WindowTitle => process
            .window_titles
            .iter()
            .any(|title| title.to_lowercase().contains(value)),
        MatchKind::Unknown => false,
    }
}
