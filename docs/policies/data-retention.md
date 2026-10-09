# Data retention policy

> **Draft for legal review**, not yet in force. Last updated: 2026-10-09.

Each organisation sets how long it keeps candidates' data, in line with its legal obligations and its own policy (PRD §84). Hirevion deletes data when its period ends. These are the defaults when an organisation hasn't set its own:

| Data | Kept for | Notes |
|---|---|---|
| Screen recordings | 90 days after the interview | Including evidence clips cut from them |
| Camera recordings | 90 days after the interview | |
| Third-eye recordings | 90 days after the interview | |
| Audio and transcripts' source audio | 90 days after the interview | The text transcript stays with the report |
| Raw proctoring events | 90 days after the interview | Reviewed events stay with the report as a summary |
| Interview reports, transcripts and evaluations | 1 year after the interview | |
| Resumes, candidate profiles and screening results | 1 year after the last activity on the candidate | Or until the candidate asks for deletion |
| Candidate accounts and device registrations | Until the candidate's data is deleted | Sign-in records follow the audit log |
| Audit logs | At least 1 year | Tamper-evident and append-only; kept longer where the law requires |
| Email delivery records | 90 days | |
| AI usage records (no content beyond what's needed) | 1 year | For cost and governance (PRD §79) |

**How deletion works:**
- A daily job removes data whose period has ended, and the deletion is recorded in the audit log.
- Backups age out within 35 days after that.
- **Legal holds:** an organisation can hold specific data (for example, during a dispute). Held data isn't deleted until the hold is lifted, and each hold is logged.
- **Candidates' requests:** a candidate can ask for earlier deletion (see the [deletion process](deletion.md)).

**Changes:** shortening a period applies to existing data at the next daily run; lengthening one applies only to data not yet deleted.
