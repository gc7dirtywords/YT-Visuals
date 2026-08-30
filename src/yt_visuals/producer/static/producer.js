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

const beatCards = [...document.querySelectorAll("[data-beat-card]")];
const beatLinks = new Map(
  [...document.querySelectorAll("[data-beat-link]")].map((link) => [link.dataset.beatLink, link])
);

if (beatCards.length && "IntersectionObserver" in window) {
  const markActive = (id) => {
    beatLinks.forEach((link, beatId) => {
      link.classList.toggle("active", beatId === id);
      if (beatId === id) link.setAttribute("aria-current", "location");
      else link.removeAttribute("aria-current");
    });
  };
  const observer = new IntersectionObserver((entries) => {
    const visible = entries
      .filter((entry) => entry.isIntersecting)
      .sort((left, right) => Math.abs(left.boundingClientRect.top) - Math.abs(right.boundingClientRect.top));
    if (visible.length) markActive(visible[0].target.id);
  }, { rootMargin: "-145px 0px -55% 0px", threshold: [0, 0.05] });
  beatCards.forEach((card) => observer.observe(card));
  markActive(window.location.hash.slice(1) || beatCards[0].id);
}

document.querySelector("[data-expand-all]")?.addEventListener("click", () => {
  document.querySelectorAll(".beat-disclosure").forEach((item) => { item.open = true; });
});

document.querySelector("[data-collapse-completed]")?.addEventListener("click", () => {
  document.querySelectorAll(".beat-card.completed .beat-disclosure").forEach((item) => { item.open = false; });
});

const openHashBeat = () => {
  const card = document.getElementById(window.location.hash.slice(1));
  card?.querySelector(".beat-disclosure")?.setAttribute("open", "");
};
window.addEventListener("hashchange", openHashBeat);
openHashBeat();
