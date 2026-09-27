document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".friend-password-toggle").forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetId = btn.getAttribute("data-target");
      const input = targetId ? document.getElementById(targetId) : null;
      if (!input) return;

      const isVisible = input.type === "text";
      input.type = isVisible ? "password" : "text";
      btn.textContent = isVisible ? "Show" : "Hide";
      btn.setAttribute("aria-pressed", String(!isVisible));
    });
  });
});
