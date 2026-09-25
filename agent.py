"""Ollama classifies only a constrained, credential-free representation."""
import re
import ollama
import config
from schema import AgentResponse, Intent
from prompts import SYSTEM_PROMPT
from validator import validate_agent_response
from app.catalog import SOFTWARE, APPLICATIONS

class UnsafeRequest(ValueError):
    pass

def safe_message(text: str) -> str:
    # Do not send raw free text to any model. Preserve only known workflow tokens.
    # This deliberately sacrifices open-ended entity discovery to guarantee that
    # unknown text (including accidentally pasted credentials) never leaves here.
    lowered = text.lower()
    if re.search(r"(powershell|cmd\.exe|bash|curl|invoke-expression|execute|shell|script|rm -|&&|[;`])", lowered):
        raise UnsafeRequest("Only password, approved software, and application access workflows are supported.")
    if re.search(r"password\s*(?:is|=|:)\s*\S+|(?:token|secret|api[_ -]?key)\s*[:=]", lowered):
        raise UnsafeRequest("Do not enter credentials in chat. Use the dedicated authentication form.")
    words = re.findall(r"[a-z]+", lowered)
    permitted = {"i", "my", "need", "want", "please", "help", "forgot", "password", "reset",
                 "change", "update", "install", "installed", "setup", "set", "up", "download",
                 "access", "permission", "grant", "to", "for", "me", "on", "hello", "hi"}
    tokens = [word for word in words if word in permitted]
    for item in SOFTWARE.values():
        if any(re.search(r"\b" + re.escape(alias) + r"\b", lowered) for alias in item["aliases"]):
            tokens.append("vscode")
    for key in APPLICATIONS:
        if re.search(r"\b" + re.escape(key) + r"\b", lowered):
            tokens.append(key)
    unknown = set(words) - permitted - {"vscode", "vs", "code", "visual", "studio", "tableau",
        "can", "you", "could", "would", "like", "a", "an", "the", "some", "something",
        "software", "application", "app", "system", "computer", "laptop", "device", "it"}
    if unknown and any(word in tokens for word in ("install", "installed", "setup", "download")) and "vscode" not in tokens:
        tokens.append("unapproved_software")
    if unknown and any(word in tokens for word in ("access", "permission", "grant")) and "tableau" not in tokens:
        tokens.append("unknown_application")
    return " ".join(tokens) or "unspecified request"

def _resolve_pending_clarification(user_message, previous_response=None):
    if previous_response is None or previous_response.intent != Intent.CLARIFICATION:
        return None
    text = previous_response.message.lower()
    if "which application" in text:
        return AgentResponse(intent=Intent.ACCESS_REQUEST, application=user_message.strip(), message="Access request identified.")
    if "which software" in text:
        return AgentResponse(intent=Intent.SOFTWARE_INSTALL, software=user_message.strip(), message="Installation request identified.")
    return None

def process_request(user_message: str, previous_response: AgentResponse | None = None) -> AgentResponse:
    safe = safe_message(user_message)
    words = set(safe.split())
    actions = [bool(words & {"install", "installed", "setup", "download"}),
               bool(words & {"access", "permission", "grant"}), "password" in words]
    if sum(actions) > 1:
        return AgentResponse(intent=Intent.CLARIFICATION, message="Please request one workflow at a time.")
    pending = _resolve_pending_clarification(safe, previous_response)
    if pending:
        # Validate follow-up in the context of the prior backend-owned question.
        return validate_agent_response(pending)
    if not user_message.strip():
        return AgentResponse(intent=Intent.CHAT, message="Please describe your IT request.")
    try:
        client = ollama.Client(host=config.OLLAMA_HOST, timeout=config.OLLAMA_TIMEOUT)
        response = client.chat(model=config.OLLAMA_MODEL,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": safe}],
            format=AgentResponse.model_json_schema(), think=False,
            options={"temperature": 0, "num_predict": 180})
        result = AgentResponse.model_validate_json(response["message"]["content"])
        # Resolve omitted entities only from the constrained input, never from prose.
        if result.intent == Intent.ACCESS_REQUEST and not result.application:
            result.application = next((key for key in (*APPLICATIONS, "unknown_application") if key in safe.split()), None)
        if result.intent == Intent.SOFTWARE_INSTALL and not result.software:
            result.software = next((key for key in (*SOFTWARE, "unapproved_software") if key in safe.split()), None)
        return validate_agent_response(result, safe)
    except Exception:
        raise RuntimeError("Local AI unavailable or returned an invalid response. Please retry.") from None

if __name__ == "__main__":
    previous = None
    while True:
        message = input("Employee: ")
        if message.lower() in {"quit", "exit"}:
            break
        try:
            previous = process_request(message, previous)
            print(previous.model_dump_json())
        except (RuntimeError, UnsafeRequest) as error:
            print(str(error))
