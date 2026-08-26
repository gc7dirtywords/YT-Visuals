document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-copy]");
  if (!button) return;
  const original = button.textContent;
  try {
    await navigator.clipboard.writeText(button.dataset.copy);
    button.textContent = "Copied";
  } catch (_) {
    window.prompt("Copy this value", button.dataset.copy);
  }
  window.setTimeout(() => { button.textContent = original; }, 1200);
});
