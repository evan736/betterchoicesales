// Claim Map — disaster response tool for drawing damage polygons over the book
// and exporting a call list for affected households.
//
// Uses Leaflet + Leaflet.draw loaded via CDN at runtime (not bundled) because
// Next.js SSR + Leaflet's window dependency is a known annoyance and we only
// use this page when there's an event. CDN means zero build cost.
//
// Access is gated at the backend (admin / manager / retention_specialist) so
// we don't have to re-check here beyond a soft redirect for non-logged-in.
import React, { useEffect, useRef, useState, useCallback } from 'react';
import Head from 'next/head';
import { useRouter } from 'next/router';
import Navbar from '../components/Navbar';
import { useAuth } from '../contexts/AuthContext';
import api from '../lib/api';
import { toast } from 'react-toastify';
import { MapPin, Download, RefreshCw, AlertTriangle, Search, X, Zap } from 'lucide-react';

// LOB → pin color
const LOB_COLORS: Record<string, string> = {
  home: '#2563eb',        // blue
  auto: '#059669',        // green
  commercial: '#dc2626',  // red
  other: '#6b7280',       // gray
};

const LOB_LABELS: Record<string, string> = {
  home: 'Home',
  auto: 'Auto',
  commercial: 'Commercial',
  other: 'Other',
};

// Weather alert → color
const ALERT_COLORS: Record<string, string> = {
  'Tornado Warning': '#b91c1c',
  'Tornado Emergency': '#7f1d1d',
  'Severe Thunderstorm Warning': '#ea580c',
  'Flash Flood Warning': '#0891b2',
  'Flash Flood Emergency': '#164e63',
  'Hurricane Warning': '#7c3aed',
  'Tropical Storm Warning': '#a855f7',
};


type Customer = {
  customer_id: number;
  client_name: string;
  address?: string;
  city?: string;
  state?: string;
  zip?: string;
  primary_phone?: string;
  email?: string;
  lat: number | null;
  lng: number | null;
  primary_lob: string;
  lines_of_business: string[];
  policies: Array<{ policy_number?: string; carrier?: string; line_of_business?: string; status?: string }>;
};


