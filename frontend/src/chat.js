export const CHAT_MESSAGE_LIMIT = 2000;

export function chatComposerState(message, busy, retryAfter = 0) {
  const trimmed = message.trim();
  return {
    count: message.length,
    overLimit: message.length > CHAT_MESSAGE_LIMIT,
    disabled: busy || !trimmed || retryAfter > 0 || message.length > CHAT_MESSAGE_LIMIT,
    hint: retryAfter > 0 ? `Please wait ${retryAfter} seconds before sending another message.`
      : 'I can help with password change/reset, application access, and request statuses. Software installation is not implemented yet.',
  };
}
