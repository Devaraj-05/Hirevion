# PRD — Enterprise AI Recruitment & Interview Intelligence Platform

**Version:** 1.0  
**Status:** Product Baseline  
**Applications:** Recruitment Platform (Web) + AI Interview Desktop (Windows)  
**Supporting Experience:** Mobile Third-Eye Camera

## 1. Executive Summary

An enterprise recruitment platform that manages the complete flow:

**Job Description + Resumes → AI Resume Parsing → Screening & Ranking → Recruiter Shortlist → AI Interview → Coding → Proctoring → Evaluation → Recruiter Review → Hiring Decision**

The product has two independent applications:

1. **Recruitment Platform — Web Application**
   - Super Admin, Organization Admin, Recruiter, Hiring Manager, Interviewer/Reviewer.
   - Jobs, JD upload, resume upload, AI screening/ranking, candidates, shortlisting, interview configuration, invitations, live monitoring, reports, analytics, administration and integrations.

2. **AI Interview Desktop — Windows `.exe`**
   - Candidate-only application.
   - Candidate logs in with email/password.
   - AI voice interview, adaptive questions, coding, camera/microphone, fullscreen, screen recording, native Windows monitoring, proctoring and recording.

3. **Third-Eye — Mobile Browser**
   - Candidate scans a QR code.
   - Mobile browser provides a second camera angle.
   - No mobile application installation.

## 2. Product Vision

Build an enterprise AI recruitment operating platform combining:

- Resume Intelligence
- Candidate Management
- AI Interviewing
- Technical/Coding Interview
- Proctoring
- Evidence-Based Evaluation
- Recruiter Analytics
- Enterprise Governance

AI assists recruiters with screening, interviewing and evaluation. Hiring decisions remain under authorized human control.

## 3. Primary Product Goals

- Create jobs and upload JDs.
- Upload one or many resumes.
- Parse and normalize resumes.
- Compare resumes with job requirements.
- Rank candidates with explainable evidence.
- Allow recruiters to shortlist candidates.
- Configure AI interviews.
- Send invitations.
- Candidate installs and authenticates in the desktop application.
- Conduct resume/JD/skill-based AI voice interviews.
- Ask adaptive follow-ups.
- Adjust question difficulty.
- Support coding when configured.
- Capture transcript, camera, microphone and screen.
- Support native Windows proctoring.
- Support mobile third-eye camera.
- Provide real-time alerts.
- Generate interview, coding and proctoring reports.
- Provide Candidate 360.
- Maintain enterprise security, tenant isolation, RBAC, auditability and AI governance.

## 4. Scope Boundaries

The first product focuses on:

**Recruitment → Screening → Interview → Evaluation → Hiring Decision**

Not included as core scope:

- Payroll
- Attendance
- Post-hire HRMS
- Benefits
- General HR case management
- Autonomous hiring decisions
- Unexplained single "cheating scores"
- Native mobile third-eye application
- Unnecessary global keystroke recording

## 5. Product Architecture

```text
Enterprise AI Recruitment Platform
│
├── Recruitment Platform Web
│   ├── Admin
│   ├── Recruiter
│   ├── Hiring Manager
│   ├── Interviewer
│   ├── Jobs
│   ├── Resume Screening
│   ├── Candidates
│   ├── Interviews
│   ├── Reports
│   └── Analytics
│
├── AI Interview Desktop
│   ├── Candidate Authentication
│   ├── System Check
│   ├── AI Voice Interview
│   ├── Adaptive Questions
│   ├── Coding
│   ├── Camera/Mic
│   ├── Screen Capture
│   ├── Native Windows Monitoring
│   └── Recording
│
├── Third Eye
│   └── Mobile Browser Camera
│
└── Shared Backend
    ├── APIs
    ├── AI
    ├── Interview Orchestration
    ├── Screening
    ├── Proctoring
    ├── Evaluation
    ├── Storage
    ├── Realtime
    └── Reporting
```

# 6. User Roles

### Super Admin
Global platform administration, organizations, global AI/security settings, platform audit and monitoring.

### Organization Admin
Organization settings, users, roles, teams, interview templates, question library, AI configuration, proctoring policies, integrations and retention.

### Recruiter
Jobs, JD/resume upload, screening, ranking, shortlisting, interview configuration, invitations, monitoring and reports.

### Hiring Manager
Assigned jobs/candidates, interview results, reports, notes and hiring input.

### Interviewer/Reviewer
Assigned interviews, live monitoring where permitted, transcript, coding and evaluation review.

### Candidate
Only assigned interview and candidate desktop session.

# 7. Recruitment Platform — Information Architecture

```text
Dashboard

Jobs
├── All Jobs
├── Create Job
├── Draft
├── Open
├── Paused
├── Closed
└── Archived

Candidates
├── All
├── Screening
├── Shortlisted
├── Interview
├── Completed
└── Final Decision

Interviews
├── Upcoming
├── Live
├── Completed
└── Templates

Question Library
├── Technical
├── Coding
├── System Design
├── Resume-Based
└── Custom

Reports
├── Interview
├── Proctoring
├── Candidate
└── Analytics

Administration
├── Users
├── Roles
├── Teams
├── AI
├── Integrations
├── Security
└── Audit Logs
```

# 8. Authentication & Authorization

Recruitment Platform:

- Email/password
- Microsoft Entra ID
- OIDC
- SAML
- MFA
- Session management
- Password reset
- RBAC
- Rate limiting

Candidate Desktop:

- Email/password
- Short-lived access token
- Interview-specific session token
- Interview/device/session binding
- Session expiry

Never ship database, Azure, Redis or LLM master credentials inside the desktop app.

# 9. Organization Management

Organization Admin manages:

- Organization profile
- Departments
- Teams
- Users
- Roles
- Permissions
- Branding
- Default screening configuration
- Default interview configuration
- Proctoring policies
- AI configuration
- Retention policies
- Integrations

