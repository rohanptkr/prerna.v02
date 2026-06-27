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

  const mediaTrack = document.getElementById("login-media-track-main");
  const mediaArrows = document.querySelectorAll(".login-scroll-arrow");

  if (mediaTrack && mediaArrows.length) {
    let resumeTimer = null;
    mediaArrows.forEach((arrow) => {
      arrow.addEventListener("click", function () {
        const direction = arrow.dataset.direction;
        const firstItem = mediaTrack.firstElementChild;
        const lastItem = mediaTrack.lastElementChild;

        if (!firstItem || !lastItem) return;

        mediaTrack.style.animationPlayState = "paused";
        if (direction === "right") {
          mediaTrack.appendChild(firstItem);
        } else {
          mediaTrack.insertBefore(lastItem, firstItem);
        }

        if (resumeTimer) {
          clearTimeout(resumeTimer);
        }
        resumeTimer = setTimeout(function () {
          mediaTrack.style.animationPlayState = "running";
        }, 2500);
      });
    });
  }
});
