/**
 * websocket.js — WebSocket connection manager, reconnects, dispatches data to map & UI.
 */
(function () {
    const WS_URL = `ws://${window.location.host}/ws`;
    const wsStatusEl = document.getElementById("ws-status");

    let ws = null;
    let reconnectTimer = null;
    let reconnectDelay = 1000;
    const MAX_RECONNECT_DELAY = 30000;

    function setWsStatus(state) {
        const dot = wsStatusEl.querySelector(".status-dot");
        dot.className = "status-dot " + state;
        const labels = { connected: "已连接", disconnected: "未连接", connecting: "连接中..." };
        wsStatusEl.lastChild.textContent = labels[state] || state;
    }

    function connect() {
        if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;

        setWsStatus("connecting");
        ws = new WebSocket(WS_URL);

        ws.onopen = () => {
            setWsStatus("connected");
            reconnectDelay = 1000;
            UIController.addLog("WebSocket 已连接", "success");
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);

                // Ignore pong
                if (data === "pong") return;

                // Check if this is a valid GeoJSON payload
                if (data.type === "FeatureCollection" && data._layer_name) {
                    handleGeoJSONMessage(data);
                }
            } catch (err) {
                // Not JSON or parse error, ignore
            }
        };

        ws.onclose = () => {
            setWsStatus("disconnected");
            UIController.addLog("WebSocket 连接断开，尝试重连...", "warn");
            scheduleReconnect();
        };

        ws.onerror = () => {
            // onclose will fire after onerror
        };
    }

    function scheduleReconnect() {
        if (reconnectTimer) clearTimeout(reconnectTimer);
        reconnectTimer = setTimeout(() => {
            UIController.addLog(`正在重连 WebSocket (${(reconnectDelay / 1000).toFixed(0)}s)...`, "info");
            connect();
            reconnectDelay = Math.min(reconnectDelay * 1.5, MAX_RECONNECT_DELAY);
        }, reconnectDelay);
    }

    /**
     * Handle an incoming GeoJSON + metadata payload.
     */
    function handleGeoJSONMessage(data) {
        const layerName = data._layer_name || "未命名图层";
        const renderer = data._renderer || { type: "simple", symbol: {} };

        UIController.addLog(`收到图层数据: "${layerName}" (${(data.features || []).length} 个要素)`, "info");

        // Strip metadata fields from the GeoJSON
        const geojson = { ...data };
        delete geojson._layer_name;
        delete geojson._renderer;

        // Create unique ID for this layer
        const layerId = UIController.nextLayerId();

        // Render on map (pass layerName explicitly)
        MAP.addLayer(layerId, geojson, renderer, layerName);

        // Add to sidebar
        UIController.addLayerItem(layerId, layerName, renderer);

        // Auto-zoom to the new layer
        MAP.zoomToLayer(layerId);

        UIController.addLog(`图层 "${layerName}" 已加载到地图`, "success");
    }

    // Ping to keep alive
    function startPing() {
        setInterval(() => {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send("ping");
            }
        }, 30000);
    }

    // Start connection on page load
    connect();
    startPing();
})();
