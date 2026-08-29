(function () {
  const toggle = document.getElementById("theme-toggle");
  const buttons = toggle.querySelectorAll("button");
  const current = localStorage.getItem("pmadas-theme") || "dark"; // 기본값: 다크

  function applyActive(value) {
    buttons.forEach((b) => b.classList.toggle("active", b.dataset.themeValue === value));
  }

  function setTheme(value) {
    if (value === "system") {
      localStorage.removeItem("pmadas-theme");
      document.documentElement.removeAttribute("data-theme");
    } else {
      localStorage.setItem("pmadas-theme", value);
      document.documentElement.setAttribute("data-theme", value);
    }
    applyActive(value);
  }

  applyActive(current);
  buttons.forEach((b) => b.addEventListener("click", () => setTheme(b.dataset.themeValue)));

  const nicknameInput = document.getElementById("nickname-input");
  const checkBtn = document.getElementById("nickname-check-btn");
  const hint = document.getElementById("nickname-change-hint");
  const form = document.getElementById("nickname-form");
  let checkedNickname = null;
  let isAvailable = false;

  nicknameInput.addEventListener("input", () => {
    checkedNickname = null;
    isAvailable = false;
    hint.textContent = "";
    hint.className = "field-hint";
  });

  checkBtn.addEventListener("click", async () => {
    const nickname = nicknameInput.value.trim();
    if (!nickname) {
      hint.textContent = "닉네임을 입력해주세요.";
      hint.className = "field-hint warn";
      return;
    }
    hint.textContent = "확인 중...";
    hint.className = "field-hint";
    const res = await fetch("/api/check-nickname", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nickname }),
    });
    const data = await res.json();
    checkedNickname = nickname;
    isAvailable = data.available;
    hint.textContent = data.available
      ? "사용할 수 있는 닉네임이에요."
      : "이미 사용 중이거나 사용할 수 없는 닉네임이에요.";
    hint.className = "field-hint " + (data.available ? "ok" : "warn");
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const nickname = nicknameInput.value.trim();
    if (!nickname) return;
    if (checkedNickname !== nickname || !isAvailable) {
      hint.textContent = "닉네임 중복확인을 먼저 해주세요.";
      hint.className = "field-hint warn";
      return;
    }
    const res = await fetch("/api/change-nickname", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nickname }),
    });
    if (res.ok) {
      window.location.reload();
    } else {
      const data = await res.json();
      hint.textContent = data.error || "변경에 실패했어요.";
      hint.className = "field-hint warn";
    }
  });
})();
