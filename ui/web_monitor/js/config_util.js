(function () {
    function getSearchParam(name) {
        const params = new URLSearchParams(window.location.search);
        return params.get(name);
    }

    function getConfig() {
        const base = window.SWM_CONFIG || {};

        return {
            matrixSize: Number(base.matrixSize || 16),
            reconnectMs: Number(base.reconnectMs || 1500),
            wsUrl: getSearchParam("ws") || base.wsUrl || "ws://swmgate:8765",
        };
    }

    window.SWM_RUNTIME_CONFIG = getConfig();
})();
