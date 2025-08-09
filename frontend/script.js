// script-production.js - Updated Frontend for Production API v2.0
document.addEventListener('DOMContentLoaded', () => {
    let map;
    let vendorLayerGroup = L.featureGroup();
    let polygonLayerGroup = L.featureGroup();
    let coverageGridLayerGroup = L.featureGroup();
    let heatmapLayer;
    let tempLocationMarker = null;
    let currentHeatmapType = 'none';
    let showVendorRadius = true;
    let vendorsAreVisible = true;
    let currentRadiusModifier = 1.0;
    let currentRadiusMode = 'percentage';
    let currentRadiusFixed = 3.0;
    let marketingAreasOnTop = false;
    let currentZoomLevel = 11;
    let currentPage = 1;
    let totalPages = 1;
    let isLoading = false;

    // Production API endpoints
    const API_BASE_URL = '/api/v2';
    const LEGACY_API_URL = '/api'; // Fallback for backward compatibility
    
    // Enhanced error handling and retry logic
    const API_CONFIG = {
        timeout: 30000,
        retries: 3,
        retryDelay: 1000
    };

    // DOM Elements (keeping existing structure)
    const bodyEl = document.body;
    const daterangeStartEl = document.getElementById('daterange-start');
    const daterangeEndEl = document.getElementById('daterange-end');
    const cityEl = document.getElementById('city');
    const areaMainTypeEl = document.getElementById('area-main-type');
    const applyFiltersBtn = document.getElementById('apply-filters-btn');
    let globalLoadingOverlayEl = document.getElementById('map-loading-overlay-wrapper');

    // Enhanced API call function with retry logic
    async function apiCall(endpoint, options = {}) {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), API_CONFIG.timeout);
        
        let lastError = null;
        
        for (let attempt = 1; attempt <= API_CONFIG.retries; attempt++) {
            try {
                const response = await fetch(endpoint, {
                    ...options,
                    signal: controller.signal,
                    headers: {
                        'Content-Type': 'application/json',
                        ...options.headers
                    }
                });
                
                clearTimeout(timeoutId);
                
                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({
                        error: `HTTP ${response.status}`,
                        details: response.statusText
                    }));
                    throw new Error(`API Error: ${errorData.error || response.statusText}`);
                }
                
                return await response.json();
                
            } catch (error) {
                lastError = error;
                console.warn(`API call attempt ${attempt}/${API_CONFIG.retries} failed:`, error.message);
                
                if (attempt < API_CONFIG.retries && !controller.signal.aborted) {
                    await new Promise(resolve => setTimeout(resolve, API_CONFIG.retryDelay * attempt));
                } else {
                    clearTimeout(timeoutId);
                }
            }
        }
        
        throw lastError;
    }

    // Enhanced initialization with health check
    async function init() {
        try {
            showLoading(true, 'Checking system health...');
            
            // Check API health first
            const healthStatus = await checkSystemHealth();
            if (!healthStatus.healthy) {
                throw new Error(`System not ready: ${healthStatus.issues.join(', ')}`);
            }
            
            initMap();
            
            showLoading(true, 'Loading configuration...');
            await fetchInitialFilterData();
            
            populateCitySelect();
            initializeCustomDropdowns();
            applyDefaultFilters();
            setupEventListeners();
            setupHeatmapZoomHandler();
            
            // Set default dates
            const today = new Date();
            const thirtyDaysAgo = new Date(new Date().setDate(today.getDate() - 30));
            daterangeStartEl.value = thirtyDaysAgo.toISOString().split('T')[0];
            daterangeEndEl.value = today.toISOString().split('T')[0];
            
            // Initialize UI components
            initializeUIComponents();
            
            showLoading(true, 'Loading map data...');
            await fetchAndDisplayMapData();
            
            showLoading(false);
            
            // Show success notification
            showNotification('Dashboard loaded successfully!', 'success');
            
        } catch (error) {
            console.error("Initialization failed:", error);
            showLoading(true, `Initialization failed: ${error.message}. Please refresh.`);
            showNotification(`Failed to load dashboard: ${error.message}`, 'error');
        }
    }

    // System health check
    async function checkSystemHealth() {
        try {
            const health = await apiCall(`${API_BASE_URL}/health`);
            
            const issues = [];
            if (health.services?.database !== 'healthy') {
                issues.push('Database connection');
            }
            if (health.services?.cache !== 'healthy') {
                issues.push('Cache connection');
            }
            
            return {
                healthy: issues.length === 0,
                issues: issues,
                status: health
            };
        } catch (error) {
            console.error('Health check failed:', error);
            return {
                healthy: false,
                issues: ['API not responding'],
                status: null
            };
        }
    }

    // Enhanced initial data fetching
    async function fetchInitialFilterData() {
        try {
            const data = await apiCall(`${API_BASE_URL}/initial-data`);
            window.initialFilterData = data;
            return data;
        } catch (error) {
            console.error("Failed to fetch initial data:", error);
            // Fallback to legacy API
            try {
                const fallbackData = await apiCall(`${LEGACY_API_URL}/initial-data`);
                window.initialFilterData = fallbackData;
                return fallbackData;
            } catch (fallbackError) {
                throw new Error(`Failed to load configuration: ${error.message}`);
            }
        }
    }

    // Enhanced map data fetching with pagination
    async function fetchAndDisplayMapData() {
        if (isLoading) return;
        
        isLoading = true;
        applyFiltersBtn.disabled = true;
        
        try {
            // Clear temporary marker
            if (tempLocationMarker) {
                map.removeLayer(tempLocationMarker);
                tempLocationMarker = null;
            }

            const params = buildApiParams();
            
            showLoading(true, 'Fetching map data...');
            
            const data = await apiCall(`${API_BASE_URL}/map-data?${params.toString()}`);
            
            // Update pagination info
            if (data.pagination) {
                currentPage = data.pagination.page;
                totalPages = data.pagination.total_pages;
                updatePaginationUI(data.pagination);
            }
            
            // Update map layers
            updateMapLayers(data);
            
            // Update metadata display
            updateMetadataDisplay(data.metadata);
            
            showLoading(false);
            showNotification(`Loaded ${data.vendors?.length || 0} vendors`, 'info');
            
        } catch (error) {
            console.error("Map data fetch failed:", error);
            showLoading(true, `Error: ${error.message}. Please try again.`);
            showNotification(`Failed to load map data: ${error.message}`, 'error');
        } finally {
            isLoading = false;
            applyFiltersBtn.disabled = false;
        }
    }

    // Build API parameters from UI
    function buildApiParams() {
        const params = new URLSearchParams();
        
        // Basic filters
        params.append('city', cityEl.value);
        params.append('start_date', daterangeStartEl.value);
        params.append('end_date', daterangeEndEl.value);
        params.append('zoom_level', map.getZoom().toString());
        params.append('heatmap_type_request', currentHeatmapType);
        params.append('area_type_display', areaMainTypeEl.value);
        params.append('page', currentPage.toString());
        params.append('page_size', '1000');
        
        // Business lines
        const selectedBLs = getSelectedValuesFromCustomDropdown(customFilterConfigs.businessLine);
        selectedBLs.forEach(bl => params.append('business_lines', bl));
        
        // Vendor codes
        const vendorCodesText = document.getElementById('vendor-codes-filter')?.value?.trim();
        if (vendorCodesText) {
            params.append('vendor_codes_filter', vendorCodesText);
        }
        
        // Other filters (add as needed)
        const selectedAreaSubTypes = getSelectedValuesFromCustomDropdown(customFilterConfigs.areaSubType);
        selectedAreaSubTypes.forEach(st => params.append('area_sub_type_filter', st));
        
        return params;
    }

    // Update map layers with new data
    function updateMapLayers(data) {
        // Clear existing layers
        vendorLayerGroup.clearLayers();
        polygonLayerGroup.clearLayers();
        coverageGridLayerGroup.clearLayers();
        
        if (heatmapLayer) {
            map.removeLayer(heatmapLayer);
            heatmapLayer = null;
        }
        
        // Add vendors
        if (data.vendors && vendorsAreVisible) {
            addVendorsToMap(data.vendors);
        }
        
        // Add polygons
        if (data.polygons && data.polygons.features) {
            addPolygonsToMap(data.polygons);
        }
        
        // Add heatmap
        if (data.heatmap_data && data.heatmap_data.length > 0) {
            addHeatmapToMap(data.heatmap_data);
        }
        
        // Add coverage grid
        if (data.coverage_grid && data.coverage_grid.length > 0) {
            addCoverageGridToMap(data.coverage_grid);
        }
        
        // Adjust map view
        adjustMapView();
    }

    // Enhanced vendor rendering
    function addVendorsToMap(vendors) {
        vendors.forEach(vendor => {
            if (vendor.latitude == null || vendor.longitude == null) return;
            
            const popupContent = `
                <div class="vendor-popup">
                    <h4>${vendor.vendor_name || 'N/A'}</h4>
                    <div class="vendor-details">
                        <p><strong>Code:</strong> ${vendor.vendor_code || 'N/A'}</p>
                        <p><strong>Status:</strong> ${vendor.status_id !== null ? vendor.status_id : 'N/A'}</p>
                        <p><strong>Grade:</strong> ${vendor.grade || 'N/A'}</p>
                        <p><strong>Visible:</strong> ${vendor.visible ? 'Yes' : 'No'}</p>
                        <p><strong>Open:</strong> ${vendor.open ? 'Yes' : 'No'}</p>
                        <p><strong>Radius:</strong> ${vendor.radius ? vendor.radius.toFixed(2) + ' km' : 'N/A'}</p>
                    </div>
                </div>
            `;
            
            const marker = L.marker([vendor.latitude, vendor.longitude], {
                icon: getVendorIcon(vendor)
            }).bindPopup(popupContent);
            
            vendorLayerGroup.addLayer(marker);
            
            // Add radius circle if enabled
            if (showVendorRadius && vendor.radius > 0) {
                const circle = L.circle([vendor.latitude, vendor.longitude], {
                    radius: vendor.radius * 1000,
                    color: document.getElementById('radius-edge-color')?.value || '#E57373',
                    fillColor: document.getElementById('radius-inner-none')?.checked ? 
                        'transparent' : (document.getElementById('radius-inner-color')?.value || '#FFCDD2'),
                    fillOpacity: document.getElementById('radius-inner-none')?.checked ? 0 : 0.25,
                    weight: 1.5,
                    pane: 'shadowPane'
                });
                vendorLayerGroup.addLayer(circle);
            }
        });
    }

    // Get vendor icon based on properties
    function getVendorIcon(vendor) {
        const baseSize = parseInt(document.getElementById('vendor-marker-size')?.value || 12);
        const aspectRatio = 41/25;
        const iconWidth = baseSize;
        const iconHeight = Math.round(iconWidth * aspectRatio);
        
        // Color based on status or grade
        let iconUrl = 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon.png';
        
        if (vendor.grade === 'A+') {
            iconUrl = 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-green.png';
        } else if (vendor.grade === 'A') {
            iconUrl = 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-blue.png';
        } else if (!vendor.visible || !vendor.open) {
            iconUrl = 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-red.png';
        }
        
        return L.icon({
            iconUrl: iconUrl,
            iconRetinaUrl: iconUrl,
            shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
            iconSize: [iconWidth, iconHeight],
            iconAnchor: [iconWidth / 2, iconHeight],
            popupAnchor: [0, -iconHeight + 5],
            shadowSize: [iconWidth * 1.5, iconHeight * 1.5]
        });
    }

    // Enhanced heatmap rendering
    function addHeatmapToMap(heatmapData) {
        if (!heatmapData || heatmapData.length === 0) return;
        
        const validData = heatmapData.filter(p => 
            p.lat != null && p.lng != null && p.value != null && 
            !isNaN(p.lat) && !isNaN(p.lng) && !isNaN(p.value) && p.value > 0
        );
        
        if (validData.length === 0) return;
        
        const heatPoints = validData.map(p => [p.lat, p.lng, p.value / 100]);
        
        const heatOptions = {
            radius: getOptimalHeatmapRadius(),
            blur: parseInt(document.getElementById('heatmap-blur')?.value || 15),
            max: parseFloat(document.getElementById('heatmap-max-val')?.value || 1.0),
            minOpacity: 0.3,
            gradient: getHeatmapGradient(currentHeatmapType)
        };
        
        heatmapLayer = L.heatLayer(heatPoints, heatOptions).addTo(map);
        
        // Make heatmap non-interactive
        if (heatmapLayer.getPane) {
            heatmapLayer.getPane().style.pointerEvents = 'none';
        }
        
        console.log(`Rendered heatmap: ${validData.length} points`);
    }

    // Get optimal heatmap radius based on zoom
    function getOptimalHeatmapRadius() {
        const baseRadius = parseInt(document.getElementById('heatmap-radius')?.value || 25);
        const zoomLevel = map.getZoom();
        
        // Auto-optimize based on zoom level
        if (document.getElementById('heatmap-auto-optimize')?.classList.contains('active')) {
            let multiplier = 1.0;
            if (zoomLevel <= 10) multiplier = 1.8;
            else if (zoomLevel <= 12) multiplier = 1.4;
            else if (zoomLevel >= 16) multiplier = 0.7;
            else if (zoomLevel >= 14) multiplier = 0.85;
            
            return Math.round(baseRadius * multiplier);
        }
        
        return baseRadius;
    }

    // Get heatmap gradient based on type
    function getHeatmapGradient(type) {
        switch (type) {
            case 'order_density':
                return {
                    0.0: 'rgba(0, 0, 255, 0)',
                    0.15: 'rgba(0, 100, 255, 0.4)',
                    0.3: 'rgba(0, 200, 255, 0.6)',
                    0.5: 'rgba(0, 255, 100, 0.8)',
                    0.7: 'rgba(255, 255, 0, 0.9)',
                    1.0: 'rgba(255, 0, 0, 1)'
                };
            case 'order_density_organic':
                return {
                    0.0: 'rgba(0, 128, 0, 0)',
                    0.2: 'rgba(0, 200, 0, 0.5)',
                    0.4: 'rgba(100, 255, 0, 0.7)',
                    0.6: 'rgba(200, 255, 0, 0.8)',
                    0.8: 'rgba(255, 200, 0, 0.9)',
                    1.0: 'rgba(255, 100, 0, 1)'
                };
            case 'user_density':
                return {
                    0.0: 'rgba(75, 0, 130, 0)',
                    0.2: 'rgba(100, 50, 200, 0.5)',
                    0.4: 'rgba(150, 100, 255, 0.7)',
                    0.6: 'rgba(200, 150, 255, 0.8)',
                    0.8: 'rgba(255, 200, 150, 0.9)',
                    1.0: 'rgba(255, 100, 0, 1)'
                };
            default:
                return {
                    0.0: 'rgba(0, 0, 255, 0)',
                    0.25: 'rgba(0, 255, 255, 0.6)',
                    0.5: 'rgba(0, 255, 0, 0.8)',
                    0.75: 'rgba(255, 255, 0, 0.9)',
                    1.0: 'rgba(255, 0, 0, 1)'
                };
        }
    }

    // Pagination UI update
    function updatePaginationUI(pagination) {
        // Create pagination controls if they don't exist
        let paginationContainer = document.getElementById('pagination-controls');
        if (!paginationContainer) {
            paginationContainer = document.createElement('div');
            paginationContainer.id = 'pagination-controls';
            paginationContainer.className = 'pagination-controls';
            
            // Insert after the map
            const mapContainer = document.getElementById('map');
            mapContainer.parentNode.insertBefore(paginationContainer, mapContainer.nextSibling);
        }
        
        // Update pagination info
        paginationContainer.innerHTML = `
            <div class="pagination-info">
                <span>Page ${pagination.page} of ${pagination.total_pages}</span>
                <span>${pagination.total_vendors} total vendors</span>
            </div>
            <div class="pagination-buttons">
                <button ${pagination.page <= 1 ? 'disabled' : ''} onclick="changePage(${pagination.page - 1})">Previous</button>
                <button ${!pagination.has_next ? 'disabled' : ''} onclick="changePage(${pagination.page + 1})">Next</button>
            </div>
        `;
    }

    // Change page function
    window.changePage = function(newPage) {
        if (newPage < 1 || newPage > totalPages || isLoading) return;
        currentPage = newPage;
        fetchAndDisplayMapData();
    };

    // Metadata display update
    function updateMetadataDisplay(metadata) {
        let metadataContainer = document.getElementById('metadata-display');
        if (!metadataContainer) {
            metadataContainer = document.createElement('div');
            metadataContainer.id = 'metadata-display';
            metadataContainer.className = 'metadata-display';
            
            // Insert in sidebar or create a dedicated area
            const sidebar = document.querySelector('.sidebar-filters');
            if (sidebar) {
                sidebar.appendChild(metadataContainer);
            }
        }
        
        metadataContainer.innerHTML = `
            <h4>Data Summary</h4>
            <div class="metadata-item">
                <span>Orders:</span> <strong>${metadata.order_count?.toLocaleString() || 0}</strong>
            </div>
            <div class="metadata-item">
                <span>Vendors:</span> <strong>${metadata.vendor_count?.toLocaleString() || 0}</strong>
            </div>
            <div class="metadata-item">
                <span>Generated:</span> <small>${new Date(metadata.generated_at).toLocaleString()}</small>
            </div>
        `;
    }

    // Enhanced notification system
    function showNotification(message, type = 'info') {
        const notification = document.createElement('div');
        notification.className = `notification notification-${type}`;
        notification.innerHTML = `
            <span>${message}</span>
            <button onclick="this.parentElement.remove()">×</button>
        `;
        
        // Style the notification
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 12px 16px;
            background: ${type === 'error' ? '#f44336' : type === 'success' ? '#4caf50' : '#2196f3'};
            color: white;
            border-radius: 4px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.2);
            z-index: 10000;
            display: flex;
            align-items: center;
            gap: 10px;
            max-width: 300px;
        `;
        
        document.body.appendChild(notification);
        
        // Auto-remove after 5 seconds
        setTimeout(() => {
            if (notification.parentElement) {
                notification.remove();
            }
        }, 5000);
    }

    // Admin functions for production monitoring
    async function refreshData() {
        try {
            showLoading(true, 'Triggering data refresh...');
            const result = await apiCall(`${API_BASE_URL}/admin/refresh-data`, { method: 'POST' });
            showNotification(`Data refresh triggered: ${result.task_id}`, 'success');
        } catch (error) {
            showNotification(`Failed to trigger refresh: ${error.message}`, 'error');
        } finally {
            showLoading(false);
        }
    }

    async function warmCache() {
        try {
            showLoading(true, 'Warming cache...');
            const result = await apiCall(`${API_BASE_URL}/admin/warm-cache`, { method: 'POST' });
            showNotification('Cache warming triggered', 'success');
        } catch (error) {
            showNotification(`Failed to warm cache: ${error.message}`, 'error');
        } finally {
            showLoading(false);
        }
    }

    // Expose admin functions globally for console access
    window.dashboardAdmin = {
        refreshData,
        warmCache,
        checkHealth: checkSystemHealth,
        clearCache: async () => {
            try {
                await apiCall(`${API_BASE_URL}/admin/cache`, { method: 'DELETE' });
                showNotification('Cache cleared', 'success');
            } catch (error) {
                showNotification(`Failed to clear cache: ${error.message}`, 'error');
            }
        }
    };

    // Keep existing functions but ensure they work with new API
    // [Previous functions like initMap, setupEventListeners, etc. remain the same]
    // Just update any API calls to use the new apiCall function and endpoints

    function initMap() {
        const mapContainer = document.getElementById('map');
        if (mapContainer) mapContainer.innerHTML = '';
        
        map = L.map('map', { 
            preferCanvas: true,
            attributionControl: false 
        }).setView([35.7219, 51.3347], 11);
        
        // Create panes for layer ordering
        map.createPane('polygonPane');
        map.getPane('polygonPane').style.zIndex = 450;
        
        map.createPane('coverageGridPane');
        map.getPane('coverageGridPane').style.zIndex = 460;
        
        map.getPane('shadowPane').style.zIndex = 250;
        
        L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
            attribution: '© <a href="https://www.openstreetmap.org/copyright">OSM</a> © <a href="https://carto.com/attributions">CARTO</a>',
            subdomains: 'abcd',
            maxZoom: 20
        }).addTo(map);
        
        L.control.attribution({position: 'bottomleft'}).addTo(map);
        
        if (vendorsAreVisible) vendorLayerGroup.addTo(map);
        polygonLayerGroup.addTo(map);
        coverageGridLayerGroup.addTo(map);
    }

    function setupHeatmapZoomHandler() {
        let zoomTimeout;
        
        map.on('zoomend', () => {
            const newZoomLevel = map.getZoom();
            if (Math.abs(newZoomLevel - currentZoomLevel) >= 0.5) {
                currentZoomLevel = newZoomLevel;
                
                if (zoomTimeout) clearTimeout(zoomTimeout);
                
                zoomTimeout = setTimeout(() => {
                    if (currentHeatmapType !== 'none' && heatmapLayer) {
                        // Re-render heatmap with new zoom-optimized parameters
                        const newRadius = getOptimalHeatmapRadius();
                        if (heatmapLayer.setOptions) {
                            heatmapLayer.setOptions({ radius: newRadius });
                        }
                    }
                }, 200);
            }
        });
    }

    // Initialize UI components
    function initializeUIComponents() {
        // Add pagination styles
        const style = document.createElement('style');
        style.textContent = `
            .pagination-controls {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 10px 20px;
                background: white;
                border-top: 1px solid #ddd;
                font-size: 14px;
            }
            .pagination-buttons button {
                padding: 6px 12px;
                margin: 0 4px;
                border: 1px solid #ddd;
                background: white;
                cursor: pointer;
                border-radius: 4px;
            }
            .pagination-buttons button:disabled {
                opacity: 0.5;
                cursor: not-allowed;
            }
            .pagination-buttons button:hover:not(:disabled) {
                background: #f5f5f5;
            }
            .metadata-display {
                margin-top: 15px;
                padding: 10px;
                background: #f9f9f9;
                border-radius: 4px;
                font-size: 13px;
            }
            .metadata-item {
                display: flex;
                justify-content: space-between;
                margin: 4px 0;
            }
        `;
        document.head.appendChild(style);
    }

    // Enhanced error handling for legacy function compatibility
    function handleLegacyFunctions() {
        // Map type buttons with new API
        const mapTypeButtons = {
            densityTotal: document.getElementById('btn-order-density-total'),
            densityOrganic: document.getElementById('btn-order-density-organic'),
            densityNonOrganic: document.getElementById('btn-order-density-non-organic'),
            userDensity: document.getElementById('btn-user-density-heatmap'),
            population: document.getElementById('btn-population-heatmap'),
            vendors: document.getElementById('btn-vendors-map'),
        };

        Object.keys(mapTypeButtons).forEach(type => {
            const button = mapTypeButtons[type];
            if (button) {
                button.addEventListener('click', () => {
                    const typeMapping = {
                        densityTotal: 'order_density',
                        densityOrganic: 'order_density_organic',
                        densityNonOrganic: 'order_density_non_organic',
                        userDensity: 'user_density',
                        population: 'population',
                        vendors: 'none'
                    };
                    currentHeatmapType = typeMapping[type] || 'none';
                    setActiveMapTypeButton(type);
                    fetchAndDisplayMapData();
                });
            }
        });
    }

    // Keep all existing utility functions but add error handling
    function showLoading(isLoading, message = 'LOADING ...') {
        if (isLoading) {
            bodyEl.classList.add('is-loading');
            globalLoadingOverlayEl.textContent = message;
            globalLoadingOverlayEl.classList.add('visible');
        } else {
            bodyEl.classList.remove('is-loading');
            globalLoadingOverlayEl.classList.remove('visible');
        }
    }

    // Placeholder functions for custom dropdowns (implement based on existing code)
    function getSelectedValuesFromCustomDropdown(config) {
        // Implementation should match your existing custom dropdown logic
        return [];
    }

    function populateCitySelect() {
        // Implementation from existing code
    }

    function initializeCustomDropdowns() {
        // Implementation from existing code
    }

    function applyDefaultFilters() {
        // Implementation from existing code
    }

    function setupEventListeners() {
        // Implementation from existing code + new handlers
        applyFiltersBtn.addEventListener('click', fetchAndDisplayMapData);
        handleLegacyFunctions();
    }

    function setActiveMapTypeButton(type) {
        // Implementation from existing code
    }

    function adjustMapView() {
        // Implementation from existing code
    }

    function addPolygonsToMap(polygonsData) {
        // Implementation from existing code
    }

    function addCoverageGridToMap(gridData) {
        // Implementation from existing code
    }

    // Start the application
    init();
});