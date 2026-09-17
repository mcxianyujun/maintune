from dataclasses import dataclass
import re
from typing import Iterable


@dataclass(frozen=True)
class MergeEvidence:
    enabled: bool = False
    ci_passed: bool = False
    review_passed: bool = False
    blocking: bool = True
    low_risk: bool = False
    sensitive_files: bool = True
    breaking_change: bool = True
    security_change: bool = True
    owner_required: bool = True
    reviewed_sha: str = ""
    current_sha: str = ""


def merge_blockers(e: MergeEvidence) -> list[str]:
    checks = {"automatic merge disabled": e.enabled, "CI not passed": e.ci_passed,
              "review not passed": e.review_passed, "blocking findings": not e.blocking,
              "risk not low": e.low_risk, "sensitive files": not e.sensitive_files,
              "breaking change": not e.breaking_change, "security change": not e.security_change,
              "owner decision required": not e.owner_required,
              "reviewed head is stale or absent": bool(e.current_sha) and e.current_sha == e.reviewed_sha}
    return [reason for reason, passed in checks.items() if not passed]


@dataclass(frozen=True)
class TriageGate:
    classification: str = "maintenance_bug"
    risk: str = "low"
    owner_required: bool = False
    reason: str = ""
    affected_components: tuple[str, ...] = ()


_HIGH_RISK_RULES = {
    "auto_merge_policy": (r"auto[- ]?merge|自动合并|merge policy", "Controller merge policy"),
    "credential_handling": (r"credential|api key|密钥|凭据|secret storage|secret handling", "Secret storage"),
    "sandbox_privilege": (r"sandbox.*privilege|privilege.*sandbox|沙箱.*权限|提权", "Sandbox boundary"),
    "authentication": (r"authentication|authorization|auth\b|登录认证|身份验证|鉴权", "Authentication"),
    "webhook_validation": (r"webhook.*(validation|signature|verify)|webhook.*(验证|签名)", "Webhook verification"),
    "github_write_authority": (r"github.*write|write authority|写入权限|写权限", "GitHub write authority"),
}
_FEATURE_RE = re.compile(
    r"\b(add|introduce|implement|support|feature|new capability|automatic cleanup)\b|"
    r"新增|新功能|增加.*功能|支持.*功能|自动清理|功能请求",
    re.IGNORECASE,
)
_NON_ACTIONABLE_RE = re.compile(
    r"^(?:hi|hello|hey|thanks|thank you|good job|洛天依好可爱|天依好可爱|辛苦了|谢谢)[\s!！。.~～\U0001F300-\U0001FAFF]*$",
    re.IGNORECASE,
)


def owner_action(decision: str, explicit_action: str | None = None) -> str:
    """Resolve an owner decision into a controller action.

    ``explicit_action`` is the authoritative value from the UI/API.  The text
    fallback keeps decisions recorded before the structured field existed safe:
    a clear close/reject instruction must never reach a model or sandbox.
    """
    if explicit_action in {"implement", "reject", "defer"}:
        return explicit_action
    text = (decision or "").casefold()
    if any(token in text for token in ("不修改", "关闭", "拒绝", "不实施", "reject", "close", "decline")):
        return "reject"
    if any(token in text for token in ("暂缓", "延后", "稍后", "defer", "hold")):
        return "defer"
    return "implement"


def _high_risk(text: str) -> tuple[list[str], list[str]]:
    reasons, components = [], []
    for reason, (pattern, component) in _HIGH_RISK_RULES.items():
        if re.search(pattern, text, re.IGNORECASE):
            reasons.append(reason)
            components.append(component)
    return reasons, components


def issue_triage_gate(title: str, body: str) -> TriageGate:
    text = f"{title}\n{body}".strip()
    # Issue titles and bodies are separate user inputs.  A concise chat title
    # may be repeated in the body, so classify either field directly instead
    # of requiring the concatenated two-line representation to match.
    if _NON_ACTIONABLE_RE.fullmatch(title.strip()) or _NON_ACTIONABLE_RE.fullmatch(body.strip()):
        return TriageGate("non_actionable", "low", False, "non_actionable_chat")
    reasons, components = _high_risk(text)
    if reasons:
        return TriageGate("high_risk_change", "high", True, ",".join(reasons), tuple(components))
    if _FEATURE_RE.search(text):
        return TriageGate("product_feature", "medium", True, "owner_decision_required", ("Product behavior",))
    return TriageGate()


_SENSITIVE_PATHS = (
    "backend/maintainer/policy.py",
    "backend/maintainer/security.py",
    "backend/maintainer/github.py",
    "backend/maintainer/sandboxes.py",
    "backend/maintainer/tasks.py",
    "backend/maintainer/api.py",
    ".github/workflows/",
)


def pull_triage_gate(title: str, body: str, paths: Iterable[str]) -> TriageGate:
    text = f"{title}\n{body}".strip()
    reasons, components = _high_risk(text)
    sensitive = [path for path in paths if any(path == prefix or path.startswith(prefix) for prefix in _SENSITIVE_PATHS)]
    if sensitive:
        reasons.append("sensitive_path")
        components.extend(sensitive[:10])
    if reasons:
        return TriageGate("high_risk_change", "high", True, ",".join(dict.fromkeys(reasons)), tuple(dict.fromkeys(components)))
    if _FEATURE_RE.search(text):
        return TriageGate("product_feature", "medium", True, "owner_decision_required", ("Product behavior",))
    return TriageGate()
