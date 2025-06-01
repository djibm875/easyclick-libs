// Devices page JavaScript (app/static/js/devices.js)
document.addEventListener("DOMContentLoaded", function() {
    const devicesTableBody = document.getElementById("devicesTableBody");
    const devicesTable = document.getElementById("devicesTable");
    const deviceListContainer = document.getElementById("deviceListContainer");
    // const errorMessageDiv = document.getElementById("errorMessage"); // Already declared if using full file

    const registerDeviceModal = document.getElementById("registerDeviceModal");
    const showRegisterDeviceFormBtn = document.getElementById("showRegisterDeviceForm");
    const cancelRegisterDeviceBtn = document.getElementById("cancelRegisterDevice");
    const registerDeviceForm = document.getElementById("registerDeviceForm");
    const registerDeviceMessageDiv = document.getElementById("registerDeviceMessage");

    const currentUser = JSON.parse(localStorage.getItem("currentUser"));
    if (!currentUser) {
        window.location.href = "login.html";
        return;
    }

    // Store active SocketIO connections to prevent duplicates and manage them
    // This is a simple client-side store. Key is deviceId.
    const activeSockets = {};


    async function fetchDevices() {
        // ... (existing fetchDevices code - assumed to be here and correct)
        try {
            const response = await fetch("/api/devices/");
            if (!response.ok) {
                if (response.status === 401) {
                    localStorage.removeItem("currentUser");
                    window.location.href = "login.html";
                }
                const errorData = await response.json();
                throw new Error(errorData.error || "Failed to fetch devices");
            }
            const data = await response.json();
            displayDevices(data.devices);
        } catch (error) {
            console.error("Error fetching devices:", error);
            deviceListContainer.innerHTML = `<p class="error-message">Error loading devices: ${error.message}</p>`;
        }
    }

    function displayDevices(devices) {
        // ... (existing displayDevices code - assumed to be here and correct, including action buttons)
        devicesTableBody.innerHTML = "";
        if (devices && devices.length > 0) {
            devices.forEach(device => {
                const row = devicesTableBody.insertRow();
                row.insertCell().textContent = device.device_name || "N/A";
                row.insertCell().textContent = device.device_id;
                row.insertCell().textContent = device.platform;
                row.insertCell().textContent = device.os_version || "N/A";
                row.insertCell().textContent = device.status;
                row.insertCell().textContent = device.last_seen ? new Date(device.last_seen).toLocaleString() : "Never";
                const actionsCell = row.insertCell();
                actionsCell.className = "actions-column";
                actionsCell.innerHTML = `
                    <button onclick="viewDeviceDetails('${device.device_id}')">Details</button>
                    <button id="mirrorBtn-${device.device_id}" onclick="toggleMirroring('${device.device_id}')">Mirror</button>
                    <button onclick="assignTaskToDevice('${device.device_id}')">Assign Task</button>
                    <button style="background-color:#dc3545" onclick="deleteDevice('${device.device_id}', this)">Delete</button>
                `;
            });
            devicesTable.style.display = "table";
            if (deviceListContainer.querySelector("p")) {
                 deviceListContainer.querySelector("p").style.display = "none";
            }
        } else {
            deviceListContainer.innerHTML = "<p>No devices found for your tenant.</p>";
        }
    }

    // --- Mirroring Logic with Token ---
    window.toggleMirroring = async function(deviceId) {
        const mirrorButton = document.getElementById(`mirrorBtn-${deviceId}`);
        if (activeSockets[deviceId] && activeSockets[deviceId].connected) {
            // If socket exists and is connected, this means "Stop Mirroring"
            console.log(`Stopping mirroring for ${deviceId}`);
            activeSockets[deviceId].emit("leave_mirror_session", { device_id: deviceId });
            activeSockets[deviceId].disconnect();
            // No need to call /api/mirroring/stop here if disconnect handles server-side session state via SocketIO
            // However, an explicit stop API call might be good for cleanup if SocketIO disconnect is not guaranteed to be caught by server always.
            // For now, let's assume server cleans up on SocketIO disconnect or session expiry.
            // Call the stop API for good measure to clear session state if server relies on it
            try {
                await fetch(`/api/mirroring/stop/${deviceId}`, { method: 'POST' });
            } catch(e) { console.warn("Error calling stop mirroring API, session might remain in store:", e); }

            delete activeSockets[deviceId];
            alert(`Mirroring stopped for ${deviceId}`);
            mirrorButton.textContent = "Mirror";
            mirrorButton.style.backgroundColor = ""; // Reset color
            // Hide mirroring UI if any was shown
            const mirrorView = document.getElementById(`mirror-view-${deviceId}`);
            if (mirrorView) mirrorView.style.display = "none";

        } else {
            // This means "Start Mirroring"
            console.log(`Attempting to start mirroring for ${deviceId}`);
            mirrorButton.textContent = "Connecting...";
            mirrorButton.disabled = true;
            try {
                const response = await fetch(`/api/mirroring/start/${deviceId}`, { method: 'POST' });
                const result = await response.json();

                if (response.ok && result.sio_conn_token) {
                    console.log(`Received SIO connection token for ${deviceId}: ${result.sio_conn_token.substring(0,10)}...`);
                    connectMirroringSocket(deviceId, result.sio_conn_token, mirrorButton);
                } else {
                    alert(`Failed to start mirroring for ${deviceId}: ${result.error || 'Unknown error'}`);
                    mirrorButton.textContent = "Mirror";
                    mirrorButton.disabled = false;
                }
            } catch (err) {
                alert(`Error starting mirroring for ${deviceId}: ${err.message}`);
                mirrorButton.textContent = "Mirror";
                mirrorButton.disabled = false;
            }
        }
    };

    function connectMirroringSocket(deviceId, token, buttonElement) {
        // Disconnect if already connected (should not happen if toggle logic is correct)
        if (activeSockets[deviceId] && activeSockets[deviceId].connected) {
            activeSockets[deviceId].disconnect();
        }

        console.log(`Connecting SocketIO for /mirroring with token for device ${deviceId}`);
        const socket = io("/mirroring", {
            query: { token: token }, // Send token as query parameter
            // For newer Socket.IO versions, `auth: { token: token }` is preferred
            // auth: { token: token }
            reconnectionAttempts: 3, // Limit reconnection attempts
        });
        activeSockets[deviceId] = socket; // Store the socket

        socket.on("connect", () => {
            console.log(`Socket connected for /mirroring (SID: ${socket.id}) for device ${deviceId}`);
            buttonElement.textContent = "Stop Mirror";
            buttonElement.style.backgroundColor = "orange";
            buttonElement.disabled = false;
            socket.emit("join_mirror_session", { device_id: deviceId });
        });

        socket.on("connection_ack", (data) => {
            console.log(`Connection acknowledged by server: ${JSON.stringify(data)}`);
        });

        socket.on("joined_session", (data) => {
            console.log(`Joined mirroring session: ${JSON.stringify(data)}`);
            // Show mirroring UI
            const mirrorView = document.getElementById(`mirror-view-${deviceId}`) || createMirrorView(deviceId);
            mirrorView.style.display = "block";
            mirrorView.querySelector('h4').textContent = `Mirroring: ${deviceId}`;
        });

        socket.on("left_session", (data) => {
            console.log(`Left mirroring session: ${JSON.stringify(data)}`);
        });

        socket.on("screen_update", (data) => {
            // console.log(`Screen update for device ${data.device_id}: ${data.frame ? data.frame.substring(0, 30) + "..." : "No frame"}\`);
            if (data.device_id === deviceId) {
                const mirrorView = document.getElementById(`mirror-view-${deviceId}`);
                if (mirrorView) {
                    const img = mirrorView.querySelector("img") || document.createElement('img');
                    img.src = data.frame; // Assuming frame is base64 data URL
                    if(!img.parentElement) mirrorView.appendChild(img);
                }
            }
        });

        socket.on("error", (errorData) => {
            console.error(`Socket error for device ${deviceId}: ${JSON.stringify(errorData)}`);
            alert(`Mirroring error for ${deviceId}: ${errorData.message || 'Unknown socket error'}`);
            socket.disconnect(); // Disconnect on error
        });

        socket.on("disconnect", (reason) => {
            console.log(`Socket disconnected for device ${deviceId}. Reason: ${reason}`);
            buttonElement.textContent = "Mirror";
            buttonElement.style.backgroundColor = "";
            buttonElement.disabled = false;
            delete activeSockets[deviceId];
            const mirrorView = document.getElementById(`mirror-view-${deviceId}`);
            if (mirrorView) mirrorView.style.display = "none";
            if (reason === "io server disconnect") {
                // Server initiated disconnect, possibly due to token expiry on connect or other auth issue
                alert(`Mirroring disconnected by server for ${deviceId}. Please try again.`);
            }
        });
    }

    function createMirrorView(deviceId) {
        // Simple placeholder for a mirror view area
        let view = document.createElement('div');
        view.id = `mirror-view-${deviceId}`;
        view.style.border = "1px solid #ccc";
        view.style.padding = "10px";
        view.style.marginTop = "10px";
        view.style.display = "none"; // Initially hidden
        view.innerHTML = `<h4>Mirroring: ${deviceId}</h4><p>Screen updates will appear here.</p>`;
        // Insert it somewhere, e.g., after the devices table or a dedicated area
        deviceListContainer.parentNode.insertBefore(view, deviceListContainer.nextSibling);
        return view;
    }

    // --- Other functions (deleteDevice, viewDeviceDetails, assignTaskToDevice) ---
    window.deleteDevice = async function(deviceId, buttonElement) { /* ... existing ... */
        if (!confirm(`Are you sure you want to delete device ${deviceId}?`)) return;
        try {
            const response = await fetch(`/api/devices/${deviceId}`, { method: 'DELETE' });
            const result = await response.json();
            if (response.ok) { alert(result.message || `Device ${deviceId} deleted.`); buttonElement.closest('tr').remove(); }
            else { alert(`Failed to delete ${deviceId}: ${result.error}`); }
        } catch (err) { alert(`Error deleting ${deviceId}: ${err.message}`); }
    };
    window.viewDeviceDetails = function(deviceId) { alert('View details for ' + deviceId); };
    window.assignTaskToDevice = function(deviceId) { alert('Assign task to ' + deviceId); };


    // --- Register Device Form Logic (from previous step, assumed correct) ---
    if (showRegisterDeviceFormBtn) { /* ... existing ... */
        showRegisterDeviceFormBtn.addEventListener("click", () => { registerDeviceModal.style.display = "block"; showRegisterDeviceFormBtn.style.display = "none"; });
    }
    if (cancelRegisterDeviceBtn) { /* ... existing ... */
        cancelRegisterDeviceBtn.addEventListener("click", () => { registerDeviceModal.style.display = "none"; showRegisterDeviceFormBtn.style.display = "block"; registerDeviceForm.reset(); registerDeviceMessageDiv.textContent = ""; registerDeviceMessageDiv.className = ""; });
    }
    if (registerDeviceForm) { /* ... existing ... */
        registerDeviceForm.addEventListener("submit", async function(event) {
            event.preventDefault(); registerDeviceMessageDiv.textContent = ""; registerDeviceMessageDiv.className = "";
            const deviceData = { device_id: document.getElementById("regDeviceId").value, device_name: document.getElementById("regDeviceName").value, platform: document.getElementById("regPlatform").value, os_version: document.getElementById("regOsVersion").value };
            try {
                const response = await fetch("/api/devices/register", { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(deviceData) });
                const result = await response.json();
                if (response.ok) {
                    registerDeviceMessageDiv.textContent = "Device registered successfully! API Key: " + (result.api_key || 'N/A'); // Show API key
                    registerDeviceMessageDiv.className = "success-message"; fetchDevices();
                    // Do not auto-hide form so user can copy API key
                    // setTimeout(() => { cancelRegisterDeviceBtn.click(); }, 5000);
                } else { registerDeviceMessageDiv.textContent = result.error || "Failed to register device."; registerDeviceMessageDiv.className = "error-message"; }
            } catch (err) { registerDeviceMessageDiv.textContent = "Error: " + err.message; registerDeviceMessageDiv.className = "error-message"; }
            registerDeviceMessageDiv.style.display = "block";
        });
    }

    // Initial fetch of devices
    fetchDevices();
});
