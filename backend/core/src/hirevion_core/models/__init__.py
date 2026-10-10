"""ORM models. Importing this package registers every table on `Base.metadata`."""

from hirevion_core.models.ai_invocation import AiInvocation
from hirevion_core.models.audit_log import AuditLog
from hirevion_core.models.auth_token import AuthToken
from hirevion_core.models.candidate import Application, Candidate, CandidateSkill
from hirevion_core.models.candidate_account import CandidateAccount, CandidateToken
from hirevion_core.models.candidate_device import (
    CandidateDevice,
    CandidateOtp,
    CandidateRefreshToken,
)
from hirevion_core.models.department import Department
from hirevion_core.models.desktop_release import DesktopChannel, DesktopRelease
from hirevion_core.models.document import Document
from hirevion_core.models.feature_flag import FeatureFlag
from hirevion_core.models.idempotency_key import IdempotencyKey
from hirevion_core.models.interview import (
    Interview,
    InterviewEvent,
    InterviewReviewer,
    Invitation,
)
from hirevion_core.models.interview_config import (
    InterviewTemplate,
    InterviewTemplateVersion,
    OrganizationSettings,
    Question,
    QuestionVersion,
)
from hirevion_core.models.interview_session import (
    Accommodation,
    Consent,
    InterviewAnswer,
    InterviewQuestion,
    InterviewSession,
    SystemCheckResult,
    Transcript,
    TranscriptSegment,
    WorkspaceSnapshot,
)
from hirevion_core.models.job import Job, JobSkill, JobVersion
from hirevion_core.models.organization import Organization
from hirevion_core.models.outbox_event import OutboxEvent
from hirevion_core.models.quota import Quota
from hirevion_core.models.recording import Recording, RecordingSegment
from hirevion_core.models.role import Role, RolePermission, UserRole
from hirevion_core.models.screening import ApplicationHistory, ScreeningConfig, ScreeningResult
from hirevion_core.models.skill import Skill, SkillAlias
from hirevion_core.models.team import Team, TeamMember
from hirevion_core.models.usage_event import UsageEvent
from hirevion_core.models.user import User
from hirevion_core.models.web_session import WebSession

__all__ = [
    "Accommodation",
    "AiInvocation",
    "Application",
    "ApplicationHistory",
    "AuditLog",
    "AuthToken",
    "Candidate",
    "CandidateAccount",
    "CandidateDevice",
    "CandidateOtp",
    "CandidateRefreshToken",
    "CandidateSkill",
    "CandidateToken",
    "Consent",
    "Department",
    "DesktopChannel",
    "DesktopRelease",
    "Document",
    "FeatureFlag",
    "IdempotencyKey",
    "Interview",
    "InterviewAnswer",
    "InterviewEvent",
    "InterviewQuestion",
    "InterviewReviewer",
    "InterviewSession",
    "InterviewTemplate",
    "InterviewTemplateVersion",
    "Invitation",
    "Job",
    "JobSkill",
    "JobVersion",
    "Organization",
    "OrganizationSettings",
    "OutboxEvent",
    "Question",
    "QuestionVersion",
    "Quota",
    "Recording",
    "RecordingSegment",
    "Role",
    "RolePermission",
    "ScreeningConfig",
    "ScreeningResult",
    "Skill",
    "SkillAlias",
    "SystemCheckResult",
    "Team",
    "TeamMember",
    "Transcript",
    "TranscriptSegment",
    "UsageEvent",
    "User",
    "UserRole",
    "WebSession",
    "WorkspaceSnapshot",
]