const ClaimMapPage = () => {
  const { user } = useAuth();
  const router = useRouter();
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<any>(null);
  const customersLayerRef = useRef<any>(null);
  const alertsLayerRef = useRef<any>(null);
  const drawnItemsRef = useRef<any>(null);

  const [leafletReady, setLeafletReady] = useState(false);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [filtered, setFiltered] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);
  const [geocodeStatus, setGeocodeStatus] = useState<any>(null);
  const [alerts, setAlerts] = useState<any[]>([]);
  const [search, setSearch] = useState('');
  const [drawnPolygon, setDrawnPolygon] = useState<any>(null);
  const [insidePolygon, setInsidePolygon] = useState<Customer[]>([]);
  const [lobFilters, setLobFilters] = useState<Record<string, boolean>>({
    home: true, auto: true, commercial: true, other: true,
  });
  const [geocodeBatching, setGeocodeBatching] = useState(false);

  // ── Auth gate (soft) ────────────────────────────────────────────
  useEffect(() => {
    if (!user) { router.push('/'); return; }
  }, [user, router]);

  // ── Dynamic-load Leaflet + leaflet-draw from CDN ────────────────
  useEffect(() => {
    if (typeof window === 'undefined') return;
    if ((window as any).L && (window as any).L.Draw) { setLeafletReady(true); return; }

    const cssBase = document.createElement('link');
    cssBase.rel = 'stylesheet';
    cssBase.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
    document.head.appendChild(cssBase);

    const cssDraw = document.createElement('link');
    cssDraw.rel = 'stylesheet';
    cssDraw.href = 'https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.css';
    document.head.appendChild(cssDraw);

    const scriptBase = document.createElement('script');
    scriptBase.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
    scriptBase.async = true;
    scriptBase.onload = () => {
      const scriptDraw = document.createElement('script');
      scriptDraw.src = 'https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.js';
      scriptDraw.async = true;
      scriptDraw.onload = () => setLeafletReady(true);
      document.body.appendChild(scriptDraw);
    };
    document.body.appendChild(scriptBase);
  }, []);

  // ── Initialize the Leaflet map once Leaflet is loaded ───────────
  useEffect(() => {
    if (!leafletReady || mapRef.current || !mapContainerRef.current) return;
    const L = (window as any).L;

    // Default view centered on St Charles IL — will auto-zoom to fit customers
    const map = L.map(mapContainerRef.current, {
      center: [41.9142, -88.3098],
      zoom: 9,
    });

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap',
      maxZoom: 19,
    }).addTo(map);

    // Feature group to hold drawn polygons
    const drawnItems = new L.FeatureGroup();
    map.addLayer(drawnItems);
    drawnItemsRef.current = drawnItems;

    // Draw toolbar — polygon only (we don't need markers/circles/rectangles for this use case)
    const drawControl = new L.Control.Draw({
      edit: { featureGroup: drawnItems, remove: true },
      draw: {
        polygon: { allowIntersection: false, showArea: true, shapeOptions: { color: '#dc2626', weight: 3 } },
        polyline: false, rectangle: false, circle: false, marker: false, circlemarker: false,
      },
    });
    map.addControl(drawControl);

    map.on((L as any).Draw.Event.CREATED, (e: any) => {
      // Only one polygon at a time — replace any previous
      drawnItems.clearLayers();
      drawnItems.addLayer(e.layer);
      setDrawnPolygon(e.layer);
    });
    map.on((L as any).Draw.Event.DELETED, () => {
      setDrawnPolygon(null);
    });
    map.on((L as any).Draw.Event.EDITED, (e: any) => {
      e.layers.eachLayer((layer: any) => setDrawnPolygon(layer));
    });

    customersLayerRef.current = L.layerGroup().addTo(map);
    alertsLayerRef.current = L.layerGroup().addTo(map);

    mapRef.current = map;
  }, [leafletReady]);

  // ── Load data ───────────────────────────────────────────────────
  const loadCustomers = useCallback(async () => {
    setLoading(true);
    try {
      const [cRes, gRes] = await Promise.all([
        api.get('/api/claim-map/customers'),
        api.get('/api/claim-map/geocode-status'),
      ]);
      setCustomers(cRes.data.customers || []);
      setGeocodeStatus(gRes.data);
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Failed to load customers');
    }
    setLoading(false);
  }, []);

  const loadAlerts = useCallback(async () => {
    try {
      const r = await api.get('/api/claim-map/weather-alerts');
      setAlerts(r.data.alerts || []);
    } catch {
      // NWS is occasionally flaky; don't toast every failure
    }
  }, []);

  useEffect(() => {
    if (!user) return;
    loadCustomers();
    loadAlerts();
    const weatherPoll = setInterval(loadAlerts, 5 * 60 * 1000);  // 5 min
    return () => clearInterval(weatherPoll);
  }, [user, loadCustomers, loadAlerts]);

  // ── Filter customers by search + LOB toggles ────────────────────
  useEffect(() => {
    const q = search.trim().toLowerCase();
    const result = customers.filter(c => {
      if (!lobFilters[c.primary_lob]) return false;
      if (!q) return true;
      return (
        (c.client_name || '').toLowerCase().includes(q) ||
        (c.zip || '').includes(q) ||
        c.policies.some(p => (p.policy_number || '').toLowerCase().includes(q))
      );
    });
    setFiltered(result);
  }, [customers, search, lobFilters]);

  // ── Render customer pins on map ─────────────────────────────────
  useEffect(() => {
    if (!mapRef.current || !customersLayerRef.current) return;
    const L = (window as any).L;
    const layer = customersLayerRef.current;
    layer.clearLayers();

    const bounds: [number, number][] = [];
    filtered.forEach(c => {
      if (c.lat == null || c.lng == null) return;
      const color = LOB_COLORS[c.primary_lob] || LOB_COLORS.other;
      const marker = L.circleMarker([c.lat, c.lng], {
        radius: 6,
        fillColor: color,
        color: '#ffffff',
        weight: 1.5,
        opacity: 1,
        fillOpacity: 0.9,
      });

      const policiesHtml = c.policies.slice(0, 5).map(p => (
        `<li>${p.carrier || '—'} · ${p.line_of_business || '—'}${p.policy_number ? ' · #' + p.policy_number : ''}</li>`
      )).join('');

      marker.bindPopup(`
        <div style="font-family: -apple-system, system-ui, sans-serif; min-width: 220px;">
          <div style="font-weight: 700; font-size: 14px; color: #0f172a; margin-bottom: 4px;">${c.client_name}</div>
          <div style="font-size: 12px; color: #64748b; margin-bottom: 8px;">${c.address || ''}${c.city ? ', ' + c.city : ''}${c.state ? ', ' + c.state : ''} ${c.zip || ''}</div>
          ${c.primary_phone ? `<div style="font-size: 12px;"><strong>Phone:</strong> <a href="tel:${c.primary_phone}">${c.primary_phone}</a></div>` : ''}
          ${c.email ? `<div style="font-size: 12px;"><strong>Email:</strong> <a href="mailto:${c.email}">${c.email}</a></div>` : ''}
          <div style="font-size: 11px; color: #475569; margin-top: 8px; font-weight: 600;">Policies:</div>
          <ul style="font-size: 11px; color: #475569; margin: 4px 0 0 16px; padding: 0;">${policiesHtml}</ul>
        </div>
      `);
      marker.addTo(layer);
      bounds.push([c.lat, c.lng]);
    });

    if (bounds.length > 0 && filtered.length !== customers.length) {
      // User narrowed the set — zoom to the narrowed group
      mapRef.current.fitBounds(bounds, { padding: [30, 30], maxZoom: 14 });
    } else if (bounds.length > 0 && !mapRef.current._fittedOnce) {
      mapRef.current.fitBounds(bounds, { padding: [30, 30], maxZoom: 12 });
      mapRef.current._fittedOnce = true;
    }
  }, [filtered, customers.length]);

  // ── Render weather alert polygons ───────────────────────────────
  useEffect(() => {
    if (!mapRef.current || !alertsLayerRef.current) return;
    const L = (window as any).L;
    const layer = alertsLayerRef.current;
    layer.clearLayers();

    alerts.forEach(a => {
      if (!a.geometry) return;
      const color = ALERT_COLORS[a.event] || '#b91c1c';
      try {
        const poly = L.geoJSON(a.geometry, {
          style: { color, weight: 2, fillColor: color, fillOpacity: 0.15, dashArray: '4 2' },
        });
        poly.bindPopup(`
          <div style="font-family: -apple-system, system-ui, sans-serif; min-width: 240px; max-width: 320px;">
            <div style="font-weight: 700; color: ${color}; font-size: 13px; margin-bottom: 4px;">${a.event || 'Active Alert'}</div>
            <div style="font-size: 12px; color: #334155; margin-bottom: 6px;">${a.headline || ''}</div>
            <div style="font-size: 11px; color: #64748b;">${a.area_desc || ''}</div>
            ${a.expires ? `<div style="font-size: 11px; color: #475569; margin-top: 6px;"><strong>Expires:</strong> ${new Date(a.expires).toLocaleString()}</div>` : ''}
          </div>
        `);
        poly.addTo(layer);
      } catch {
        // Malformed geometry — skip
      }
    });
  }, [alerts]);

  // ── Compute which customers are inside the drawn polygon ────────
  useEffect(() => {
    if (!drawnPolygon) { setInsidePolygon([]); return; }
    const L = (window as any).L;
    const latLngs = drawnPolygon.getLatLngs()[0];
    // Point-in-polygon (ray casting) — works for simple polygons, which is all
    // the Leaflet.draw tool creates
    const inside = (lat: number, lng: number): boolean => {
      let result = false;
      for (let i = 0, j = latLngs.length - 1; i < latLngs.length; j = i++) {
        const xi = latLngs[i].lng, yi = latLngs[i].lat;
        const xj = latLngs[j].lng, yj = latLngs[j].lat;
        const intersect = ((yi > lat) !== (yj > lat)) && (lng < (xj - xi) * (lat - yi) / (yj - yi + 1e-12) + xi);
        if (intersect) result = !result;
      }
      return result;
    };
    const hits = customers.filter(c => c.lat != null && c.lng != null && inside(c.lat!, c.lng!));
    setInsidePolygon(hits);
  }, [drawnPolygon, customers]);

  // ── CSV export of customers in polygon ──────────────────────────
  const exportCallList = () => {
    if (insidePolygon.length === 0) {
      toast.error('No customers inside the drawn polygon');
      return;
    }
    const header = ['name', 'phone', 'email', 'address', 'city', 'state', 'zip', 'primary_lob', 'policies'].join(',');
    const csvEscape = (s: any) => {
      const str = s == null ? '' : String(s);
      if (str.includes(',') || str.includes('"') || str.includes('\n')) {
        return '"' + str.replace(/"/g, '""') + '"';
      }
      return str;
    };
    const lines = insidePolygon.map(c => [
      c.client_name,
      c.primary_phone || '',
      c.email || '',
      c.address || '',
      c.city || '',
      c.state || '',
      c.zip || '',
      c.primary_lob,
      c.policies.map(p => `${p.carrier}:${p.policy_number}`).join('|'),
    ].map(csvEscape).join(','));
    const csv = [header, ...lines].join('\n');

    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    const stamp = new Date().toISOString().slice(0, 16).replace(/[T:]/g, '-');
    link.download = `claim-map-calllist-${stamp}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    toast.success(`Exported ${insidePolygon.length} households`);
  };

  const runGeocodeBatch = async () => {
    setGeocodeBatching(true);
    try {
      const r = await api.post('/api/claim-map/geocode-batch?limit=100');
      toast.success(`Geocoded: ${r.data.succeeded} succeeded, ${r.data.failed} failed, ${r.data.remaining} pending`);
      // Reload customers to pick up new lat/lng
      loadCustomers();
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Geocode batch failed');
    }
    setGeocodeBatching(false);
  };

  const pctGeocoded = geocodeStatus
    ? Math.round((geocodeStatus.geocoded / Math.max(geocodeStatus.total_addresses, 1)) * 100)
    : 0;

  return (
    <>
      <Head><title>Claim Map · ORBIT</title></Head>
      <div className="min-h-screen bg-slate-50">
        <Navbar />
        <div className="max-w-[1800px] mx-auto px-4 py-4">
          {/* Header */}
          <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
            <div>
              <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
                <MapPin size={24} className="text-red-600" />
                Claim Map
              </h1>
              <p className="text-xs text-slate-500 mt-0.5">
                Draw a polygon on the map to isolate affected households after a disaster event.
              </p>
            </div>
            <div className="flex items-center gap-2">
              {alerts.length > 0 && (
                <div className="flex items-center gap-1.5 px-3 py-1.5 bg-red-50 border border-red-200 rounded-lg text-xs font-semibold text-red-700">
                  <AlertTriangle size={14} />
                  {alerts.length} active weather alert{alerts.length !== 1 ? 's' : ''}
                </div>
              )}
              <button
                onClick={() => { loadCustomers(); loadAlerts(); }}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-slate-700 bg-white border border-slate-200 rounded-lg hover:bg-slate-50"
              >
                <RefreshCw size={13} />
                Refresh
              </button>
            </div>
          </div>

          {/* Geocode status banner */}
          {geocodeStatus && geocodeStatus.pending > 0 && (
            <div className="mb-3 px-3 py-2 bg-amber-50 border border-amber-200 rounded-lg flex items-center gap-3 text-xs">
              <Zap size={14} className="text-amber-600 flex-shrink-0" />
              <div className="flex-1">
                <strong>{geocodeStatus.geocoded}</strong> of {geocodeStatus.total_addresses} addresses geocoded ({pctGeocoded}%) ·
                <strong className="ml-1">{geocodeStatus.pending}</strong> pending
                {geocodeStatus.failed > 0 && <span className="ml-1">· {geocodeStatus.failed} failed</span>}
                <span className="ml-2 text-slate-500">— providers: {geocodeStatus.providers_available.join(', ')}</span>
              </div>
              {user?.role?.toLowerCase() === 'admin' && (
                <button
                  onClick={runGeocodeBatch}
                  disabled={geocodeBatching}
                  className="px-3 py-1 text-xs font-semibold text-white bg-amber-600 rounded hover:bg-amber-700 disabled:opacity-50"
                >
                  {geocodeBatching ? 'Geocoding…' : 'Run Batch (100)'}
                </button>
              )}
            </div>
          )}

          {/* Main grid: map + sidebar */}
          <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-3">
            {/* Map */}
            <div className="relative bg-white border border-slate-200 rounded-lg overflow-hidden" style={{ height: '78vh', minHeight: 500 }}>
              <div ref={mapContainerRef} className="w-full h-full" />
              {!leafletReady && (
                <div className="absolute inset-0 flex items-center justify-center bg-slate-50 text-slate-400 text-sm">
                  Loading map…
                </div>
              )}

              {/* Legend overlay */}
              <div className="absolute bottom-3 left-3 bg-white rounded-lg shadow-lg border border-slate-200 p-2 text-[10px]" style={{ zIndex: 1000 }}>
                <div className="font-semibold text-slate-700 mb-1">Pin color</div>
                {Object.entries(LOB_COLORS).map(([lob, color]) => (
                  <div key={lob} className="flex items-center gap-1.5 mb-0.5">
                    <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ backgroundColor: color }} />
                    <span className="text-slate-600">{LOB_LABELS[lob]}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Sidebar */}
            <div className="space-y-3">
              {/* Search + filters */}
              <div className="bg-white border border-slate-200 rounded-lg p-3">
                <div className="relative mb-2">
                  <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
                  <input
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                    placeholder="Search name, policy, zip…"
                    className="w-full pl-8 pr-8 py-1.5 text-sm border border-slate-200 rounded-lg focus:border-blue-300 focus:ring-1 focus:ring-blue-200 outline-none"
                    style={{ color: '#0f172a', backgroundColor: '#ffffff' }}
                  />
                  {search && (
                    <button onClick={() => setSearch('')} className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600">
                      <X size={13} />
                    </button>
                  )}
                </div>
                <div className="text-[10px] text-slate-500 font-semibold uppercase tracking-wide mb-1">Line of business</div>
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(LOB_LABELS).map(([lob, label]) => (
                    <button
                      key={lob}
                      onClick={() => setLobFilters({ ...lobFilters, [lob]: !lobFilters[lob] })}
                      className={`flex items-center gap-1 px-2 py-0.5 text-[11px] rounded border transition-colors ${
                        lobFilters[lob]
                          ? 'bg-slate-100 border-slate-300 text-slate-800'
                          : 'bg-white border-slate-200 text-slate-400 line-through'
                      }`}
                    >
                      <span className="inline-block w-2 h-2 rounded-full" style={{ backgroundColor: LOB_COLORS[lob] }} />
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Stats */}
              <div className="bg-white border border-slate-200 rounded-lg p-3">
                <div className="text-[10px] text-slate-500 font-semibold uppercase tracking-wide mb-1.5">On the map</div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <div className="text-lg font-bold text-slate-900 tabular-nums">{filtered.length.toLocaleString()}</div>
                    <div className="text-[11px] text-slate-500">visible households</div>
                  </div>
                  <div>
                    <div className="text-lg font-bold text-slate-900 tabular-nums">{customers.filter(c => c.lat).length.toLocaleString()}</div>
                    <div className="text-[11px] text-slate-500">pinned total</div>
                  </div>
                </div>
              </div>

              {/* Polygon export */}
              <div className="bg-white border border-slate-200 rounded-lg p-3">
                <div className="text-[10px] text-slate-500 font-semibold uppercase tracking-wide mb-1.5">Polygon selection</div>
                {drawnPolygon ? (
                  <>
                    <div className="text-lg font-bold text-slate-900 tabular-nums mb-0.5">{insidePolygon.length}</div>
                    <div className="text-[11px] text-slate-500 mb-2">households inside the drawn area</div>
                    <button
                      onClick={exportCallList}
                      disabled={insidePolygon.length === 0}
                      className="w-full flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-semibold text-white bg-red-600 rounded-lg hover:bg-red-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      <Download size={13} />
                      Export Call List CSV
                    </button>
                  </>
                ) : (
                  <div className="text-xs text-slate-500 leading-relaxed">
                    Use the polygon tool (top-left of map) to trace a damage area. Customers inside will be listed here for export.
                  </div>
                )}
              </div>

              {/* Active weather alerts list */}
              {alerts.length > 0 && (
                <div className="bg-white border border-slate-200 rounded-lg p-3 max-h-[40vh] overflow-y-auto">
                  <div className="text-[10px] text-slate-500 font-semibold uppercase tracking-wide mb-1.5 flex items-center gap-1">
                    <AlertTriangle size={10} />
                    Active NWS Alerts ({alerts.length})
                  </div>
                  <div className="space-y-1.5">
                    {alerts.slice(0, 20).map((a, i) => (
                      <div key={i} className="p-1.5 rounded border border-slate-100 text-[11px]">
                        <div className="font-semibold" style={{ color: ALERT_COLORS[a.event] || '#b91c1c' }}>{a.event}</div>
                        <div className="text-slate-600 truncate" title={a.area_desc}>{a.area_desc}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  );
};

export default ClaimMapPage;
