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
});
