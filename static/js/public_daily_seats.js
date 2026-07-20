document.addEventListener("DOMContentLoaded", function () {
  const form = document.getElementById("quickSeatForm");
  if (!form) return;

  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
  const seatCodeInput = document.getElementById("seatCodeInput");
  const memberSelectInput = document.getElementById("memberSelectInput");
  const submitBtn = document.getElementById("quickSeatSubmitBtn");
  const alertArea = document.getElementById("quick-seat-alert-area");
  const resultCard = document.getElementById("quick-seat-result");
  const resultText = document.getElementById("quick-seat-result-text");

  function showAlert(message, type) {
    if (!alertArea) return;
    const div = document.createElement("div");
    div.className = `alert alert-${type} alert-dismissible fade show`;
    div.innerHTML = `${message}<button type="button" class="btn-close" data-bs-dismiss="alert"></button>`;
    alertArea.innerHTML = "";
    alertArea.appendChild(div);
  }

  function updateResult(payload) {
    if (!resultCard || !resultText) return;
    resultCard.style.display = "block";
    const actionText = payload.action === "booked" ? "Booked" : "Unbooked";
    resultText.textContent = `${actionText}: ${payload.seat_label} - ${payload.member_name}`;
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();

    const seatCode = seatCodeInput.value.trim();
    const memberId = memberSelectInput.value;
    const memberLabel = memberSelectInput.options[memberSelectInput.selectedIndex]?.text || "";

    if (!seatCode || !memberId) {
      showAlert("Seat number and member selection are required.", "warning");
      return;
    }

    submitBtn.disabled = true;
    fetch("/daily-seats/quick-access/toggle", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken,
      },
      body: JSON.stringify({
        seat_code: seatCode,
        member_id: parseInt(memberId, 10),
      }),
    })
      .then((response) => response.json().then((data) => ({ ok: response.ok, data })))
      .then(({ ok, data }) => {
        submitBtn.disabled = false;
        if (!ok || !data.success) {
          showAlert(data.message || "Could not process this request.", "danger");
          return;
        }

        showAlert(data.message || "Seat status updated.", "success");
        updateResult(data);
        seatCodeInput.value = "";
        if (memberLabel) {
          resultText.textContent = `${data.action === "booked" ? "Booked" : "Unbooked"}: ${data.seat_label} - ${memberLabel}`;
        }
        seatCodeInput.focus();
      })
      .catch(() => {
        submitBtn.disabled = false;
        showAlert("Something went wrong. Please try again.", "danger");
      });
  });
});
