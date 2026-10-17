export function validatedSsprUrl(value) {
  if (typeof value !== 'string' || !value.trim()) return null;
  try {
    const url = new URL(value.trim());
    if (url.protocol !== 'https:' || url.hostname !== 'passwordreset.microsoftonline.com'
        || url.port && url.port !== '443' || url.username || url.password || url.hash) return null;
    return url.href;
  } catch {
    return null;
  }
}
