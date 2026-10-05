const $ = (id) => document.getElementById(id);

function addLog(message) {
    const log = $("activityLog");
    const line = document.createElement("div");

    line.className = "log-line";

    const time = new Date().toLocaleTimeString();

    line.textContent = `[${time}] ${message}`;

    log.appendChild(line);
    log.scrollTop = log.scrollHeight;
}


function getConfig() {
    return {
        mode: $("mode").value,
        asset: $("asset").value,
        timeframe: Number($("timeframe").value),
        amount: Number($("amount").value),
        min_payout: Number($("minPayout").value),
        take_profit: Number($("takeProfit").value),
        stop_loss: Number($("stopLoss").value),
        martingale: $("martingale").value
    };
}


async function saveConfig() {
    const response = await fetch("/api/config", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify(getConfig())
    });

    if (!response.ok) {
        throw new Error("Could not save configuration");
    }

    return await response.json();
}


async function startBot() {
    try {
        $("startButton").disabled = true;

        await saveConfig();

        const response = await fetch("/api/start", {
            method: "POST"
        });

        if (!response.ok) {
            throw new Error("Could not start bot");
        }

        const data = await response.json();

        updateDashboard(data.state);

        addLog("Bot started.");

    } catch (error) {

        addLog("ERROR: " + error.message);
        $("startButton").disabled = false;
    }
}


async function stopBot() {
    try {
        const response = await fetch("/api/stop", {
            method: "POST"
        });

        if (!response.ok) {
            throw new Error("Could not stop bot");
        }

        const data = await response.json();

        updateDashboard(data.state);

        addLog("Bot stopped.");

    } catch (error) {

        addLog("ERROR: " + error.message);
    }
}


function updateDashboard(state) {

    $("profit").textContent =
        "$" + Number(state.profit || 0).toFixed(2);

    $("wins").textContent =
        state.wins || 0;

    $("losses").textContent =
        state.losses || 0;

    $("botStatus").textContent =
        state.status || "Ready";


    const indicator = $("connectionStatus");

    if (state.running) {

        indicator.textContent = "RUNNING";

        indicator.classList.remove("stopped");
        indicator.classList.add("running");

        $("startButton").disabled = true;
        $("stopButton").disabled = false;

    } else {

        indicator.textContent = "STOPPED";

        indicator.classList.remove("running");
        indicator.classList.add("stopped");

        $("startButton").disabled = false;
        $("stopButton").disabled = true;
    }
}


async function loadStatus() {

    try {

        const response = await fetch("/api/status");

        if (!response.ok) {
            throw new Error("Server unavailable");
        }

        const state = await response.json();

        updateDashboard(state);

    } catch (error) {

        $("connectionStatus").textContent = "OFFLINE";
        $("connectionStatus").className = "status stopped";
    }
}


loadStatus();

setInterval(loadStatus, 3000);
