// PRERNA ABHYASIKA — interactions (UI only, no backend calls)

document.addEventListener("DOMContentLoaded", () => {
  /* Mobile nav toggle */
  const navToggle = document.querySelector(".nav-toggle");
  const navLinks = document.querySelector(".nav-links");
  if (navToggle && navLinks) {
    navToggle.addEventListener("click", () => {
      const isOpen = navLinks.classList.toggle("is-open");
      navToggle.setAttribute("aria-expanded", String(isOpen));
    });
  }

  /* Password show/hide */
  document.querySelectorAll(".password-toggle").forEach((btn) => {
    btn.addEventListener("click", () => {
      const input = document.getElementById(btn.dataset.target);
      if (!input) return;
      const showing = input.type === "text";
      input.type = showing ? "password" : "text";
      btn.textContent = showing ? "Show" : "Hide";
      btn.setAttribute("aria-pressed", String(!showing));
    });
  });

  /* Gallery carousel arrows */
  const galleryTrack = document.getElementById("gallery-track");
  const galleryPrev = document.getElementById("gallery-prev");
  const galleryNext = document.getElementById("gallery-next");
  if (galleryTrack && galleryPrev && galleryNext) {
    const scrollByOne = (dir) => {
      const slide = galleryTrack.querySelector(".carousel-slide");
      const amount = slide ? slide.getBoundingClientRect().width + 24 : 300;
      galleryTrack.scrollBy({ left: dir * amount, behavior: "smooth" });
    };
    galleryPrev.addEventListener("click", () => scrollByOne(-1));
    galleryNext.addEventListener("click", () => scrollByOne(1));
  }

  /* Login form (frontend-only demo) */
  const loginForm = document.getElementById("login-form");
  if (loginForm) {
    loginForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const errorBox = document.getElementById("login-error");
      const successBox = document.getElementById("login-success");
      const email = document.getElementById("email").value.trim();
      const password = document.getElementById("password").value;

      errorBox.hidden = true;
      successBox.hidden = true;

      if (!email || !password) {
        errorBox.textContent = "Enter both email and password to continue.";
        errorBox.hidden = false;
        return;
      }
      successBox.textContent = "This is a UI preview only — sign-in is not connected yet.";
      successBox.hidden = false;
    });
  }

  /* Contact form (frontend-only demo) */
  const contactForm = document.getElementById("contact-form");
  if (contactForm) {
    contactForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const successBox = document.getElementById("contact-success");
      successBox.hidden = false;
      contactForm.reset();
      successBox.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  }

  /* Footer year */
  const yearEl = document.getElementById("year");
  if (yearEl) yearEl.textContent = new Date().getFullYear();
});
