// One timer and at most one active request per job. Explicit refreshes after a
// mutation wait for an active read, then fetch the new state.
export function startPolling(jobs, options = {}) {
  const visibility = options.visibility ?? document;
  const setTimer = options.setTimer ?? setTimeout;
  const clearTimer = options.clearTimer ?? clearTimeout;
  const now = options.now ?? Date.now;
  const onError = options.onError ?? (() => {});
  const entries = new Map(jobs.map(job => [job.name, {
    ...job, timer: null, promise: null, queued: null, controller: null, last: null, enabled: true,
    failures: 0, dirty: false,
  }]));
  let stopped = false;
  const visible = () => !visibility.hidden;

  function schedule(entry, delay) {
    if (entry.timer !== null) clearTimer(entry.timer);
    entry.timer = null;
    if (!stopped && visible() && entry.enabled) entry.timer = setTimer(() => {
      entry.timer = null;
      void run(entry);
    }, delay);
  }

  function run(entry, force = false) {
    if (stopped) return Promise.resolve();
    if (!visible()) {
      if (force) entry.dirty = true;
      return Promise.resolve();
    }
    if (!force && !entry.enabled) return Promise.resolve();
    if (entry.promise) {
      if (!force) return entry.promise;
      if (!entry.queued) entry.queued = entry.promise.then(() => {
        entry.queued = null;
        return run(entry, true);
      });
      return entry.queued;
    }
    if (entry.timer !== null) clearTimer(entry.timer);
    entry.timer = null;
    const controller = new AbortController();
    entry.controller = controller;
    entry.dirty = false;
    entry.promise = Promise.resolve().then(() => {
      if (!controller.signal.aborted) return entry.load(controller.signal);
    })
      .then(keepPolling => { if (!controller.signal.aborted) {
        entry.enabled = keepPolling !== false;
        entry.failures = 0;
      } })
      .catch(error => { if (!stopped && !controller.signal.aborted) {
        entry.failures++;
        entry.enabled = true;
        onError(error);
      } })
      .finally(() => {
        entry.promise = null;
        entry.controller = null;
        if (!controller.signal.aborted) entry.last = now();
        const delay = entry.failures ? Math.min(entry.interval * 2 ** Math.min(entry.failures, 6),
          options.maxBackoff ?? 120000) : entry.interval;
        if (!stopped && visible()) schedule(entry, controller.signal.aborted ? 0 : delay);
      });
    return entry.promise;
  }

  function onVisibilityChange() {
    if (!visible()) {
      for (const entry of entries.values()) {
        if (entry.timer !== null) clearTimer(entry.timer);
        entry.timer = null;
        entry.controller?.abort();
      }
    } else {
      for (const entry of entries.values()) {
        if (!entry.promise) {
          if (entry.dirty || !entry.enabled) void run(entry, true);
          else schedule(entry,
            entry.last === null ? 0 : Math.max(0, entry.interval - (now() - entry.last)));
        }
      }
    }
  }

  visibility.addEventListener('visibilitychange', onVisibilityChange);
  for (const entry of entries.values()) schedule(entry, 0);
  return {
    refresh(name) {
      const entry = entries.get(name);
      if (!entry) throw new Error(`Unknown poll job: ${name}`);
      return run(entry, true);
    },
    stop() {
      if (stopped) return;
      stopped = true;
      visibility.removeEventListener('visibilitychange', onVisibilityChange);
      for (const entry of entries.values()) {
        if (entry.timer !== null) clearTimer(entry.timer);
        entry.timer = null;
        entry.controller?.abort();
      }
    },
  };
}