# 10. Recruitment Dashboard

Show:

```text
Open Jobs
Active Candidates
Candidates Screened
Candidates Shortlisted
Interviews Scheduled
Interviews Live
Completed Interviews
Pending Reviews
Proctoring Alerts
Hiring Pipeline
```

Filters:

- Date
- Recruiter
- Team
- Job
- Department
- Candidate status
- Interview status

# 11. Job Management

Job fields:

- Job ID
- Job Title
- Department
- Location
- Employment Type
- Experience Range
- Job Description
- Required Skills
- Preferred Skills
- Responsibilities
- Qualifications
- Salary Range if used
- Hiring Manager
- Recruiter
- Status
- Screening Configuration
- Interview Template

Statuses:

`Draft → Open → Paused → Closed → Archived`

# 12. Job Description Upload & Parsing

Supported:

- PDF
- DOCX
- TXT
- Direct text

Pipeline:

```text
JD Upload
 ↓
Validation
 ↓
Text Extraction
 ↓
Normalization
 ↓
Section Detection
 ↓
Skill Extraction
 ↓
Requirement Extraction
 ↓
Experience Extraction
 ↓
Embedding
 ↓
Screening Profile
```

Extract:

- Role/title
- Required skills
- Preferred skills
- Experience
- Responsibilities
- Qualifications
- Domain requirements
- Location/work model

Recruiter must be able to review and edit extracted requirements.

# 13. Resume Upload

Support:

- Single resume
- Bulk resumes
- PDF
- DOCX
- TXT
- Image-based resumes requiring OCR

Pipeline:

```text
Upload
 ↓
Validation
 ↓
Malware/File Scan
 ↓
Text Extraction
 ↓
OCR if required
 ↓
Resume Parser
 ↓
Candidate Profile
 ↓
Skill Extraction
 ↓
Embeddings
 ↓
Screening
```

# 14. Resume Parsing

Extract:

- Name
- Email
- Phone
- Location
- Summary
- Skills
- Experience
- Companies
- Job titles
- Employment dates
- Education
- Certifications
- Projects
- Achievements
- Languages
- Links

Store evidence references where possible, such as page/section/source text.

# 15. AI Resume Screening

Input:

```text
Job Description
+
Structured Job Profile
+
Candidate Resume
+
Screening Configuration
```

Evaluate:

- Required skill match
- Preferred skill match
- Experience match
- Relevant roles
- Relevant projects
- Technology match
- Domain experience
- Education where configured
- Location/work model where configured

Combine:

- Structured rules
- Semantic matching
- Skill matching
- Experience matching
- Embeddings
- LLM reasoning where useful

# 16. Resume Ranking

Output:

```text
Candidate
Rank
Match Score
Skill Match
Experience Match
Relevant Evidence
Missing Requirements
Strengths
Concerns
```

Example:

```text
Candidate A — Match 91
Candidate B — Match 86
Candidate C — Match 79
```

Ranking must be explainable. Every major factor should have evidence.

# 17. Screening Configuration

Recruiter can configure weights such as:

```text
Required Skills       35%
Experience            25%
Projects              15%
Preferred Skills      10%
Education              5%
Domain Experience     10%
```

Skills can be:

- Required
- Preferred
- Optional

# 18. Screening Workflow

```text
Uploaded
 ↓
Parsed
 ↓
Screened
 ↓
Ranked
 ↓
Recruiter Review
 ↓
Shortlisted
```

Recruiter actions:

- Shortlist
- Reject
- Hold
- Review
- Assign recruiter
- Assign hiring manager
- Create interview
- Export

Manual shortlist overrides should be audit logged.

# 19. Candidate Management

Candidate profile:

```text
Personal Information
Resume
Parsed Profile
Applications
Jobs
Screening Results
Shortlist Status
Interview History
Coding Results
Proctoring Results
Evaluation Results
Recruiter Notes
Timeline
```

# 20. Candidate 360

Core enterprise screen:

```text
Candidate 360
├── Profile
├── Resume
├── Applications
├── Screening
├── Interview History
├── Technical Skills
├── Coding
├── AI Interview
├── Proctoring
├── Recordings
├── Reports
├── Recruiter Notes
└── Activity Timeline
```

# 21. Interview Templates

Reusable templates define:

- Duration
- Skills
- Question count
- Difficulty distribution
- Question types
- Resume/JD usage
- Adaptive follow-ups
- Coding
- Coding languages
- Proctoring level
- Third eye
- Recording
- Evaluation rubric

Example:

```text
Senior Python Developer
Python/FastAPI     25%
PostgreSQL         15%
System Design      20%
Cloud/DevOps       15%
AI/LLM             15%
Communication      10%

Easy      20%
Medium    50%
Hard      30%

Coding: Enabled
Proctoring: Strict
Third Eye: Required
```

# 22. Question Library

Each question contains:

```text
Question
Skill
Topic
Difficulty
Question Type
Expected Concepts
Evaluation Rubric
Time Limit
Follow-up Rules
Version
```

Types:

- Technical
- Conceptual
- Scenario
- System Design
- Coding
- Resume-Based
- Project-Based
- Problem Solving

# 23. AI Question Generation

Generate question candidates from:

```text
JD
Resume
Required Skills
Experience Level
Interview Template
Question Library
```

Recruiter should be able to review/edit generated questions before they become reusable configuration.

# 24. Interview Assignment

Recruiter selects:

```text
Candidate
+
Job
+
Interview Template Version
```

System creates:

```text
Interview ID
Candidate
Job
Template Version
Start Window
Expiry
Duration
Status
Proctoring Policy
```

# 25. Interview Invitation

Candidate receives:

- Company
- Job
- Interview duration
- Interview window
- Desktop application instructions
- System requirements
- Privacy/recording notice
- Support information

# 26. Candidate Desktop — Startup

