(function () {
    const config = window.SWM_RUNTIME_CONFIG;

    const matrixRoot = document.getElementById("matrix-root");
    const wsState = document.getElementById("ws-state");
    const wsUri = document.getElementById("ws-uri");
    const eventState = document.getElementById("event-state");
    const activeCount = document.getElementById("active-count");
    const activeList = document.getElementById("active-list");
    const refreshBtn = document.getElementById("refresh-btn");

    wsUri.textContent = config.wsUrl;

    function setGatewayState(text, isConnected) {
        wsState.textContent = text;
        wsState.classList.toggle("connected", isConnected);
        wsState.classList.toggle("disconnected", !isConnected);
    }

    function extractPinsFromMessage(msg) {
        if (!msg || typeof msg !== "object") {
            return null;
        }

        if (
            (msg.event === "pinstat_snapshot" ||
             msg.event === "pinstat_update" ||
             msg.event === "get") &&
            msg.data &&
            Array.isArray(msg.data.pins)
        ) {
            return msg.data.pins;
        }

        if (
            msg.ok === 1 &&
            msg.cmd === "PINSTAT" &&
            msg.which === "ALL" &&
            Array.isArray(msg.pins)
        ) {
            return msg.pins;
        }

        return null;
    }

    const matrixView = new window.MatrixView(matrixRoot, {
        matrixSize: config.matrixSize,
    });

    matrixView.build();

    const gateway = new window.GatewayClient({
        wsUrl: config.wsUrl,
        reconnectMs: config.reconnectMs,
    });

    gateway.onOpen = () => {
        setGatewayState("Connected", true);
    };

    gateway.onClose = () => {
        setGatewayState("Disconnected", false);
    };

    gateway.onError = (error) => {
        console.error("WebSocket error:", error);
        setGatewayState("Error", false);
    };

    gateway.onEvent = (msg) => {
        if (typeof msg.event === "string") {
            eventState.textContent = msg.event;
        }

        const pins = extractPinsFromMessage(msg);

        if (pins) {
            const activePins = matrixView.renderPins(pins);
            const labels = matrixView.activePinsToLabels(activePins);

            activeCount.textContent = String(activePins.length);
            activeList.textContent = labels.length > 0 ? labels.join(" ") : "(none)";
        }
    };

    refreshBtn.addEventListener("click", () => {
        gateway.requestRefresh();
    });

    gateway.connect();
})();
