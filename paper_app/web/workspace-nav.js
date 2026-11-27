"use strict";

(() => {
  const button = document.getElementById("workspace-nav-toggle");
  const navigation = document.getElementById("workspace-navigation");
  if (!button || !navigation) return;
  const compact = matchMedia("(max-width: 59.99rem)");
  const preferenceKey = "paper-library-sidebar";
  let preference;
  try {
    preference = localStorage.getItem(preferenceKey);
  } catch {
    preference = null;
  }

  function render() {
    const hidden = preference ? preference === "hidden" : compact.matches;
    navigation.hidden = hidden;
    document.body.dataset.sidebar = hidden ? "hidden" : "visible";
    button.setAttribute("aria-expanded", String(!hidden));
    button.textContent = hidden ? "Show sidebar" : "Hide sidebar";
  }

  function setPreference(hidden) {
    preference = hidden ? "hidden" : "visible";
    try {
      localStorage.setItem(preferenceKey, preference);
    } catch {
      // Keep the preference for the current page when storage is unavailable.
    }
    render();
  }

  button.hidden = false;
  button.addEventListener("click", () => setPreference(!navigation.hidden));
  compact.addEventListener("change", render);
  navigation.addEventListener("keydown", event => {
    if (event.key === "Escape" && !navigation.hidden) {
      setPreference(true);
      button.focus();
    }
  });
  render();
})();