The candidate receives:

```text
AI-Interview.exe
```

Startup:

```text
Launch
 ↓
Version Check
 ↓
Login
 ↓
Load Interview
 ↓
System Check
 ↓
Consent
 ↓
Third-Eye Setup
 ↓
Environment Check
 ↓
Ready
```

# 27. Candidate Desktop Technology

Recommended:

```text
Tauri
React
TypeScript
Rust
Monaco Editor
```

Rust/native layer handles Windows capabilities.

# 28. Candidate Login

Candidate enters:

```text
Email
Password
```

Backend verifies:

- Candidate account
- Assigned interview
- Job
- Interview status
- Expiry
- Application version

Then issues short-lived session credentials.

# 29. System Check

Check:

```text
Camera
Microphone
Speaker
Screen Capture
Network
CPU
Memory
Disk
Display
Required permissions
Third Eye
```

Mandatory checks are controlled by the interview policy.

# 30. Candidate Instructions & Consent

Candidate sees configured instructions such as:

```text
Close unnecessary applications.
Keep camera and microphone enabled.
Keep your face visible.
Keep the interview application in focus.
Do not use prohibited applications.
Follow third-eye placement instructions.
```

Consent can cover:

- Camera
- Microphone
- Screen
- Audio
- Video
- Third eye
- Transcript
- Coding activity
- System/process telemetry
- Proctoring events

# 31. Full-Screen Mode

The desktop app enters fullscreen.

Native monitoring tracks:

- Focus
- Minimize/restore
- Fullscreen state
- Display changes
- Application exit

Fullscreen is one security control, not the only security mechanism.

# 32. AI Interview UI

```text
┌─────────────────────────────────────────────────────────────┐
│ AI INTERVIEW                              32:14             │
├──────────────────────────────┬──────────────────────────────┤
│              ◉               │        CODE EDITOR            │
│         AI VOICE ORB         │                              │
│          SPEAKING            │  def solution(...):          │
│                              │                              │
│ AI TRANSCRIPT                │  Python ▼  Run  Submit       │
│ "Explain your approach..."   │                              │
├──────────────────────────────┴──────────────────────────────┤
│ Camera ●  Mic ●  Screen ●  Third Eye ●  Secure Session ●  │
└─────────────────────────────────────────────────────────────┘
```

For non-coding questions, the coding panel becomes an appropriate interview workspace.

# 33. AI Voice

States:

```text
Idle
Listening
Thinking
Speaking
Paused
Error
```

Use streaming STT/TTS where supported to reduce latency.

# 34. AI Interview Orchestrator

Do not use one giant prompt.

State includes:

```text
Candidate
Job
Resume
Skills
Questions Asked
Topics Covered
Difficulty
Answer Quality
Remaining Time
Current Topic
Coding State
Proctor Events
```

Components:

```text
ContextBuilder
SkillMatrixBuilder
QuestionPlanner
AnswerAnalyzer
DifficultyController
FollowUpGenerator
CodingController
TimeController
CompletionEvaluator
```

# 35. Interview State Machine

```text
START
 ↓
INTRODUCTION
 ↓
EASY
 ↓
MEDIUM
 ↓
HARD
 ↓
ADAPTIVE FOLLOW-UP
 ↓
CODING (if configured)
 ↓
FINAL QUESTIONS
 ↓
COMPLETION
 ↓
EVALUATION
```

# 36. Resume-Based Interview

Use candidate-specific resume evidence.

Example:

```text
Resume: Built FastAPI microservices.

AI:
"You mentioned building FastAPI microservices.
How did you handle service-to-service communication?"
```

The question should reference the resume source when stored internally.

# 37. JD-Based Interview

Interview should cover required skills from the job.

Example:

```text
JD:
Python, FastAPI, PostgreSQL, Redis, Docker

Interview:
FastAPI → PostgreSQL → Redis → Docker → System Design
```

Skill coverage should be tracked.

# 38. Adaptive Follow-Ups

After each answer:

```text
Answer
 ↓
Correctness
Completeness
Depth
Missing Concepts
Contradictions
 ↓
Follow-Up Generator
```

Examples:

- Strong answer → deeper question.
- Partial answer → targeted follow-up.
- Weak answer → clarification.
- Repeated weak answers → move to another skill.

# 39. Difficulty Controller

Levels:

```text
Easy
Medium
Hard
```

The engine adjusts difficulty based on performance while preserving required skill coverage.

# 40. Interview Time Controller

Track:

```text
Start
Deadline
Remaining time
Question duration
Coding duration
```

As time decreases, the planner reduces remaining questions while preserving important skill coverage.

# 41. Speech-to-Text

Every transcript segment:

```text
Speaker
Text
Start
End
Question ID
Confidence
```

# 42. Text-to-Speech

AI responses are converted to voice with:

- Low perceived latency
- Streaming where supported
- Interrupt handling
- Audio state tracking
- Failure handling

# 43. Complete Transcript

Store both sides:

```text
AI:
Explain connection pooling.

Candidate:
...

AI:
What happens when the pool is exhausted?

Candidate:
...
```

# 44. Answer Evaluation

Dimensions:

```text
Relevance
Correctness
Completeness
Technical Depth
Reasoning
Clarity
Communication
Evidence
```

Store evidence rather than only a score.

# 45. Coding Interview

When enabled:

```text
AI asks coding question
 ↓
Monaco Editor
 ↓
Candidate writes code
 ↓
Run
 ↓
Tests
 ↓
Submit
 ↓
Evaluation
```

Initial languages:

```text
Python
JavaScript
TypeScript
SQL
```

# 46. Secure Coding Sandbox

Never execute candidate code directly on API servers.

```text
Desktop
 ↓
Coding API
 ↓
Queue
 ↓
Isolated Sandbox
 ↓
Tests
 ↓
Result
```

Sandbox limits:

