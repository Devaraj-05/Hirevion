"""What the AI says when no model is needed: greetings, transitions, acknowledgements, generated
and resume questions, follow-up and clarification templates, guardrail answers, recaps and the
close. Deterministic, so the plan never waits on a model and every fallback reads naturally.

Also the speech helpers: a pronunciation lexicon applied before text-to-speech (§42; captions
keep the written form) and the key terms that prime speech-to-text.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from hirevion_core.engine.skills import snippet
from hirevion_core.engine.state import InterviewState, ResumeHook

ACKS = ("Thanks.", "Got it, thank you.", "Okay, thanks for that.", "Thank you.", "Understood.")

GENERATED: dict[str, tuple[str, ...]] = {
    "easy": (
        "In your own words, what is {skill}, and when would you choose it?",
        "What are the core ideas someone new to {skill} should understand first?",
        "What problem does {skill} solve well, and where does it fall short?",
    ),
    "medium": (
        "Walk me through how you have used {skill} on a real problem. "
        "What trade-offs did you weigh?",
        "How would you structure a small production service that relies on {skill}? "
        "What would you watch out for?",
        "Tell me about a bug or failure involving {skill} that you had to track down. "
        "How did you find the cause?",
    ),
    "hard": (
        "Describe a difficult problem you solved with {skill} at scale. "
        "What broke first, and how did you fix it?",
        "If a system built on {skill} had to handle ten times its current load, "
        "what would you change, and why?",
        "What are the subtle failure modes of {skill} that most people miss, "
        "and how do you guard against them?",
    ),
}

RESUME = {
    "projects": "Your resume mentions the project {label}: “{quote}”. "
    "What role did {skill} play in it, and what would you change if you built it again?",
    "positions": "Your resume says, from your time as {label}: “{quote}”. "
    "How did you use {skill} in that work?",
    "achievements": "You mentioned “{quote}”. How did {skill} help you get there, "
    "and what was the hardest part?",
    "skills": "Your resume lists {skill}: “{quote}”. "
    "Tell me about the most substantial thing you've built with it.",
}

PARTIAL = (
    "That covers part of it. Could you say more about {concepts}?",
    "Good start. How does {concepts} fit into your answer?",
)
PARTIAL_NO_CONCEPTS = "Could you go a little deeper on that, perhaps with a concrete example?"
WEAK = (
    "No problem. At a high level, how would you approach {topic}? A rough outline is fine.",
    "Let me put it another way: what would your first step be with {topic}?",
)
STRONG_DEEPER = "Let's go a level deeper on {topic}. What changes when the stakes are higher?"

LEXICON: dict[str, str] = {
    "PostgreSQL": "Postgres Q L",
    "MySQL": "My S Q L",
    "NoSQL": "No sequel",
    "GraphQL": "Graph Q L",
    "nginx": "engine X",
    "NGINX": "engine X",
    "kubectl": "kube control",
    "k8s": "Kubernetes",
    "FastAPI": "Fast A P I",
    "gRPC": "G R P C",
    "CI/CD": "C I C D",
    "OAuth": "Oh Auth",
    "JWT": "J W T",
    "JSON": "Jason",
    "YAML": "Yamel",
    "SaaS": "Sass",
    "Django": "Jango",
    "PyTorch": "Pie Torch",
    "NumPy": "Num Pie",
    "C#": "C sharp",
    "F#": "F sharp",
    ".NET": "dot net",
    "Node.js": "Node J S",
    "Next.js": "Next J S",
    "Vue.js": "View J S",
    "Vue": "View",
    "SQL": "S Q L",
    "AWS": "A W S",
    "GCP": "G C P",
    "SRE": "S R E",
    "regex": "rej ex",
}
_LEXICON = sorted(LEXICON, key=len, reverse=True)
_LEXICON_PATTERN = re.compile(
    "|".join(rf"(?<![\w.#+]){re.escape(term)}(?![\w#+])" for term in _LEXICON)
)


def pronounce(text: str) -> str:
    """`text` with technical terms spelled the way text-to-speech should say them."""
    return _LEXICON_PATTERN.sub(lambda match: LEXICON[match.group(0)], text)


def keyterms(state: InterviewState, limit: int = 50) -> list[str]:
    """Terms that prime speech-to-text: the skills, the job title and the resume's hooks."""
    terms: list[str] = []
    for value in [s.name for s in state.skills] + [state.job.title, state.job.company]:
        if value and value not in terms:
            terms.append(value)
    for hook in state.resume:
        if hook.label and hook.label not in terms:
            terms.append(hook.label)
    return terms[:limit]


