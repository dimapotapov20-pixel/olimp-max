/* MAX-only bootstrap. It is inert in the ordinary browser preview. */
(async () => {
  const max = window.WebApp;
  if (!max) return;

  // Reserve the full mobile canvas as soon as MAX injects its bridge. In an
  // ordinary browser preview these methods are simply unavailable.
  max.ready?.();
  max.expand?.();
  document.documentElement.classList.add('inside-max');

  if (!max.initData) return;

  try {
    const response = await fetch('/api/auth/max', {
      method: 'POST',
      headers: { 'X-MAX-Init-Data': max.initData },
    });
    if (!response.ok) throw new Error(`MAX auth failed: ${response.status}`);
    const { user } = await response.json();
    window.dispatchEvent(new CustomEvent('olimp:max-authenticated', { detail: user }));
  } catch (error) {
    // Keep the UI usable while showing a real error only in the app integration.
    console.warn('Olimp could not authenticate MAX launch data', error);
  }
})();