- CPU
- Memory
- Time
- Filesystem
- Network
- Processes

Destroy the environment after execution.

# 47. Coding Evaluation

Evaluate:

```text
Correctness
Test Cases
Edge Cases
Time Complexity
Space Complexity
Code Quality
Readability
Approach
```

Store final code, submissions, test results, execution time and memory.

# 48. Coding Telemetry

Record meaningful events:

```text
Typing started/stopped
Code changed
Run
Submit
Copy
Paste
Cut
Editor focus change
```

Avoid unnecessary raw global keystroke storage.

# 49. Candidate Camera & Microphone

Camera supports:

- Interview video
- Face detection
- Multiple-face detection
- Face absence
- Proctoring evidence
- Recording

Microphone supports:

- AI conversation
- STT
- Recording
- Speech analytics
- Voice activity detection

# 50. Screen Recording

Capture the candidate desktop using native Windows capture mechanisms.

Use segmented recording:

```text
segment-0001
segment-0002
segment-0003
```

Upload continuously rather than waiting for interview completion.

# 51. Recording Recovery

```text
Capture
 ↓
Encrypted local buffer
 ↓
Upload Queue
 ↓
Retry
 ↓
Server ACK
```

Recover pending segments after a crash or network interruption.

# 52. Third-Eye

Flow:

```text
Desktop
 ↓
Temporary Token
 ↓
QR
 ↓
Mobile Browser
 ↓
Camera Permission
 ↓
LiveKit/WebRTC
 ↓
Interview Session
```

No native mobile app is required.

Token must be:

- Short-lived
- Single-use
- Interview-bound
- Candidate-bound
- Revocable

# 53. Third-Eye Purpose

The second camera can provide evidence about:

- Candidate posture
- Hands
- Phone
- Additional person
- Secondary screen
- Workspace
- Unusual movement

Signals are evidence, not automatic proof of misconduct.

# 54. Proctoring Sources

```text
Candidate Camera
Third Eye
Screen
Native Windows Agent
Coding Editor
Audio
Interview State
```

Pipeline:

```text
Sources
 ↓
Event Normalizer
 ↓
Temporal Aggregator
 ↓
Rule Engine
 ↓
Evidence Manager
 ↓
Severity
 ↓
Realtime Alert
 ↓
Report
```

# 55. Proctoring Events

```text
FACE_ABSENT
MULTIPLE_FACES
PHONE_DETECTED
GAZE_DEVIATION
CAMERA_DISCONNECTED
MIC_DISCONNECTED
SCREEN_CAPTURE_STOPPED
APPLICATION_FOCUS_CHANGE
WINDOW_MINIMIZED
BLOCKED_PROCESS_DETECTED
EXTERNAL_DISPLAY_CHANGE
THIRD_EYE_DISCONNECTED
UNEXPECTED_PERSON_DETECTED
CAMERA_OBSTRUCTED
```

# 56. Face Detection

Use:

```text
OpenCV
MediaPipe
ONNX Runtime
```

Detect:

- Face present
- Face absent
- Multiple faces
- Face too far
- Face too close

Apply temporal thresholds to reduce false alerts.

# 57. Eye Gaze

```text
Frame
 ↓
Face
 ↓
Landmarks
 ↓
Eyes
 ↓
Gaze Estimation
 ↓
Temporal Smoothing
 ↓
Event
```

Potential events:

```text
Extended left gaze
Extended right gaze
Extended downward gaze
```

Do not represent gaze as definitive proof of cheating or AI use.

# 58. Body/Hand Analysis

Use MediaPipe Pose/Hands for signals such as:

- Hands below frame
- Repeated downward movement
- Typing posture
- Unusual hand movement

Combine with editor telemetry.

# 59. Speech Analytics

Possible measurements:

- Speech rate
- Pauses
- Response latency
- Filler words
- Prosody
- Repetition

Do not claim these measurements prove a candidate is reading AI-generated text.

# 60. Native Windows Monitoring

Native layer can collect configured process metadata:

```text
Process name
PID
Executable path
Publisher/signature where available
Start time
Window information
```

Potential implementation:

```text
Rust + Windows APIs
```

C#/.NET can be used for isolated Windows-specific components where appropriate.

# 61. Prohibited Application Policy

Organization Admin can configure:

```text
Blocked applications
Blocked categories
Allowed applications
```

Where possible, detection can use:

```text
Name
Path
Publisher
Digital signature
Hash
Window title
```

Do not rely only on executable names.

# 62. Application Focus Monitoring

Detect:

```text
Interview app loses focus
Foreground application changes
Application minimized
Unexpected window
```

Store:

```text
Timestamp
Previous application
New application
Duration
```

# 63. Display & Device Monitoring

Monitor:

```text
Monitor connected/disconnected
Display configuration changes
Camera changes
Microphone changes
Third-eye changes
```

These should be treated as evidence/events, not automatic misconduct decisions.

# 64. Proctoring Severity

```text
INFO
WARNING
CRITICAL
```

Example:

```text
INFO: Third-eye reconnected
WARNING: Application focus changed for 4 seconds
CRITICAL: Screen capture unavailable for configured duration
```

Severity is configurable.

# 65. Real-Time Recruiter Monitoring

```text
Candidate Desktop
 ↓
Proctor Event
 ↓
Backend
 ↓
Redis Pub/Sub
 ↓
WebSocket
 ↓
Recruitment Platform
```

Recruiter can see:

```text
Candidate
Camera
Screen
Third Eye
AI status
Transcript
Recent events
Connection health
```

# 66. Live Interview Dashboard

```text
┌───────────────────────────────────────────────────────────┐
│ Candidate                         Interview 28:32         │
├───────────────────────┬───────────────────────────────────┤
│ Candidate Camera      │ Screen                            │
│                       │                                   │
├───────────────────────┼───────────────────────────────────┤
│ Third Eye             │ AI Transcript                     │
│                       │                                   │
├───────────────────────┴───────────────────────────────────┤
│ LIVE EVENTS                                               │
│ WARNING — Focus change detected                           │
└───────────────────────────────────────────────────────────┘
```

