export const NETWORK_ERROR = 'Unable to reach the server. Check your connection and try again.';
export const TIMEOUT_ERROR = 'The server took too long to respond. Please try again.';
export const GATEWAY_ERROR = 'The service is temporarily unavailable. Please try again shortly.';
export const SESSION_ERROR = 'Your session expired. Please sign in again.';
export const isConnectionError = message => [NETWORK_ERROR, TIMEOUT_ERROR, GATEWAY_ERROR].includes(message);

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

// No automatic retries: mutations may already have reached the server.
export async function requestApi(path, {token = '', timeoutMs = 60000, fetchImpl = fetch, ...options} = {}) {
  const controller = new AbortController();
  const external = options.signal;
  let timedOut = false;
  const abort = () => controller.abort();
  if (external?.aborted) abort();
  external?.addEventListener('abort', abort, {once: true});
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
  const headers = new Headers(options.headers);
  if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  if (token) headers.set('Authorization', `Bearer ${token}`);
  try {
    const response = await fetchImpl(`/api${path}`, {cache: 'no-store', ...options, headers, signal: controller.signal});
    const raw = await response.text();
    let data;
    try { data = raw ? JSON.parse(raw) : null; } catch { /* Proxy errors often contain HTML. */ }
    if (!response.ok) {
      const detail = data?.detail;
      const message = response.status === 401 && token ? SESSION_ERROR
        : typeof detail === 'string' ? detail
        : Array.isArray(detail) ? detail.map(item => item.msg).join('. ')
        : response.status >= 500 ? GATEWAY_ERROR
        : `Request failed (${response.status}). Please try again.`;
      throw new ApiError(message, response.status);
    }
    if (data === undefined) throw new ApiError('The server returned an unreadable response.', response.status);
    return data;
  } catch (error) {
    if (external?.aborted) throw new DOMException('Aborted', 'AbortError');
    if (timedOut) throw new ApiError(TIMEOUT_ERROR);
    if (error instanceof ApiError || error.name === 'AbortError') throw error;
    throw new ApiError(NETWORK_ERROR);
  } finally {
    clearTimeout(timer);
    external?.removeEventListener('abort', abort);
  }
}
