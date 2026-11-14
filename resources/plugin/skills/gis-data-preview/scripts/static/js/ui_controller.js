/**
 * ui_controller.js — Sidebar UI, layer list management, tabbed attribute tables,
 *                    logging, and resizable panels.
 */
const UIController = (() => {
    // ---- DOM refs ----
    const layerListEl = document.getElementById("layer-list");
    const layerEmptyHint = document.getElementById("layer-empty-hint");
    const layerIdCounter = { value: 0 };

    const sidebar = document.getElementById("sidebar");
    const sidebarExpandBtn = document.getElementById("sidebar-expand-btn");
    const collapseBtn = document.getElementById("toggle-sidebar-btn");
    const attrDrawer = document.getElementById("attr-drawer");
    const attrTabs = document.getElementById("attr-tabs");
    const attrTabPanels = document.getElementById("attr-tab-panels");
    const attrEmpty = document.getElementById("attr-empty");

    // ---- Sidebar toggle ----
    collapseBtn.addEventListener("click", () => {
        sidebar.classList.add("collapsed");
        sidebarExpandBtn.classList.remove("hidden");
    });

    sidebarExpandBtn.addEventListener("click", () => {
        sidebar.classList.remove("collapsed");
        sidebarExpandBtn.classList.add("hidden");
    });

    // ---- Attribute drawer toggle ----
    const drawerToggle = document.getElementById("drawer-toggle");
    drawerToggle.addEventListener("click", () => {
        attrDrawer.classList.toggle("collapsed");
    });

    // ---- Clear log ----
    document.getElementById("clear-log-btn").addEventListener("click", () => {
        document.getElementById("log-content").innerHTML = "";
    });

    // =========================================================
    //  Layer list with up/down buttons (no drag-and-drop)
    // =========================================================

    function moveLayerInList(layerId, direction) {
        const group = layerListEl.querySelector(`.layer-group[data-layer-id="${layerId}"]`);
        if (!group) return;

        if (direction === "up") {
            const prev = group.previousElementSibling;
            if (prev && prev.classList.contains("layer-group")) {
                layerListEl.insertBefore(group, prev);
            }
        } else {
            const next = group.nextElementSibling;
            if (next && next.classList.contains("layer-group")) {
                layerListEl.insertBefore(next, group);
            }
        }

        // Sync map z-order to match sidebar list order
        MAP.reorderToSidebar();
    }

    // ---- Add layer item to sidebar ----
    function addLayerItem(layerId, layerName, renderer) {
        layerEmptyHint.style.display = "none";

        const style = MAP.parseStyle(renderer);
        const color = style.fillColor || style.color || "#ff0000";

        // Wrapper div: contains both the layer-item row and the legend
        const group = document.createElement("div");
        group.className = "layer-group";
        group.dataset.layerId = layerId;

        // Layer item row
        const li = document.createElement("div");
        li.className = "layer-item";

        li.innerHTML = `
            <input type="checkbox" checked title="显示/隐藏" />
            <span class="layer-color" style="background:${color}"></span>
            <span class="layer-name" title="${layerName}">${layerName}</span>
            <span class="layer-actions">
                <button class="layer-action-btn move-up-btn" title="上移">&#9650;</button>
                <button class="layer-action-btn move-down-btn" title="下移">&#9660;</button>
                <button class="layer-action-btn zoom-btn" title="缩放至图层">&#9733;</button>
                <button class="layer-action-btn remove-btn" title="移除图层">&#10005;</button>
            </span>
        `;

        // Checkbox: toggle visibility
        const checkbox = li.querySelector('input[type="checkbox"]');
        checkbox.addEventListener("change", () => {
            MAP.toggleLayer(layerId, checkbox.checked);
        });

        // Up button
        li.querySelector(".move-up-btn").addEventListener("click", (e) => {
            e.stopPropagation();
            moveLayerInList(layerId, "up");
        });

        // Down button
        li.querySelector(".move-down-btn").addEventListener("click", (e) => {
            e.stopPropagation();
            moveLayerInList(layerId, "down");
        });

        // Zoom button
        li.querySelector(".zoom-btn").addEventListener("click", (e) => {
            e.stopPropagation();
            MAP.zoomToLayer(layerId);
        });

        // Remove button
        li.querySelector(".remove-btn").addEventListener("click", (e) => {
            e.stopPropagation();
            MAP.removeLayer(layerId);
            group.remove();
            // Also close the tab if open
            closeTab(layerId);
            if (layerListEl.children.length === 0) {
                layerEmptyHint.style.display = "block";
            }
            addLog(`图层 "${layerName}" 已移除`, "warn");
        });

        // Click layer name -> open attribute table tab
        li.querySelector(".layer-name").addEventListener("click", (e) => {
            e.stopPropagation();
            openLayerTab(layerId);
            MAP.zoomToLayer(layerId);
        });

        group.appendChild(li);

        // Build legend and append into group
        buildLegend(layerId, renderer, layerName, group);

        // Insert at top (newest layer on top)
        layerListEl.prepend(group);
    }

    /**
     * Build legend DOM and append into the layer group.
     */
    function buildLegend(layerId, renderer, layerName, groupEl) {
        const old = groupEl.querySelector(".layer-legend");
        if (old) old.remove();

        let items = [];

        if (renderer.type === "simple") {
            const style = MAP.parseStyle(renderer);
            items.push({ color: style.fillColor || style.color, label: layerName });
        } else if (renderer.type === "unique") {
            const values = renderer.unique_values || {};
            for (const [val, cfg] of Object.entries(values)) {
                items.push({ color: cfg.color || "#ff0000", label: val });
            }
        } else if (renderer.type === "graduated") {
            const breaks = renderer.classification_breaks || [];
            for (const b of breaks) {
                const label = b.label || `${b.min} - ${b.max}`;
                items.push({ color: b.color || "#ff0000", label });
            }
        }

        if (items.length === 0) return;

        const div = document.createElement("div");
        div.className = "layer-legend";
        div.dataset.layerId = layerId;
        div.innerHTML = items
            .map((it) => `<div class="legend-item">
                <span class="legend-symbol" style="background:${it.color}"></span>
                <span class="legend-label">${it.label}</span>
            </div>`)
            .join("");

        groupEl.appendChild(div);
    }

    // =========================================================
    //  Tabbed Attribute Table
    // =========================================================

    // Track open tabs: layerId -> { name, panelEl }
    const openTabs = {};
    let activeTabId = null;

    /**
     * Open (or switch to) a layer's attribute table tab.
     */
    function openLayerTab(layerId) {
        const entry = MAP._layers[layerId];
        if (!entry) return;

        // If tab already exists, just activate it
        if (openTabs[layerId]) {
            activateTab(layerId);
            attrDrawer.classList.remove("collapsed");
            return;
        }

        const features = entry.geojson.features || [];
        if (features.length === 0) return;

        // Collect all property keys
        const keySet = new Set();
        for (const f of features) {
            for (const k of Object.keys(f.properties || {})) {
                if (!k.startsWith("_")) keySet.add(k);
            }
        }
        const keys = [...keySet];
        if (keys.length === 0) return;

        // Build tab element
        const tab = document.createElement("div");
        tab.className = "attr-tab";
        tab.dataset.layerId = layerId;
        tab.innerHTML = `<span class="tab-label">${entry.name}</span><span class="tab-close">&times;</span>`;

        tab.querySelector(".tab-label").addEventListener("click", () => {
            activateTab(layerId);
        });

        tab.querySelector(".tab-close").addEventListener("click", (e) => {
            e.stopPropagation();
            closeTab(layerId);
        });

        // Build panel content
        const panel = document.createElement("div");
        panel.className = "attr-tab-panel";
        panel.dataset.layerId = layerId;

        let tableHtml = `<table class="attr-table"><thead><tr>`;
        for (const k of keys) tableHtml += `<th>${k}</th>`;
        tableHtml += `</tr></thead><tbody>`;
        for (let fi = 0; fi < features.length; fi++) {
            tableHtml += `<tr data-feature-index="${fi}">`;
            for (const k of keys) {
                const v = (features[fi].properties || {})[k];
                tableHtml += `<td title="${v ?? ''}">${v ?? ''}</td>`;
            }
            tableHtml += `</tr>`;
        }
        tableHtml += `</tbody></table>`;
        panel.innerHTML = tableHtml;

        // Store
        openTabs[layerId] = { name: entry.name, panelEl: panel, tabEl: tab };

        // Add to DOM
        attrTabs.appendChild(tab);
        attrTabPanels.appendChild(panel);

        // Activate this tab
        activateTab(layerId);
        attrDrawer.classList.remove("collapsed");
        attrEmpty.style.display = "none";

        addLog(`已打开属性表: "${entry.name}"`, "info");
    }

    /**
     * Activate a tab (show its panel, highlight tab).
     */
    function activateTab(layerId) {
        activeTabId = layerId;

        // Deactivate all tabs
        attrTabs.querySelectorAll(".attr-tab").forEach((t) => t.classList.remove("active"));
        attrTabPanels.querySelectorAll(".attr-tab-panel").forEach((p) => p.classList.remove("active"));

        // Activate target
        const tab = openTabs[layerId];
        if (tab) {
            tab.tabEl.classList.add("active");
            tab.panelEl.classList.add("active");
        }
    }

    /**
     * Close a tab and remove its panel.
     */
    function closeTab(layerId) {
        const tab = openTabs[layerId];
        if (!tab) return;

        tab.tabEl.remove();
        tab.panelEl.remove();
        delete openTabs[layerId];

        // If the closed tab was active, activate the last remaining tab
        if (activeTabId === layerId) {
            const remaining = Object.keys(openTabs);
            if (remaining.length > 0) {
                activateTab(remaining[remaining.length - 1]);
            } else {
                activeTabId = null;
                attrDrawer.classList.add("collapsed");
                attrEmpty.style.display = "block";
            }
        }
    }

    /**
     * Highlight a specific feature row in a layer's attribute table tab.
     * Called from map feature click.
     */
    function highlightFeature(layerId, featureIndex) {
        // Open the tab if not already open
        if (!openTabs[layerId]) {
            openLayerTab(layerId);
        } else {
            activateTab(layerId);
            attrDrawer.classList.remove("collapsed");
        }

        // Clear previous highlight across all panels
        attrTabPanels.querySelectorAll(".attr-row-highlight").forEach((r) => {
            r.classList.remove("attr-row-highlight");
        });

        // Highlight the target row
        const panel = openTabs[layerId]?.panelEl;
        if (panel) {
            const row = panel.querySelector(`tr[data-feature-index="${featureIndex}"]`);
            if (row) {
                row.classList.add("attr-row-highlight");
                row.scrollIntoView({ behavior: "smooth", block: "nearest" });
            }
        }
    }

    // ---- Operation Log ----
    function addLog(message, level = "info") {
        const logContent = document.getElementById("log-content");
        const now = new Date();
        const timeStr = now.toLocaleTimeString("zh-CN", { hour12: false });

        const entry = document.createElement("div");
        entry.className = `log-entry ${level}`;
        entry.innerHTML = `<span class="log-time">[${timeStr}]</span>${message}`;

        logContent.appendChild(entry);
        logContent.scrollTop = logContent.scrollHeight;

        while (logContent.children.length > 200) {
            logContent.removeChild(logContent.firstChild);
        }
    }

    // ---- Next layer ID ----
    function nextLayerId() {
        layerIdCounter.value++;
        return `layer_${layerIdCounter.value}`;
    }

    // =========================================================
    //  Resizable panels
    // =========================================================
    function makeResizable(handle, target, dir, opts = {}) {
        const { min = 80, max = 800 } = opts;
        let startPos, startSize;

        function onStart(e) {
            e.preventDefault();
            startPos = dir === "col" ? e.clientX : e.clientY;
            startSize = dir === "col" ? target.offsetWidth : target.offsetHeight;
            handle.classList.add("active");
            document.body.classList.add(dir === "col" ? "resizing" : "resizing-row");
            document.addEventListener("mousemove", onMove);
            document.addEventListener("mouseup", onEnd);
        }

        function onMove(e) {
            const delta = (dir === "col" ? e.clientX : e.clientY) - startPos;
            let newSize = dir === "col" ? startSize + delta : startSize - delta;
            newSize = Math.max(min, Math.min(max, newSize));
            if (dir === "col") {
                target.style.width = newSize + "px";
            } else {
                target.style.height = newSize + "px";
            }
            if (typeof MAP !== "undefined") {
                MAP.map.invalidateSize({ animate: false });
            }
        }

        function onEnd() {
            handle.classList.remove("active");
            document.body.classList.remove("resizing", "resizing-row");
            document.removeEventListener("mousemove", onMove);
            document.removeEventListener("mouseup", onEnd);
        }

        handle.addEventListener("mousedown", onStart);
    }

    makeResizable(
        document.getElementById("resize-sidebar"),
        sidebar,
        "col",
        { min: 180, max: 500 }
    );

    const logPanel = document.getElementById("log-panel");
    makeResizable(
        document.getElementById("resize-log"),
        logPanel,
        "row",
        { min: 80, max: 500 }
    );

    makeResizable(
        document.getElementById("resize-drawer"),
        attrDrawer,
        "row",
        { min: 80, max: window.innerHeight * 0.7 }
    );

    return {
        addLayerItem,
        showAttributes: highlightFeature,
        showLayerAttributes: openLayerTab,
        addLog,
        nextLayerId,
        closeTab,
    };
})();
