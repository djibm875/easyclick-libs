// Register page JavaScript (app/static/js/register.js)
document.addEventListener("DOMContentLoaded", function() {
    const registerForm = document.getElementById("registerForm");
    const messageDiv = document.getElementById("messageDiv");

    if (registerForm) {
        registerForm.addEventListener("submit", async function(event) {
            event.preventDefault();
            messageDiv.style.display = "none";
            messageDiv.className = "error-message"; // Reset class
            messageDiv.textContent = "";

            const username = document.getElementById("username").value;
            const email = document.getElementById("email").value;
            const password = document.getElementById("password").value;
            const tenant_name = document.getElementById("tenant_name").value;

            try {
                const response = await fetch("/auth/register", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({ username, email, password, tenant_name })
                });

                const data = await response.json();

                if (response.ok) {
                    messageDiv.textContent = "Registration successful! Redirecting to login...";
                    messageDiv.className = "success-message";
                    messageDiv.style.display = "block";
                    // Store user info and redirect or let them login manually
                    localStorage.setItem("currentUser", JSON.stringify(data)); // Assumes register returns user object
                    setTimeout(() => {
                        window.location.href = "dashboard.html"; // Or login.html
                    }, 2000);
                } else {
                    messageDiv.textContent = data.error || "Registration failed. Please try again.";
                    messageDiv.className = "error-message";
                    messageDiv.style.display = "block";
                }
            } catch (error) {
                console.error("Registration error:", error);
                messageDiv.textContent = "An error occurred during registration. Please try again.";
                messageDiv.className = "error-message";
                messageDiv.style.display = "block";
            }
        });
    }
});