# 67. Evidence Management

Important events can reference:

```text
Screenshot
Video segment
Camera segment
Third-eye segment
Screen segment
Transcript segment
Process metadata
```

Example:

```json
{
  "event": "MULTIPLE_FACES",
  "timestamp": "...",
  "duration_ms": 4100,
  "confidence": 0.91,
  "evidence": ["..."]
}
```

# 68. Proctoring Report

Sections:

```text
Session Summary
Device Checks
Camera Status
Microphone Status
Screen Status
Third-Eye Status
Application Events
Process Events
Face Events
Gaze Events
Object Events
Timeline
Evidence
Reviewer Notes
```

Avoid an unexplained single "cheating score."

# 69. Interview Report

Sections:

```text
Executive Summary
Interview Metadata
Questions
Answers
Skill Evaluation
Technical Evaluation
Coding Evaluation
Communication
Strengths
Knowledge Gaps
Follow-Up Performance
Transcript
Timeline
```

# 70. Final Evaluation

Example:

```text
Python/FastAPI       8.2
PostgreSQL           7.8
System Design        7.1
AI/LLM               8.4
Coding               8.6
Communication        7.9
```

Each score must have supporting evidence.

# 71. Recruiter Review

Authorized users can:

- View transcript.
- Watch recordings.
- Jump to evidence timestamps.
- Review code.
- Review test results.
- Review screening result.
- Review interview evaluation.
- Review proctoring events.
- Add notes.
- Export reports.
- Change workflow status.

# 72. Hiring Workflow

Statuses:

```text
Under Review
Shortlisted
Interview Invited
Interview Started
Interview Completed
Additional Review
Selected
Rejected
On Hold
```

All changes are audit logged.

# 73. Analytics

Recruitment analytics:

- Applications per job
- Screening conversion
- Shortlist rate
- Interview completion
- Interview duration
- Average skill scores
- Coding performance
- Proctoring events
- Recruiter activity
- Time to shortlist
- Time to interview
- Candidate funnel

# 74. Candidate Funnel

```text
Applications
 ↓
Parsed
 ↓
Screened
 ↓
Shortlisted
 ↓
Interview Invited
 ↓
Interview Started
 ↓
Interview Completed
 ↓
Recruiter Review
 ↓
Selected / Rejected / Hold
```

# 75. Notifications

Channels:

- Email
- In-app
- Webhook

Events:

- Interview invitation
- Reminder
- Reschedule
- Interview completed
- Report ready
- Candidate shortlisted
- Candidate status changed
- Proctoring alert

# 76. ATS / Enterprise Integrations

Architecture should support adapters for:

- Workday
- SAP SuccessFactors
- Oracle
- Greenhouse
- iCIMS
- Lever
- Custom REST APIs
- Webhooks

Do not hard-code provider-specific logic into core recruitment services.

# 77. Webhooks

Events:

```text
candidate.created
candidate.shortlisted
interview.created
interview.started
interview.completed
evaluation.completed
report.ready
candidate.selected
candidate.rejected
```

Security:

- HMAC signatures
- Timestamp
- Replay protection
- Retries
- Delivery logs

# 78. AI Architecture

Provider abstraction:

```text
AIProvider
├── LLM
├── Embedding
├── STT
├── TTS
└── Vision
```

Services:

```text
LLMService
EmbeddingService
SpeechToTextService
TextToSpeechService
VisionService
```

# 79. AI Evaluation Governance

Store:

```text
Model Name
Model Version
Prompt Version
Rubric Version
Evaluation Version
Timestamp
Input References
Output
```

This makes evaluations auditable and reproducible.

# 80. Interview Versioning

Do not mutate a template used by active interviews.

Example:

```text
Senior Python Interview v1
Senior Python Interview v2
Senior Python Interview v3
```

Every interview references the exact version used.

# 81. Multi-Tenant Architecture

```text
Platform
├── Organization A
│   ├── Users
│   ├── Jobs
│   ├── Candidates
│   └── Interviews
├── Organization B
│   └── ...
└── Organization C
    └── ...
```

Every organization-owned entity must be tenant scoped.

Authorization must be checked server-side.

# 82. Enterprise Security

Requirements:

- TLS
- Encryption at rest
- RBAC
- Tenant isolation
- Short-lived tokens
- Signed storage URLs
- Secret management
- Audit logs
- Rate limiting
- Input validation
- File scanning
- Secure coding sandbox
- Session expiry
- Device/session binding
- Secure desktop updates

Production security should target enterprise control frameworks such as SOC 2 Type II, ISO 27001 and privacy/security requirements applicable to customer jurisdictions.

# 83. Privacy

Before interview, clearly disclose applicable collection:

```text
Camera
Microphone
Screen
Audio
Video
Third Eye
Transcript
Coding activity
System telemetry
Proctoring events
```

Provide:

- Privacy policy
- Recording policy
- Proctoring policy
- Data retention policy
- Data deletion process
- Support contact

# 84. Data Retention

Retention must be organization-configurable and aligned with applicable law/customer policy.

Example configuration:

```text
Screen recordings       90 days
Camera recordings       90 days
Third-eye recordings    90 days
Raw proctor events      90 days
Interview reports        1 year
Audit logs               1 year+
```

# 85. Storage Architecture

PostgreSQL:

- Metadata
- Candidates
- Jobs
- Interviews
- Scores
- Events
- Configuration
- Audit

Redis:

- Interview state
- Queues
- Realtime fan-out
- Rate limiting
- Temporary session state

Azure Blob:

- Resumes
- JD documents
- Screen recordings
- Camera recordings
- Audio
- Third-eye recordings
- Evidence
- Reports
- Transcript artifacts

