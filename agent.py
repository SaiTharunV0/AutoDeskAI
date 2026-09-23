import time
import json
from google import genai
from google.genai import types

from config import GEMINI_API_KEY
from schema import AgentResponse, Intent
from prompts import SYSTEM_PROMPT
from validator import validate_agent_response


MAX_HISTORY_MESSAGES = 20


client = genai.Client(
    api_key=GEMINI_API_KEY,
    http_options=types.HttpOptions(
        timeout=60000
    )
)


def _message(role: str, text: str) -> types.Content:
    return types.Content(
        role=role,
        parts=[types.Part.from_text(text=text)],
    )


def _resolve_pending_clarification(
    user_message: str,
    conversation_history: list[types.Content] | None,
) -> AgentResponse | None:
    if not conversation_history:
        return None

    last_message = conversation_history[-1]
    if last_message.role != "model" or not last_message.parts:
        return None

    try:
        previous_response = AgentResponse.model_validate(json.loads(last_message.parts[0].text))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None

    if previous_response.intent != Intent.CLARIFICATION:
        return None

    clarification = previous_response.message.lower()
    value = user_message.strip()

    if "which application" in clarification or "application or system" in clarification:
        return AgentResponse(
            intent=Intent.ACCESS_REQUEST,
            application=value,
            message=f"I can help you request access to {value}.",
        )

    if "which software" in clarification or "install" in clarification:
        return AgentResponse(
            intent=Intent.SOFTWARE_INSTALL,
            software=value,
            message=f"I can help you install {value}.",
        )

    return None


def process_request(
    user_message: str,
    conversation_history: list[types.Content] | None = None,
) -> AgentResponse:

    if not user_message.strip():
        result = AgentResponse(
            intent=Intent.CHAT,
            message="Please tell me how I can help with your IT request.",
        )
        return result

    pending_result = _resolve_pending_clarification(
        user_message,
        conversation_history,
    )
    if pending_result is not None:
        if conversation_history is not None:
            conversation_history.extend(
                [
                    _message("user", user_message),
                    _message("model", pending_result.model_dump_json()),
                ]
            )
            del conversation_history[:-MAX_HISTORY_MESSAGES]
        return pending_result

    user_turn = _message("user", user_message)
    request_contents = list(conversation_history or [])
    request_contents.append(user_turn)

    for attempt in range(3):

        try:

            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=request_contents,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=AgentResponse,
                )
            )

            result = AgentResponse.model_validate_json(
                response.text
            )

            # Our own safety validation
            result = validate_agent_response(result, user_message)

            if conversation_history is not None:
                conversation_history.extend(
                    [
                        user_turn,
                        _message("model", result.model_dump_json()),
                    ]
                )
                del conversation_history[:-MAX_HISTORY_MESSAGES]

            return result

        except Exception as e:

            print(
                f"Gemini attempt "
                f"{attempt + 1}/3 failed: {e}"
            )

            if attempt < 2:

                wait_time = 2 ** attempt

                print(
                    f"Retrying in "
                    f"{wait_time} seconds..."
                )

                time.sleep(wait_time)

    # Technical failure should NOT pretend
    # that the user's request was unsupported.
    print("Gemini unavailable.")

    raise RuntimeError(
        "AI service temporarily unavailable"
    )

if __name__ == "__main__":

    conversation_history: list[types.Content] = []

    while True:

        message = input("\nEmployee: ")

        if message.lower() in ["exit", "quit"]:
            break

        try:

            result = process_request(message, conversation_history)

            print("\nAI Agent:")
            print(
                result.model_dump_json(indent=2)
            )

        except RuntimeError as e:

            print("\nAI Agent ERROR:")
            print(str(e))