/**
 * map_core.js — Leaflet map initialization, tile layers, GeoJSON rendering.
 *
 * Exports (global): MAP, addGeoJSONLayer(layerId, geojson, renderer), zoomToLayer(layerId)
 */
const MAP = (() => {
    // ---- ArcGIS tile layers (WGS 1984) ----
    const vecTile = L.tileLayer(                                                                                          
      "https://services.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",               
      { maxZoom: 18, attribution: "&copy; Esri" }                                                                       
    );

    const imgTile = L.tileLayer(
      "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      { maxZoom: 18, attribution: "&copy; Esri" }
    );

    const labelTile = L.tileLayer(
      "https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
      { maxZoom: 18, opacity: 0.7, attribution: "" }
    );

    // ---- Map init ----
    const map = L.map("map", {
        center: [35.86, 104.20],
        zoom: 4,
        zoomControl: true,
        layers: [vecTile],
    });

    // Scale bar (top-left to avoid overlapping with bottom attribute table)
    L.control.scale({ imperial: false, position: "topleft" }).addTo(map);

    // Coordinate display on mouse move
    map.on("mousemove", (e) => {
        const el = document.getElementById("coord-display");
        if (el) {
            el.textContent = `经度: ${e.latlng.lng.toFixed(6)}  纬度: ${e.latlng.lat.toFixed(6)}`;
        }
    });

    // ---- Base map switching ----
    let currentBase = "vec";
    document.querySelectorAll(".basemap-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
            const target = btn.dataset.basemap;
            if (target === currentBase) return;
            currentBase = target;

            // Remove current base layers
            map.removeLayer(vecTile);
            map.removeLayer(imgTile);
            map.removeLayer(labelTile);

            if (target === "vec") {
                map.addLayer(vecTile);
            } else {
                map.addLayer(imgTile);
                map.addLayer(labelTile);
            }

            // Toggle active class
            document.querySelectorAll(".basemap-btn").forEach((b) => b.classList.remove("active"));
            btn.classList.add("active");
        });
    });

    // ---- Layer storage ----
    const layers = {}; // layerId -> { name, leafletLayer, renderer, geojson, visible }

    /**
     * Parse renderer config into Leaflet style.
     */
    function parseStyle(renderer) {
        if (!renderer || !renderer.symbol) return {};
        const s = renderer.symbol;
        const style = {
            color: s.color || "#ff0000",
            weight: s.weight ?? 2,
            opacity: s.opacity ?? 1.0,
            fillColor: s.fillColor || s.color || "#ff0000",
            fillOpacity: s.fillOpacity ?? 0.6,
            radius: s.radius ?? 5,
        };
        return style;
    }

    /**
     * Parse renderer config into Leaflet pointToLayer.
     */
    function makePointToLayer(style) {
        return (feature, latlng) => {
            return L.circleMarker(latlng, style);
        };
    }

    /**
     * Build onEachFeature: popup + highlight + click-to-attr-table.
     */
    function makeOnEachFeature(layerId, layerName, featureIndex) {
        return (feature, layer) => {
            // Popup
            const props = feature.properties || {};
            let html = `<strong>${layerName}</strong>`;
            for (const [k, v] of Object.entries(props)) {
                if (k.startsWith("_")) continue;
                html += `<br/><b>${k}:</b> ${v}`;
            }
            layer.bindPopup(html);

            // Hover highlight
            layer.on("mouseover", () => {
                if (layer.setStyle) layer.setStyle({ weight: 4 });
            });
            layer.on("mouseout", () => {
                if (layers[layerId]) {
                    const baseStyle = parseStyle(layers[layerId].renderer);
                    layer.setStyle(baseStyle);
                }
            });

            // Click -> highlight row in attribute table
            layer.on("click", () => {
                if (typeof UIController !== "undefined") {
                    UIController.showAttributes(layerId, featureIndex);
                }
            });
        };
    }

    /**
     * Build style function for graduated renderer.
     */
    function makeGraduatedStyle(renderer) {
        const breaks = renderer.classification_breaks || [];
        const field = renderer.field;
        const base = parseStyle(renderer);

        return (feature) => {
            const val = (feature.properties || {})[field];
            for (let i = breaks.length - 1; i >= 0; i--) {
                const b = breaks[i];
                if (val !== undefined && val <= b.max) {
                    return {
                        ...base,
                        fillColor: b.color || base.fillColor,
                        color: b.color || base.color,
                    };
                }
            }
            return base;
        };
    }

    /**
     * Build style function for unique value renderer.
     */
    function makeUniqueStyle(renderer) {
        const values = renderer.unique_values || {};
        const field = renderer.field;
        const base = parseStyle(renderer);

        return (feature) => {
            const val = String((feature.properties || {})[field] ?? "");
            const override = values[val];
            if (override) {
                return {
                    ...base,
                    fillColor: override.color || base.fillColor,
                    color: override.color || base.color,
                    radius: override.radius ?? base.radius,
                };
            }
            return base;
        };
    }

    /**
     * Add a GeoJSON layer to the map.
     * @param {string} layerId - unique identifier
     * @param {object} geojson - GeoJSON FeatureCollection
     * @param {object} renderer - renderer config from _renderer
     */
    function addLayer(layerId, geojson, renderer, layerName) {
        // Remove existing layer with same ID (refresh)
        if (layers[layerId]) {
            map.removeLayer(layers[layerId].leafletLayer);
        }

        const baseStyle = parseStyle(renderer);

        let styleFn = baseStyle;
        let pointToLayerFn = makePointToLayer(baseStyle);

        if (renderer.type === "graduated" && renderer.field) {
            styleFn = makeGraduatedStyle(renderer);
            pointToLayerFn = makePointToLayer(styleFn);
        } else if (renderer.type === "unique" && renderer.field) {
            styleFn = makeUniqueStyle(renderer);
            pointToLayerFn = makePointToLayer(styleFn);
        }

        const features = geojson.features || [];

        const leafletLayer = L.geoJSON(geojson, {
            style: renderer.type === "graduated" || renderer.type === "unique"
                ? styleFn
                : baseStyle,
            pointToLayer: pointToLayerFn,
            onEachFeature: (feature, layer) => {
                let idx = 0;
                for (let i = 0; i < features.length; i++) {
                    if (features[i] === feature) { idx = i; break; }
                }
                makeOnEachFeature(layerId, layerName, idx)(feature, layer);
            },
        });

        leafletLayer.addTo(map);

        layers[layerId] = {
            name: layerName,
            leafletLayer,
            renderer,
            geojson,
            visible: true,
        };

        return layers[layerId];
    }

    /**
     * Zoom to the bounding box of a layer.
     */
    function zoomToLayer(layerId) {
        const entry = layers[layerId];
        if (!entry) return;
        const bounds = entry.leafletLayer.getBounds();
        if (bounds.isValid()) {
            map.fitBounds(bounds, { padding: [30, 30], maxZoom: 16 });
        }
    }

    /**
     * Toggle layer visibility.
     */
    function toggleLayer(layerId, visible) {
        const entry = layers[layerId];
        if (!entry) return;
        if (visible) {
            if (!map.hasLayer(entry.leafletLayer)) {
                entry.leafletLayer.addTo(map);
            }
            entry.visible = true;
        } else {
            map.removeLayer(entry.leafletLayer);
            entry.visible = false;
        }
    }

    /**
     * Remove a layer from the map and storage.
     */
    function removeLayer(layerId) {
        const entry = layers[layerId];
        if (!entry) return;
        map.removeLayer(entry.leafletLayer);
        delete layers[layerId];
    }

    /**
     * Get all registered layers (ordered by insertion).
     */
    function getAllLayers() {
        return Object.entries(layers);
    }

    /**
     * Re-order map layers to match sidebar list order.
     * Top of sidebar = front of map.
     */
    function reorderToSidebar() {
        const groups = document.querySelectorAll("#layer-list .layer-group");
        for (let i = groups.length - 1; i >= 0; i--) {
            const id = groups[i].dataset.layerId;
            const entry = layers[id];
            if (entry && entry.visible) {
                entry.leafletLayer.bringToFront();
            }
        }
    }

    return {
        map,
        addLayer,
        zoomToLayer,
        toggleLayer,
        removeLayer,
        getAllLayers,
        reorderToSidebar,
        parseStyle,
        _layers: layers,
    };
})();