Example:

```text
/{organization_id}/
    jobs/
    candidates/
    interviews/
        {interview_id}/
            screen/
            camera/
            audio/
            third-eye/
            evidence/
            transcript/
            report/
```

Use short-lived SAS URLs.

# 86. Backend Architecture

```text
                         API Gateway
                              │
             ┌────────────────┼────────────────┐
             ▼                ▼                ▼
      Recruitment API   Interview API    Proctor API
             │                │                │
             └────────────────┼────────────────┘
                              ▼
                    Interview Orchestrator
                              │
              ┌───────────────┼────────────────┐
              ▼               ▼                ▼
            Redis         PostgreSQL         Workers
                          + pgvector            │
                                                ├── AI
                                                ├── STT/TTS
                                                ├── Vision
                                                ├── Evaluation
                                                └── Reports
                              │
                              ▼
                        Azure Blob
```

# 87. Initial Deployment Strategy

Do not create dozens of microservices initially.

Start with:

```text
api-service
worker-service
realtime-service
coding-service
```

Logical modules:

```text
Auth
Organizations
Users
Jobs
Candidates
Resumes
Screening
Interviews
AI
Proctoring
Recordings
Evaluation
Reports
Notifications
Integrations
```

Split services later when scale, ownership or fault isolation requires it.

# 88. Azure Production Architecture

```text
Azure Front Door / WAF
        ↓
API Gateway / Kong
        ↓
Azure Container Apps
├── API
├── Realtime
├── Workers
└── Coding API

PostgreSQL Flexible Server
+ pgvector

Azure Cache for Redis

Azure Blob Storage

Azure Container Registry

Azure Key Vault

Microsoft Entra ID

Azure Monitor
Application Insights
```

# 89. Database Entities

Core tables:

```text
organizations
organization_settings

users
roles
permissions
user_roles
teams

jobs
job_versions
job_skills

candidates
candidate_documents
applications

resume_parses
resume_skills
resume_embeddings
screening_results

interview_templates
interview_template_versions
question_library
question_versions

interviews
interview_sessions
interview_questions
interview_answers
transcripts
transcript_segments

coding_sessions
coding_questions
coding_submissions
coding_test_results

proctor_sessions
proctor_events
proctor_evidence
proctor_metrics

third_eye_sessions

recordings
recording_segments

skill_evaluations
question_evaluations
interview_evaluations

reports
report_exports

notifications
webhooks
integrations
audit_logs
```

# 90. API Structure

```text
/auth
/organizations
/users
/jobs
/resumes
/candidates
/screening
/interviews
/interview-templates
/questions
/coding
/proctoring
/third-eye
/recordings
/evaluations
/reports
/analytics
/notifications
/integrations
/audit
```

Example screening APIs:

```text
POST /jobs
POST /jobs/{id}/jd
POST /jobs/{id}/resumes
POST /jobs/{id}/screen
GET  /jobs/{id}/screening-results
POST /candidates/{id}/shortlist
POST /candidates/{id}/reject
```

Example interview APIs:

```text
POST /interviews
GET  /interviews/{id}
POST /interviews/{id}/start
POST /interviews/{id}/answer
POST /interviews/{id}/complete
GET  /interviews/{id}/transcript
GET  /interviews/{id}/report
```

Example proctoring APIs:

```text
POST /proctoring/session
POST /proctoring/events
POST /proctoring/heartbeat
GET  /proctoring/{interview_id}
GET  /proctoring/{interview_id}/evidence
```

# 91. WebSockets

Channels:

```text
/ws/interviews/{interview_id}
/ws/proctoring/{interview_id}
/ws/recruiter/{interview_id}
```

Events:

```text
AI_SPEAKING
CANDIDATE_SPEAKING
QUESTION_STARTED
ANSWER_RECEIVED
PROCTOR_EVENT
CODE_RUN
CODE_SUBMITTED
RECORDING_STATUS
THIRD_EYE_STATUS
INTERVIEW_COMPLETED
```

# 92. Third-Eye Realtime Architecture

```text
Recruitment Platform
        │
        ▼
Interview Session
        │
        ▼
Candidate Desktop
        │
        ▼
Third-Eye Token
        │
        ▼
QR Code
        │
        ▼
Mobile Browser
        │
        ▼
Camera
        │
        ▼
LiveKit
        │
        ▼
Interview Session
```

# 93. Repository Structure

```text
enterprise-ai-recruitment/
│
├── recruitment-platform/
│   ├── app/
│   ├── components/
│   ├── features/
│   ├── services/
│   └── analytics/
│
├── ai-interviewer-desktop/
│   ├── src/
│   │   ├── auth/
│   │   ├── interview/
│   │   ├── coding/
│   │   ├── proctoring/
│   │   ├── third-eye/
│   │   ├── recording/
│   │   └── services/
│   └── src-tauri/
│       ├── process-monitor/
│       ├── window-monitor/
│       ├── screen-capture/
│       ├── device-monitor/
│       └── security/
│
├── backend/
├── workers/
├── coding-sandbox/
├── third-eye/
├── infrastructure/
└── docs/
```

# 94. Recommended Technology Stack

### Recruitment Platform

```text
Next.js
TypeScript
Tailwind CSS
shadcn/ui
React Query
Zustand
ECharts
```

### AI Interview Desktop

```text
Tauri
React
TypeScript
Rust
Monaco Editor
```

### Windows Native

```text
Rust
Windows APIs
```

### Backend

```text
Python
FastAPI
PostgreSQL
pgvector
Redis
Celery
WebSockets
```

### Realtime

```text
LiveKit
WebRTC
```

### Computer Vision

```text
OpenCV
MediaPipe
ONNX Runtime
```

### Azure

