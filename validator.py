from schema import AgentResponse, Intent


def _contains_action(text: str, actions: tuple[str, ...]) -> bool:
    normalized = text.lower()
    return any(action in normalized for action in actions)


def validate_agent_response(
    result: AgentResponse,
    user_message: str | None = None,
) -> AgentResponse:
    if user_message and result.intent in (Intent.PASSWORD_CHANGE, Intent.PASSWORD_RESET):
        if "password" not in user_message.lower():
            return AgentResponse(intent=Intent.CLARIFICATION, message="Which IT workflow do you need?")

    if result.intent == Intent.ACCESS_REQUEST and user_message:
        if not _contains_action(
            user_message,
            ("access", "permission", "grant", "authorize", "authorise", "login", "log in", "sign in"),
        ):
            application = result.application or "that application"
            result.intent = Intent.CLARIFICATION
            result.application = None
            result.message = (
                f"What would you like help with regarding {application}? "
                "Do you need access to it or help installing it?"
            )
            return result

    if result.intent == Intent.SOFTWARE_INSTALL and user_message:
        if not _contains_action(
            user_message,
            ("install", "setup", "set up", "download"),
        ):
            software = result.software or "that software"
            result.intent = Intent.CLARIFICATION
            result.software = None
            result.message = (
                f"What would you like help with regarding {software}? "
                "Would you like me to install it?"
            )
            return result

    if result.intent == Intent.SOFTWARE_INSTALL:
        result.application = None
        if not result.software:
            result.intent = Intent.CLARIFICATION
            result.message = "Which software would you like me to help you install?"

    elif result.intent == Intent.ACCESS_REQUEST:
        result.software = None

        if not result.application:
            result.intent = Intent.CLARIFICATION
            result.message = "Which application do you need access to?"

    elif result.intent == Intent.PASSWORD_CHANGE:

        result.software = None
        result.application = None

    elif result.intent == Intent.PASSWORD_RESET:

        result.software = None
        result.application = None

    elif result.intent == Intent.CHAT:

        result.software = None
        result.application = None

    return result
