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

document.querySelector("[data-collapse-all]")?.addEventListener("click", () => {
  document.querySelectorAll(".beat-disclosure").forEach((item) => { item.open = false; });
});

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-audio-play]");
  if (!button) return;
  const audio = document.getElementById(button.dataset.audioPlay);
  if (!audio) return;
  if (audio.paused) {
    document.querySelectorAll("audio").forEach((item) => { if (item !== audio) item.pause(); });
    audio.play();
    button.textContent = "Pause";
  } else {
    audio.pause();
    button.textContent = "Play";
  }
  audio.addEventListener("ended", () => { button.textContent = "Play"; }, { once: true });
});

document.querySelectorAll("[data-tag-input]").forEach((input) => {
  const originalName = input.name;
  const control = document.createElement("span");
  control.className = "tag-control";
  const chips = document.createElement("span");
  chips.className = "tag-list";
  const add = document.createElement("button");
  add.type = "button";
  add.className = "tag-add";
  add.textContent = "+";
  add.title = "Add tag";
  input.removeAttribute("name");
  input.parentNode.insertBefore(control, input);
  control.append(chips, input, add);
  const addTags = () => {
    input.value.split(",").map((value) => value.trim()).filter(Boolean).forEach((value) => {
      const key = value.normalize("NFKC").replace(/\s+/g, " ").toLocaleLowerCase();
      if ([...control.querySelectorAll("input[type=hidden]")].some((item) => item.value === key)) return;
      const hidden = document.createElement("input");
      hidden.type = "hidden";
      hidden.name = originalName;
      hidden.value = key;
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "tag-chip removable";
      chip.textContent = `${key} ×`;
      chip.addEventListener("click", () => { hidden.remove(); chip.remove(); });
      control.append(hidden);
      chips.append(chip);
    });
    input.value = "";
  };
  add.addEventListener("click", addTags);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      addTags();
    }
  });
  input.form?.addEventListener("submit", addTags);
});

const openHashBeat = () => {
  const card = document.getElementById(window.location.hash.slice(1));
  card?.querySelector(".beat-disclosure")?.setAttribute("open", "");
};
window.addEventListener("hashchange", openHashBeat);
openHashBeat();