def _pick(options: Sequence[str], seed: int) -> str:
    return options[seed % len(options)]


def ack(seed: int) -> str:
    return _pick(ACKS, seed)


def _join(items: Sequence[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def greeting(state: InterviewState, minutes: int) -> str:
    skills = _join([s.name for s in state.skills][:5])
    covers = f" We'll cover {skills}." if skills else ""
    return (
        f"Hello {state.candidate.first_name}, I'm the AI interviewer for the "
        f"{state.job.title} role at {state.job.company}. This interview takes about "
        f"{minutes} minutes.{covers} You can ask me to repeat a question, or say you need a "
        "moment, at any time."
    )


INTRODUCTION = "To start, could you briefly introduce yourself and the work you've done recently?"


def transition(skill: str, first: bool) -> str:
    return f"Let's begin with {skill}." if first else f"Now let's move on to {skill}."


def generated_question(skill: str, difficulty: str, index: int) -> str:
    options = GENERATED.get(difficulty) or GENERATED["medium"]
    return options[index % len(options)].format(skill=skill)


def resume_question(hook: ResumeHook) -> str:
    template = RESUME.get(hook.field, RESUME["achievements"])
    return template.format(
        label=hook.label or "on your resume", quote=snippet(hook.quote, 120), skill=hook.skill
    )


def partial_follow_up(missing: Sequence[str], seed: int) -> str:
    if not missing:
        return PARTIAL_NO_CONCEPTS
    return _pick(PARTIAL, seed).format(concepts=_join(list(missing)[:2]))


def clarification(topic: str, seed: int) -> str:
    return _pick(WEAK, seed).format(topic=topic)


def deeper(topic: str) -> str:
    return STRONG_DEEPER.format(topic=topic)


def repeat(question: str) -> str:
    return f"Of course. {question}"


MOMENT = "Of course, take your time. Just start answering when you're ready."
DONT_KNOW = "That's alright, let's move on."
NO_ANSWER = "I didn't catch an answer there. Let's move on."
SILENCE_NUDGE = "Take your time. Would you like me to repeat the question?"
TIMED_OUT = "We're out of time for that one, so let's move on."
OFF_TOPIC = "Let's keep to the question, please."
MANIPULATION = (
    "I can't share scores, answers or how you're doing during the interview, and I'll keep to "
    "the questions. Let's continue."
)
SKIP_SKILL = "Let's leave that topic there."
CODING_INTRO = (
    "Next is a coding exercise. The editor is open on your screen; talk me through your "
    "approach as you go, and say when you're done."
)
FINAL_QUESTIONS = (
    "That's all my questions. Do you have any questions about the role or the process?"
)
FAQ_MORE = "Do you have any other questions?"
FAQ_UNKNOWN = (
    "I don't have that information, but I'll pass your question on to the recruiting team so "
    "they can follow up."
)
RESUMED = "Welcome back. Let's pick up where we left off."
RECOVERED = "Sorry about that, we had a brief interruption on our side."


def recap(state: InterviewState) -> str:
    topic = f" We were talking about {state.current_topic}." if state.current_topic else ""
    return f"{RESUMED}{topic}"


def closing(state: InterviewState, reason: str) -> str:
    lead = (
        "We've reached the end of our time."
        if reason == "time_up"
        else "That's the end of the interview."
    )
    return (
        f"{lead} Thank you for your time, {state.candidate.first_name}. The "
        f"{state.job.company} team will review it and be in touch. Please keep the app open "
        "until it says your recordings have finished uploading."
    )


def proctor_reminder(kind: str) -> str:
    reminders = {
        "camera_covered": "Your camera appears to be covered. Please make sure your face is "
        "visible.",
        "face_missing": "I can't see you on camera. Please stay in view of the camera.",
        "multiple_faces": "It looks like someone else may be with you. Please continue on "
        "your own.",
        "focus_lost": "Please keep the interview app in focus.",
        "phone_detected": "Please put any phones or other devices away.",
        "blocked_application": "Please close the other application that is running.",
        "second_display": "Please use a single display for this interview.",
        "screen_share_stopped": "Your screen is no longer being shared. Please restore it.",
        "device_disconnected": "Your camera or microphone seems to be disconnected. Please "
        "reconnect it.",
        "third_eye_disconnected": "Your phone camera has disconnected. Please reconnect it.",
    }
    return reminders.get(kind, "Please keep to the interview's rules.")
