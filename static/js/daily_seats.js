document.addEventListener("DOMContentLoaded", function () {
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
  const alertArea = document.getElementById("daily-seats-alert-area");

  const bookModalEl = document.getElementById("bookSeatModal");
  const unbookModalEl = document.getElementById("unbookSeatModal");
  if (!bookModalEl || !unbookModalEl) return;

  const bookModal = new bootstrap.Modal(bookModalEl);
  const unbookModal = new bootstrap.Modal(unbookModalEl);

  const memberSelect = document.getElementById("memberSelect");
  const bookSeatError = document.getElementById("bookSeatError");
  const confirmBookBtn = document.getElementById("confirmBookBtn");
  const bookSeatNumberLabel = document.getElementById("bookSeatNumberLabel");

  const unbookSeatNumberLabel = document.getElementById("unbookSeatNumberLabel");
  const unbookSeatNumberText = document.getElementById("unbookSeatNumberText");
  const unbookMemberNameText = document.getElementById("unbookMemberNameText");
  const unbookSeatError = document.getElementById("unbookSeatError");
  const confirmUnbookBtn = document.getElementById("confirmUnbookBtn");

  let activeSeatNumber = null;
  let activeSeatLabel = null;
  let activeSeatBtn = null;

  function showAlert(message, type) {
    if (!alertArea) return;
    const div = document.createElement("div");
    div.className = `alert alert-${type} alert-dismissible fade show`;
    div.innerHTML = `${message}<button type="button" class="btn-close" data-bs-dismiss="alert"></button>`;
    alertArea.appendChild(div);
    setTimeout(() => div.remove(), 5000);
  }

  function escape(val) {
    const d = document.createElement("div");
    d.textContent = val;
    return d.innerHTML;
  }

  function setSeatBooked(btn, seatLabel, memberName) {
    btn.classList.remove("available", "reserved");
    btn.classList.add("booked");
    btn.dataset.status = "Booked";
    btn.dataset.memberName = memberName;
    btn.dataset.seatLabel = seatLabel;
    btn.innerHTML = `<span>${seatLabel}</span><span class="seat-name">${escape(memberName)}</span>`;
  }

  function setSeatAvailable(btn, seatLabel) {
    btn.classList.remove("booked", "reserved");
    btn.classList.add("available");
    btn.dataset.status = "Available";
    const reservedMemberId = btn.dataset.reservedMemberId || "";
    const reservedMemberName = btn.dataset.reservedMemberName || "";
    const isReserved = Boolean(reservedMemberId);
    btn.dataset.isReserved = isReserved ? "true" : "false";
    btn.dataset.memberName = isReserved ? reservedMemberName : "";
    btn.dataset.memberId = isReserved ? reservedMemberId : "";
    btn.dataset.seatLabel = seatLabel;
    btn.innerHTML = isReserved
      ? `<span>${seatLabel}</span><span class="seat-name">${escape(reservedMemberName)}</span>`
      : `<span>${seatLabel}</span>`;
  }

  document.querySelectorAll(".seat-btn").forEach((btn) => {
    btn.addEventListener("click", function () {
      activeSeatNumber = parseInt(btn.dataset.seatNumber, 10);
      activeSeatLabel = btn.dataset.seatLabel || String(activeSeatNumber);
      activeSeatBtn = btn;

      if (btn.dataset.status === "Available") {
        if (btn.dataset.isReserved === "true" && btn.dataset.reservedMemberId) {
          memberSelect.value = btn.dataset.reservedMemberId;
          memberSelect.disabled = true;
        } else {
          memberSelect.value = "";
          memberSelect.disabled = false;
        }
        bookSeatError.style.display = "none";
        bookSeatNumberLabel.textContent = activeSeatLabel;
        bookModal.show();
        setTimeout(() => memberSelect.focus(), 300);
      } else {
        unbookSeatError.style.display = "none";
        unbookSeatNumberLabel.textContent = activeSeatLabel;
        unbookSeatNumberText.textContent = activeSeatLabel;
        unbookMemberNameText.textContent = btn.dataset.memberName || "—";
        unbookModal.show();
      }
    });
  });

  confirmBookBtn.addEventListener("click", function () {
    const memberId = memberSelect.value;
    const memberName = memberSelect.options[memberSelect.selectedIndex]?.dataset.name || "";
    if (!memberId) {
      bookSeatError.textContent = "Please select a member.";
      bookSeatError.style.display = "block";
      return;
    }

    confirmBookBtn.disabled = true;
    fetch("/daily-seats/book", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
      body: JSON.stringify({ 
        seat_number: activeSeatNumber, 
        member_id: parseInt(memberId),
        lab: window.currentLab || 2
      }),
    })
      .then((r) => r.json().then((d) => ({ ok: r.ok, d })))
      .then(({ ok, d }) => {
        confirmBookBtn.disabled = false;
        if (!ok || !d.success) {
          bookSeatError.textContent = d.message || "Could not book this seat.";
          bookSeatError.style.display = "block";
          return;
        }
        const seatLabel = d.seat_label || activeSeatLabel;
        setSeatBooked(activeSeatBtn, seatLabel, d.member_name);
        activeSeatBtn.dataset.memberId = d.member_id;
        memberSelect.disabled = false;
        bookModal.hide();
        showAlert(`Seat ${seatLabel} booked for ${escape(d.member_name)}. Attendance login recorded.`, "success");
      })
      .catch(() => {
        confirmBookBtn.disabled = false;
        memberSelect.disabled = false;
        bookSeatError.textContent = "Something went wrong. Please try again.";
        bookSeatError.style.display = "block";
      });
  });

  confirmUnbookBtn.addEventListener("click", function () {
    confirmUnbookBtn.disabled = true;
    fetch("/daily-seats/unbook", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
      body: JSON.stringify({ seat_number: activeSeatNumber }),
    })
      .then((r) => r.json().then((d) => ({ ok: r.ok, d })))
      .then(({ ok, d }) => {
        confirmUnbookBtn.disabled = false;
        if (!ok || !d.success) {
          unbookSeatError.textContent = d.message || "Could not unbook this seat.";
          unbookSeatError.style.display = "block";
          return;
        }
        const seatLabel = d.seat_label || activeSeatLabel;
        setSeatAvailable(activeSeatBtn, seatLabel);
        unbookModal.hide();
        showAlert(`Seat ${seatLabel} freed. Logout time recorded in attendance.`, "success");
      })
      .catch(() => {
        confirmUnbookBtn.disabled = false;
        unbookSeatError.textContent = "Something went wrong. Please try again.";
        unbookSeatError.style.display = "block";
      });
  });
});
