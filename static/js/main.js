document.addEventListener("DOMContentLoaded", function () {
  const searchInputs = document.querySelectorAll(".ajax-search");
  searchInputs.forEach((input) => {
    input.addEventListener("input", function () {
      const url = input.dataset.url;
      if (!url) return;
      const query = input.value.trim();
      fetch(`${url}?q=${encodeURIComponent(query)}`)
        .then((response) => response.text())
        .then((html) => {
          const target = document.querySelector(input.dataset.target);
          if (target) target.innerHTML = html;
        });
    });
  });

  const toastElList = [].slice.call(document.querySelectorAll(".toast"));
  toastElList.forEach(function (toastEl) {
    const toast = new bootstrap.Toast(toastEl);
    toast.show();
  });

  const mediaArrows = document.querySelectorAll(".login-scroll-arrow");
  const resumeTimersByTrack = new Map();

  if (mediaArrows.length) {
    mediaArrows.forEach((arrow) => {
      arrow.addEventListener("click", function () {
        const direction = arrow.dataset.direction;
        const trackId = arrow.dataset.trackId || "login-media-track-main";
        const track = document.getElementById(trackId);
        if (!track) return;

        const firstItem = track.firstElementChild;
        const lastItem = track.lastElementChild;
        if (!firstItem || !lastItem) return;

        track.style.animationPlayState = "paused";
        if (direction === "right") {
          track.appendChild(firstItem);
        } else {
          track.insertBefore(lastItem, firstItem);
        }

        const previousTimer = resumeTimersByTrack.get(trackId);
        if (previousTimer) {
          clearTimeout(previousTimer);
        }

        const resumeTimer = setTimeout(function () {
          track.style.animationPlayState = "running";
        }, 2500);
        resumeTimersByTrack.set(trackId, resumeTimer);
      });
    });
  }

  const mobileSidebarEl = document.getElementById("mobileSidebar");
  if (mobileSidebarEl && window.bootstrap?.Offcanvas) {
    const mobileSidebar = bootstrap.Offcanvas.getOrCreateInstance(mobileSidebarEl);
    mobileSidebarEl.querySelectorAll("a.nav-link").forEach((link) => {
      link.addEventListener("click", function () {
        mobileSidebar.hide();
      });
    });
  }
});
