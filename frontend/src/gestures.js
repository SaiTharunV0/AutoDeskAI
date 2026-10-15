// Touchscreens expose finger positions; trackpads expose horizontal wheel deltas.
// Preserve form editing, pinch zoom, and horizontally scrollable widgets.
export function attachPageGestures(target, navigate, {setTimer = setTimeout, clearTimer = clearTimeout} = {}) {
  let touch = null, wheelX = 0, wheelTimer = null, wheelHandled = false;
  const threshold = 90;
  const ignored = event => {
    let element = event.target;
    if (!element?.closest) return false;
    if (element.closest('input, textarea, select, [contenteditable="true"], [role="dialog"], .modalBg')) return true;
    for (; element && element !== target.document?.body; element = element.parentElement) {
      if (element.scrollWidth > element.clientWidth + 1 &&
          /auto|scroll/.test(target.getComputedStyle(element).overflowX)) return true;
    }
    return false;
  };
  const point = touches => ({
    x: (touches[0].clientX + touches[1].clientX) / 2,
    y: (touches[0].clientY + touches[1].clientY) / 2,
    distance: Math.hypot(touches[0].clientX - touches[1].clientX, touches[0].clientY - touches[1].clientY),
  });
  const touchStart = event => {
    touch = event.touches.length === 2 && !ignored(event)
      ? {start: point(event.touches), dx: 0, dy: 0} : null;
  };
  const touchMove = event => {
    if (!touch || event.touches.length !== 2) return;
    const current = point(event.touches);
    touch.dx = current.x - touch.start.x;
    touch.dy = current.y - touch.start.y;
    if (Math.abs(current.distance - touch.start.distance) > Math.max(25, touch.start.distance * 0.2) ||
        (Math.abs(touch.dy) > 25 && Math.abs(touch.dy) > Math.abs(touch.dx))) {
      touch = null;
      return;
    }
    if (Math.abs(touch.dx) > 25 && Math.abs(touch.dx) > Math.abs(touch.dy) * 1.5 && event.cancelable) event.preventDefault();
  };
  const touchEnd = event => {
    if (!touch || event.touches.length >= 2) return;
    if (Math.abs(touch.dx) >= threshold && Math.abs(touch.dx) > Math.abs(touch.dy) * 1.5) navigate(touch.dx > 0 ? -1 : 1);
    touch = null;
  };
  const touchCancel = () => { touch = null; };
  const resetWheel = () => { wheelX = 0; wheelHandled = false; wheelTimer = null; };
  const wheel = event => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || ignored(event)) return;
    if (Math.abs(event.deltaX) <= Math.abs(event.deltaY) * 1.5) return;
    if (event.cancelable) event.preventDefault();
    clearTimer(wheelTimer);
    wheelTimer = setTimer(resetWheel, 250);
    if (wheelHandled) return; // Momentum from one gesture must not skip several pages.
    const delta = event.deltaX * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? (target.innerWidth || 800) : 1);
    if (Math.sign(delta) !== Math.sign(wheelX)) wheelX = 0;
    wheelX += delta;
    if (Math.abs(wheelX) >= threshold) {
      wheelHandled = true;
      navigate(wheelX > 0 ? 1 : -1);
    }
  };
  const listeners = {touchstart: touchStart, touchmove: touchMove, touchend: touchEnd, touchcancel: touchCancel, wheel};
  for (const [name, listener] of Object.entries(listeners)) target.addEventListener(name, listener, {passive: !['wheel', 'touchmove'].includes(name)});
  return () => {
    for (const [name, listener] of Object.entries(listeners)) target.removeEventListener(name, listener);
    clearTimer(wheelTimer);
    touch = null;
  };
}
