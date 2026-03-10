(function () {
    class GatewayClient {
        constructor(options) {
            this.wsUrl = options.wsUrl;
            this.reconnectMs = options.reconnectMs || 1500;

            this.ws = null;
            this.reconnectTimer = null;

            this.onOpen = null;
            this.onClose = null;
            this.onError = null;
            this.onEvent = null;
        }

        connect() {
            this.ws = new WebSocket(this.wsUrl);

            this.ws.onopen = () => {
                if (typeof this.onOpen === "function") {
                    this.onOpen();
                }

                this.send({ gateway: "subscribe" });
            };

            this.ws.onmessage = (event) => {
                let msg;

                try {
                    msg = JSON.parse(event.data);
                } catch (error) {
                    console.error("Failed to parse JSON:", error, event.data);
                    return;
                }

                if (typeof this.onEvent === "function") {
                    this.onEvent(msg);
                }
            };

            this.ws.onerror = (error) => {
                if (typeof this.onError === "function") {
                    this.onError(error);
                }
            };

            this.ws.onclose = () => {
                if (typeof this.onClose === "function") {
                    this.onClose();
                }

                this.reconnectTimer = setTimeout(() => {
                    this.connect();
                }, this.reconnectMs);
            };
        }

        send(payload) {
            if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
                return false;
            }

            this.ws.send(JSON.stringify(payload));
            return true;
        }

        requestRefresh() {
            return this.send({ gateway: "get" });
        }
    }

    window.GatewayClient = GatewayClient;
})();
