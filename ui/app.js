(() => {
  "use strict";

  const readingProgress = document.querySelector(".reading-progress");
  let scrollFrame = null;

  const updateScroll = () => {
    const root = document.documentElement;
    const distance = Math.max(0, root.scrollHeight - window.innerHeight);
    const progress = distance ? Math.min(1, Math.max(0, window.scrollY / distance)) : 0;
    if (readingProgress instanceof HTMLElement) {
      readingProgress.style.transform = `scaleX(${progress})`;
    }
    document.body.classList.toggle("is-scrolled", window.scrollY > 24);
    scrollFrame = null;
  };

  const scheduleScroll = () => {
    if (scrollFrame === null) scrollFrame = window.requestAnimationFrame(updateScroll);
  };

  window.addEventListener("scroll", scheduleScroll, { passive: true });
  window.addEventListener("resize", scheduleScroll, { passive: true });
  updateScroll();
})();
