// Login page JavaScript (app/static/js/login.js)
document.addEventListener("DOMContentLoaded", function() {
    const loginForm = document.getElementById("loginForm");
    const errorMessageDiv = document.getElementById("errorMessage");

    if (loginForm) {
        loginForm.addEventListener("submit", async function(event) {
            event.preventDefault();
            errorMessageDiv.style.display = "none";
            errorMessageDiv.textContent = "";

            const username = document.getElementById("username").value;
            const password = document.getElementById("password").value;

            try {
                const response = await fetch("/auth/login", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({ username, password })
                });

                const data = await response.json();

                if (response.ok) {
                    // Login successful, store user info or token if needed
                    // For example, save to localStorage (consider security implications for tokens)
                    localStorage.setItem("currentUser", JSON.stringify(data.user));
                    // Redirect to a dashboard or main page
                    window.location.href = "dashboard.html"; // Assuming a dashboard.html exists
                } else {
                    errorMessageDiv.textContent = data.error || "Login failed. Please try again.";
                    errorMessageDiv.style.display = "block";
                }
            } catch (error) {
                console.error("Login error:", error);
                errorMessageDiv.textContent = "An error occurred during login. Please try again.";
                errorMessageDiv.style.display = "block";
            }
        });
    }
});