```text
Azure Container Apps
Azure PostgreSQL Flexible Server
Azure Cache for Redis
Azure Blob Storage
Azure Container Registry
Azure Key Vault
Azure Front Door/WAF
Azure Monitor
Application Insights
Microsoft Entra ID
```

# 95. Reliability

Desktop must handle:

- Network loss
- Server timeout
- Application crash
- Recording upload failure
- LiveKit reconnect
- Third-eye reconnect
- Device reconnect

Use:

```text
Local encrypted event queue
Recording segment queue
Session checkpoints
Heartbeat
Server acknowledgements
```

# 96. Observability

Monitor:

- API latency
- AI latency
- STT latency
- TTS latency
- WebRTC health
- Recording health
- Upload failures
- Interview completion
- Worker queues
- Database
- Redis
- Storage
- Desktop crash rate
- Proctoring engine health

# 97. Audit Logging

Audit:

```text
Login/logout
Job created/changed
JD uploaded/changed
Resume uploaded
Screening executed
Candidate shortlisted/rejected
Interview created
Interview configuration changed
Invitation sent
Report viewed
Recording viewed
Report downloaded
Score modified
Proctor event dismissed
Permissions changed
AI configuration changed
```

# 98. Candidate Timeline

Unify:

```text
Screening
Interview
Transcript
Coding
Proctoring
Recording
Evaluation
Recruiter actions
```

Example:

```text
10:00 Interview started
10:01 Introduction
10:03 Question 1
10:05 Answer
10:07 Follow-up
10:10 Coding
10:17 Code submitted
10:20 Proctor event
10:30 Final question
10:35 Completed
```

# 99. Candidate Report

Candidate-visible information should be configurable.

Possible:

- Interview completion
- General feedback
- Technical feedback
- Coding feedback
- Next-step status

Internal recruiter reports can contain confidential information.

# 100. Performance & Scalability

Initial architecture should support growth from:

```text
10 concurrent interviews
→ 100
→ 1,000
→ 10,000+
```

Scale independently:

- API
- Realtime
- AI workers
- Vision workers
- Coding workers
- Database
- Storage

Suggested engineering targets:

```text
Normal UI interaction: <100–200 ms
Proctoring event delivery: near real-time
AI response start: target <2–4 sec where provider/network allows
Recording: stable on supported hardware
Session recovery: automatic after transient failures
```

# 101. Accessibility

Recruitment Platform:

- Keyboard navigation
- Screen reader support
- Accessible forms
- Accessible charts

Desktop:

- High contrast
- Captions/transcript
- Clear permission instructions
- Configurable accommodations

Some proctoring policies may need adjustment for accessibility accommodations.

# 102. Localization

Architecture should externalize:

- UI strings
- Email templates
- Interview instructions
- Policy text

Initial language can be English, with additional languages later.

# 103. Development Roadmap

## Phase 1 — Recruitment Foundation

```text
Authentication
Organizations
Users/Roles
Jobs
JD upload
Resume upload
Resume parsing
Screening
Ranking
Shortlisting
Candidate management
```

## Phase 2 — Interview Configuration

```text
Templates
Question library
Skill matrix
Interview configuration
Assignments
Invitations
```

## Phase 3 — AI Interview Desktop

```text
Tauri
Login
System check
Camera
Microphone
AI voice
STT
TTS
Transcript
Adaptive questions
```

## Phase 4 — Evaluation

```text
Answer analysis
Difficulty controller
Follow-up generation
Skill evaluation
Interview report
```

## Phase 5 — Coding

```text
Monaco
Python
JavaScript
TypeScript
SQL
Sandbox
Tests
Submission
Evaluation
```

## Phase 6 — Core Proctoring

```text
Fullscreen
Screen recording
Camera recording
Face detection
Multiple faces
Face absence
Focus monitoring
Recording evidence
Live alerts
```

## Phase 7 — Third Eye

```text
QR
Mobile browser
LiveKit
Side camera
Recording
Connection monitoring
Evidence
```

## Phase 8 — Native Windows Proctoring

```text
Process monitoring
Window monitoring
Device monitoring
Display monitoring
Blocked processes
Agent heartbeat
```

## Phase 9 — Advanced Proctoring

```text
Gaze
Pose
Hands
Phone detection
Camera obstruction
Multiple-person detection
Speech analytics
Cross-camera correlation
```

## Phase 10 — Enterprise

```text
SSO
SAML
OIDC
SCIM
ATS integrations
Webhooks
Audit logs
Analytics
Tenant isolation
Retention
Security controls
```

## Phase 11 — Production Hardening

```text
Code signing
Secure updates
Crash recovery
Load testing
Security testing
Penetration testing
Disaster recovery
Monitoring
Support tooling
```

# 104. MVP Definition

### Recruitment Platform

```text
✓ Login
✓ Organization
✓ Recruiter
✓ Jobs
✓ JD upload
✓ Resume upload
✓ Resume parsing
✓ Resume screening
✓ Ranking
✓ Shortlisting
✓ Candidate 360
✓ Interview template
✓ Interview assignment
✓ Invitation
✓ Basic report
```

### Desktop

```text
✓ Windows installer
✓ Candidate login
✓ System check
✓ Camera
✓ Microphone
✓ Fullscreen
✓ AI voice
✓ STT
✓ TTS
✓ Resume/JD questions
✓ Adaptive follow-up
✓ Transcript
✓ Basic evaluation
✓ Screen recording
✓ Camera recording
```

### Third Eye

```text
✓ QR
✓ Mobile browser
✓ Camera
✓ LiveKit
✓ Connection monitoring
```

### Proctoring

```text
✓ Face
✓ Multiple faces
✓ Face absence
✓ Focus change
✓ Screen recording interruption
✓ Third-eye status
✓ Basic native process monitoring
✓ Event timeline
```

# 105. Production Definition of Done

