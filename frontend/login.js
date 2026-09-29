// Pantalla de inicio de sesión.

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const error = $("#login-error");
  error.hidden = true;
  $("#login-btn").disabled = true;
  try {
    const user = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username: $("#username").value, password: $("#password").value }),
    });
    applyTheme(user.theme);
    window.location.href = "/";
  } catch (err) {
    error.textContent = err.message;
    error.hidden = false;
    $("#login-btn").disabled = false;
  }
});
