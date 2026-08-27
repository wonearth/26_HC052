(function () {
  const input = document.getElementById("nickname");
  const hint = document.getElementById("nickname-hint");
  const checkBtn = document.getElementById("check-btn");
  const form = document.getElementById("signup-form");
  let checkedNickname = null;
  let isAvailable = false;

  function resetCheck() {
    checkedNickname = null;
    isAvailable = false;
    hint.textContent = "";
    hint.className = "field-hint";
  }

  input.addEventListener("input", resetCheck);

  checkBtn.addEventListener("click", async () => {
    const nickname = input.value.trim();
    if (!nickname) {
      hint.textContent = "닉네임을 입력해주세요.";
      hint.className = "field-hint warn";
      return;
    }
    hint.textContent = "확인 중...";
    hint.className = "field-hint";
    try {
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
    } catch (e) {
      hint.textContent = "확인 중 오류가 발생했어요.";
      hint.className = "field-hint warn";
    }
  });

  form.addEventListener("submit", (e) => {
    const nickname = input.value.trim();
    if (checkedNickname !== nickname || !isAvailable) {
      e.preventDefault();
      hint.textContent = "닉네임 중복확인을 먼저 해주세요.";
      hint.className = "field-hint warn";
    }
  });
})();