```text
✓ Secure desktop installation/update
✓ Job creation
✓ JD upload
✓ Resume upload
✓ Resume parsing
✓ Screening/ranking
✓ Recruiter shortlisting
✓ Interview configuration
✓ Candidate invitation
✓ Candidate authentication
✓ System checks
✓ AI interview
✓ Adaptive questions
✓ Coding sandbox
✓ Camera/mic
✓ Screen recording
✓ Third eye
✓ Proctoring events
✓ Realtime alerts
✓ Recording recovery
✓ Reports
✓ Candidate 360
✓ Audit logs
✓ RBAC
✓ Tenant isolation
✓ Security testing
✓ Load testing
✓ Code signing
✓ Secure update
✓ Backup/DR
```

# 106. Product KPIs

Recruitment:

- Time from JD to shortlist
- Resume screening time
- Screening quality metrics
- Recruiter time saved
- Shortlist conversion

Interview:

- Interview completion
- Candidate drop-off
- AI response latency
- Interview duration
- Skill coverage

Proctoring:

- Detection latency
- False-positive rate
- Recording availability
- Third-eye reliability

Platform:

- API availability
- Desktop crash rate
- Upload success
- WebRTC reliability
- Worker success
- Report generation time

# 107. Final End-to-End Product Flow

```text
                         RECRUITER
                             │
                             ▼
                         CREATE JOB
                             │
                             ▼
                    UPLOAD JOB DESCRIPTION
                             │
                             ▼
                      UPLOAD RESUMES
                             │
                             ▼
                      RESUME PARSING
                             │
                             ▼
                    AI SCREENING/RANKING
                             │
                             ▼
                    RECRUITER REVIEW
                             │
                             ▼
                       SHORTLIST
                             │
                             ▼
                 CONFIGURE AI INTERVIEW
                             │
                             ▼
                   SEND INVITATION
                             │
                             ▼
              CANDIDATE DOWNLOADS .EXE
                             │
                             ▼
                         LOGIN
                             │
                             ▼
                      SYSTEM CHECK
                             │
                             ▼
                         CONSENT
                             │
                             ▼
                       THIRD EYE
                             │
                             ▼
                     AI VOICE INTERVIEW
                             │
                    ┌────────┴────────┐
                    ▼                 ▼
              ADAPTIVE Q&A         CODING
                    │                 │
                    └────────┬────────┘
                             ▼
                        PROCTORING
                             │
                    ┌────────┼────────┐
                    ▼        ▼        ▼
                 CAMERA    SCREEN   THIRD EYE
                    │        │        │
                    └────────┼────────┘
                             ▼
                         RECORDING
                             │
                             ▼
                       AI EVALUATION
                             │
                             ▼
                         REPORTS
                             │
                             ▼
                    RECRUITER CANDIDATE 360
                             │
                             ▼
                     HIRING DECISION
```

# 108. Final Architecture

```text
                           RECRUITMENT PLATFORM
                              WEB APPLICATION
                                   │
                    ┌──────────────┼──────────────┐
                    │              │              │
                  ADMIN         RECRUITER    HIRING MANAGER
                    │              │              │
                    └──────────────┼──────────────┘
                                   │
                              HTTPS/WSS
                                   │
                                   ▼
                            API / GATEWAY
                                   │
             ┌─────────────────────┼─────────────────────┐
             ▼                     ▼                     ▼
       Recruitment API       Interview API        Proctor API
             │                     │                     │
             └─────────────────────┼─────────────────────┘
                                   ▼
                         INTERVIEW ORCHESTRATOR
                                   │
              ┌────────────────────┼─────────────────────┐
              ▼                    ▼                     ▼
          PostgreSQL              Redis                 Workers
          + pgvector                                    │
                                                        ├─ AI
                                                        ├─ STT/TTS
                                                        ├─ Vision
                                                        ├─ Evaluation
                                                        └─ Reports
              │
              ▼
         Azure Blob
              │
      ┌───────┼────────┐
      │       │        │
    Screen  Camera   Third Eye


                    CANDIDATE WINDOWS DESKTOP
                           AI INTERVIEW
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
           React UI        Rust Native       Local CV
              │              Layer            Engine
              │                │                │
           AI Voice       Process Monitor   Face/Gaze/Pose
           Transcript     Window Monitor    Hands/Phone
           Coding         Device Monitor
           Camera         Screen Capture
           Microphone     Fullscreen
              │
              └───────────────┬────────────────┘
                              │
                           WebRTC
                              ▼
                          LIVEKIT
                              ▲
                              │
                       MOBILE THIRD EYE
                           BROWSER
```

# 109. Final Product Definition

The product should be positioned as an:

## Enterprise AI Recruitment & Interview Intelligence Platform

with this complete journey:

```text
JOB DESCRIPTION
       +
RESUMES
       ↓
AI RESUME SCREENING
       ↓
CANDIDATE RANKING
       ↓
RECRUITER SHORTLIST
       ↓
AI INTERVIEW CONFIGURATION
       ↓
CANDIDATE WINDOWS DESKTOP
       ↓
AI VOICE INTERVIEW
       ↓
ADAPTIVE FOLLOW-UP
       ↓
CODING
       ↓
NATIVE PROCTORING
       +
THIRD-EYE
       +
SCREEN/CAMERA/AUDIO RECORDING
       ↓
AI EVALUATION
       ↓
EVIDENCE-BASED REPORT
       ↓
RECRUITER CANDIDATE 360
       ↓
HIRING DECISION
```

The key architectural boundary is:

```text
RECRUITMENT PLATFORM
= Control, Configuration, Screening, Candidates, Analytics, Reports

AI INTERVIEW DESKTOP
= Candidate Interview, Coding, Capture, Native Proctoring

BACKEND
= Source of Truth, AI Orchestration, Realtime, Storage, Evaluation

THIRD EYE
= Temporary Mobile Camera Experience
```

This structure makes the existing resume-screening system the first stage of the same recruitment platform rather than a separate product.
