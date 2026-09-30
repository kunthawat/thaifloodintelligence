(() => {
  'use strict';

  const $ = (selector) => document.querySelector(selector);
  const mapEl = $('#map');
  const tileLayer = $('#tiles');
  const DEFAULT_ZOOM = 5;
  const state = {
    selected: null,
    expert: false,
    dataQuality: null,
    toastTimer: null,
    activeLayer: 'gauges',
    layerTimer: null,
    layerRequest: 0,
    searchTimer: null,
    searchRequest: 0,
  };
  const map = new maplibregl.Map({
    container: tileLayer,
    style: 'https://tiles.openfreemap.org/styles/liberty',
    center: [101, 15.2],
    zoom: DEFAULT_ZOOM,
    minZoom: 3,
    maxZoom: 16,
    attributionControl: false,
  });
  let selectedMarker = null;
  map.on('load', () => { if (state.activeLayer) scheduleLayer(); });
  map.on('idle', () => {
    const id = state.activeLayer === 'gauges' ? 'gauges-points' : state.activeLayer === 'rain' ? 'rain-points' : 'flow-lines';
    if (state.activeLayer && !map.getLayer(id)) scheduleLayer();
  });
  map.on('moveend', () => { if (state.activeLayer) scheduleLayer(); });
  map.on('click', (event) => {
    const rain = map.getLayer('rain-points')
      ? map.queryRenderedFeatures(event.point, { layers: ['rain-points'] })[0] : null;
    if (rain) {
      const p = rain.properties;
      new maplibregl.Popup().setLngLat(rain.geometry.coordinates).setText((p.name || 'สถานีฝน') + ' · ' +
        (p.rain_24h_mm == null ? 'ไม่มีค่า' : Number(p.rain_24h_mm).toFixed(1) + ' มม. / 24 ชม.') +
        ' · ' + (p.observed_at_source || 'ไม่ทราบเวลา')).addTo(map);
      return;
    }
    const gauge = map.getLayer('gauges-points')
      ? map.queryRenderedFeatures(event.point, { layers: ['gauges-points'] })[0] : null;
    if (gauge) {
      const p = gauge.properties;
      const details = [p.waterlevel_msl_m == null ? 'ไม่มีค่า MSL' : Number(p.waterlevel_msl_m).toFixed(2) + ' ม. MSL',
        p.observed_at_source || 'ไม่ทราบเวลา'];
      new maplibregl.Popup().setLngLat(gauge.geometry.coordinates).setText((p.name || 'สถานี') + ' · ' + details.join(' · ')).addTo(map);
      return;
    }
    selectLocation(event.lngLat.lat, event.lngLat.lng);
  });

  function scheduleLayer() {
    clearTimeout(state.layerTimer);
    state.layerTimer = setTimeout(loadLayer, 180);
  }

  async function loadLayer() {
    if (!state.activeLayer) return;
    if (!map.isStyleLoaded()) return;
    const bounds = map.getBounds();
    const request = ++state.layerRequest;
    try {
      const query = new URLSearchParams({
        west: bounds.getWest(), south: bounds.getSouth(),
        east: bounds.getEast(), north: bounds.getNorth(),
      });
      const layer = await api('/v1/layers/' + encodeURIComponent(state.activeLayer) + '?' + query);
      if (request !== state.layerRequest || !state.activeLayer) return;
      clearMapLayers();
      const id = state.activeLayer === 'gauges' ? 'gauges-points' : state.activeLayer === 'rain' ? 'rain-points' : 'flow-lines';
      map.addSource(id, { type: 'geojson', data: layer });
      if (state.activeLayer === 'gauges') {
        map.addLayer({ id, type: 'circle', source: id,
          paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 3, 2, 8, 5],
            'circle-color': '#0c8191', 'circle-opacity': .8,
            'circle-stroke-color': '#fff', 'circle-stroke-width': 1 } });
      } else if (state.activeLayer === 'rain') {
        map.addLayer({ id, type: 'circle', source: id, filter: ['>', ['coalesce', ['get', 'rain_24h_mm'], 0], 0],
          paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 3, 1.5, 8, 4],
            'circle-color': ['case', ['>=', ['coalesce', ['get', 'rain_24h_mm'], 0], 35], '#be4d55',
              ['>=', ['coalesce', ['get', 'rain_24h_mm'], 0], 10], '#d99b36',
              ['>', ['coalesce', ['get', 'rain_24h_mm'], 0], 0], '#328dc3', '#a4b4bb'],
            'circle-opacity': .8, 'circle-stroke-color': '#fff', 'circle-stroke-width': .4 } });
      } else {
        map.addLayer({ id, type: 'line', source: id, paint: { 'line-color': '#147dab', 'line-width': 2 } });
      }
      if (layer.stale) showToast('ข้อมูลสถานีจากครั้งล่าสุด · ยังอัปเดตไม่ได้');
    } catch (_) {
      if (request === state.layerRequest) showToast('อ่านชั้นข้อมูลไม่ได้ โปรดลองอีกครั้ง');
    }
  }

  function clearMapLayers() {
    for (const id of ['gauges-points', 'rain-points', 'flow-lines']) {
      if (map.getLayer(id)) map.removeLayer(id);
    }
    for (const id of ['gauges-points', 'rain-points', 'flow-lines']) if (map.getSource(id)) map.removeSource(id);
  }

  function showToast(message) {
    const toast = $('#toast');
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add('is-visible');
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => toast.classList.remove('is-visible'), 2700);
  }

  function coordinateLabel(lat, lon) {
    const latDir = lat >= 0 ? 'N' : 'S';
    const lonDir = lon >= 0 ? 'E' : 'W';
    return Math.abs(lat).toFixed(5) + '° ' + latDir + ', ' + Math.abs(lon).toFixed(5) + '° ' + lonDir;
  }

  function selectLocation(lat, lon, label = null) {
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || lat < -90 || lat > 90 || lon < -180 || lon > 180) {
      showToast('พิกัดไม่ถูกต้อง โปรดตรวจสอบละติจูดและลองจิจูด');
      return;
    }
    state.selected = { lat, lon };
    $('#emptyState').hidden = true;
    $('#selectedState').hidden = false;
    $('#selectedName').textContent = label || coordinateLabel(lat, lon);
    $('#selectedCoordinates').textContent = coordinateLabel(lat, lon) + ' · WGS84';
    $('#locationSearch').value = label || lat.toFixed(5) + ', ' + lon.toFixed(5);
    $('#searchSuggestions').hidden = true;
    if (selectedMarker) selectedMarker.remove();
    selectedMarker = new maplibregl.Marker({ color: '#bd6547' }).setLngLat([lon, lat]).addTo(map);
    map.flyTo({ center: [lon, lat], zoom: Math.max(map.getZoom(), label ? 10 : 8),
      offset: window.matchMedia('(max-width: 760px)').matches ? [0, -mapEl.clientHeight * .18] : [0, 0] });
    loadLocationData();
    loadNearbyGauges(lat, lon);
    loadNearbyRain(lat, lon);
    showAdminBoundary(lat, lon);
  }

  async function showAdminBoundary(lat, lon) {
    try {
      const data = await api('/v1/location/admin-boundary?lat=' + lat + '&lon=' + lon);
      if (!state.selected || state.selected.lat !== lat || state.selected.lon !== lon) return;
      const draw = () => {
        if (map.getSource('selected-admin')) map.getSource('selected-admin').setData(data);
        else {
          map.addSource('selected-admin', { type: 'geojson', data });
          map.addLayer({ id: 'selected-admin-fill', type: 'fill', source: 'selected-admin',
            paint: { 'fill-color': '#3a91a2', 'fill-opacity': 0.13 } });
          map.addLayer({ id: 'selected-admin-outline', type: 'line', source: 'selected-admin',
            paint: { 'line-color': '#287887', 'line-width': 2 } });
        }
      };
      if (map.isStyleLoaded()) draw(); else map.once('load', draw);
    } catch (_) { /* Keep the map usable when administrative geometry is unavailable. */ }
  }

  function clearLocation() {
    state.selected = null;
    if (selectedMarker) selectedMarker.remove();
    selectedMarker = null;
    if (map.getSource('selected-admin')) map.getSource('selected-admin').setData({ type: 'FeatureCollection', features: [] });
    $('#selectedState').hidden = true;
    $('#emptyState').hidden = false;
    $('#locationSearch').value = '';
    $('#searchSuggestions').hidden = true;
    $('#locationPanel').classList.remove('is-expanded');
    closeRouteMessage();
  }

  async function api(path) {
    const response = await fetch(path, { headers: { Accept: 'application/json' } });
    if (!response.ok) throw new Error('API_' + response.status);
    return response.json();
  }

  function queryLocation(path, selected) {
    return path + '?lat=' + encodeURIComponent(selected.lat) + '&lon=' + encodeURIComponent(selected.lon);
  }

  async function loadLocationData() {
    const selected = state.selected;
    if (!selected) return;
    $('#riskHeadline').textContent = 'กำลังตรวจสอบข้อมูล';
    $('#riskSubhead').textContent = 'กำลังอ่านสถานะข้อมูลที่ระบบมีอยู่';
    try {
      const results = await Promise.all([
        api(queryLocation('/v1/location/risk', selected)),
        api(queryLocation('/v1/location/forecast', selected)),
        api(queryLocation('/v1/location/explanation', selected)),
        api(queryLocation('/v1/location/context', selected)),
        api(queryLocation('/v1/location/readiness', selected)),
      ]);
      if (!state.selected || state.selected.lat !== selected.lat || state.selected.lon !== selected.lon) return;
      const risk = results[0];
      const forecast = results[1];
      const explanation = results[2];
      renderRisk(risk, forecast, explanation);
      renderContext(results[3]);
      renderReadiness(results[4]);
      if (state.dataQuality) renderSourceStatus(state.dataQuality);
      if (state.expert && state.dataQuality) renderExpert(forecast, state.dataQuality);
      $('#updatedAt').textContent = 'ตรวจข้อมูลล่าสุดแล้ว · สถานะความเสี่ยงขึ้นกับข้อมูลตรวจวัดที่ผ่านเกณฑ์';
    } catch (_) {
      if (!state.selected || state.selected.lat !== selected.lat || state.selected.lon !== selected.lon) return;
      $('#riskHeadline').textContent = 'ยังประเมินความเสี่ยงไม่ได้';
      $('#riskSubhead').textContent = 'ยังเชื่อมต่อบริการประเมินข้อมูลไม่ได้';
      $('#updatedAt').textContent = 'ยังอ่านสถานะบริการไม่ได้';
      $('#uncertaintyText').textContent = 'สถานะบริการไม่พร้อม ข้อมูลนี้ไม่ยืนยันว่าพื้นที่ปลอดภัย';
      showToast('ติดต่อบริการข้อมูลไม่ได้ โปรดลองอีกครั้ง');
    }
  }

  async function loadNearbyGauges(lat, lon) {
    $('#gaugeHeadline').textContent = 'กำลังอ่านสถานี';
    $('#gaugeDetail').textContent = 'ค่าที่สถานีไม่ใช่ค่าระดับน้ำ ณ จุดที่เลือก';
    try {
      const data = await api('/v1/location/nearby-gauges?lat=' + lat + '&lon=' + lon);
      if (!state.selected || state.selected.lat !== lat || state.selected.lon !== lon) return;
      const station = data.items[0];
      if (!station) throw new Error('NO_STATIONS');
      $('#gaugeHeadline').textContent = station.name + (station.station_code ? ' (' + station.station_code + ')' : '');
      const level = station.waterlevel_msl_m == null ? 'ไม่มีค่าระดับน้ำ MSL' : station.waterlevel_msl_m.toFixed(2) + ' ม. MSL';
      $('#gaugeDetail').textContent = level + ' · ห่างประมาณ ' + station.distance_km_approx.toFixed(1) + ' กม. · เวลาในแหล่งข้อมูล ' +
        (station.observed_at_source || 'ไม่ระบุ') + (data.stale ? ' · ข้อมูลค้างจากครั้งก่อน' : '') +
        ' · ค่าที่สถานี ไม่ใช่ระดับน้ำที่จุดนี้';
    } catch (_) {
      if (state.selected && state.selected.lat === lat && state.selected.lon === lon) {
        $('#gaugeHeadline').textContent = 'ยังอ่านสถานีไม่ได้';
        $('#gaugeDetail').textContent = 'ข้อมูลระดับน้ำสดยังไม่พร้อม';
      }
    }
  }

  async function loadNearbyRain(lat, lon) {
    $('#rainHeadline').textContent = 'กำลังอ่านสถานี';
    $('#rainDetail').textContent = 'ค่าฝนที่สถานีไม่ใช่ปริมาณฝน ณ จุดที่เลือก';
    try {
      const data = await api('/v1/location/nearby-rain?lat=' + lat + '&lon=' + lon);
      if (!state.selected || state.selected.lat !== lat || state.selected.lon !== lon) return;
      const station = data.items[0];
      if (!station) throw new Error('NO_RAIN_STATIONS');
      $('#rainHeadline').textContent = station.name + (station.station_code ? ' (' + station.station_code + ')' : '');
      const amount = station.rain_24h_mm == null ? 'ไม่มีค่าฝน 24 ชม.' : station.rain_24h_mm.toFixed(1) + ' มม. / 24 ชม.';
      $('#rainDetail').textContent = amount + ' · ห่างประมาณ ' + station.distance_km_approx.toFixed(1) +
        ' กม. · เวลาในแหล่งข้อมูล ' + (station.observed_at_source || 'ไม่ระบุ') +
        (data.stale ? ' · ข้อมูลค้างจากครั้งก่อน' : '') + ' · ค่าที่สถานี ไม่ใช่ฝนที่จุดนี้';
    } catch (_) {
      if (state.selected && state.selected.lat === lat && state.selected.lon === lon) {
        $('#rainHeadline').textContent = 'ยังอ่านสถานีฝนไม่ได้';
        $('#rainDetail').textContent = 'ข้อมูลฝนตรวจวัดยังไม่พร้อม';
      }
    }
  }

  async function refreshQuality() {
    try {
      const quality = await api('/v1/data-quality');
      state.dataQuality = quality;
      renderSourceStatus(quality);
      if (state.selected) {
        const selected = state.selected;
        api(queryLocation('/v1/official-warnings', selected)).then((warnings) => {
          if (state.selected && state.selected.lat === selected.lat && state.selected.lon === selected.lon) {
            renderOfficialWarnings(warnings);
          }
        }).catch(() => {});
      }
      if (state.expert && state.selected) {
        const forecast = JSON.parse($('#expertEligibility').dataset.forecast || '{}');
        renderExpert(forecast, quality);
      }
    } catch (_) {
      $('.live-status').lastChild.textContent = ' ยังตรวจแหล่งข้อมูลไม่ได้';
    }
  }

  function renderContext(context) {
    const catchment = context.catchment;
    const reach = context.nearest_reach;
    $('#catchmentHeadline').textContent = catchment ? 'ลุ่มน้ำย่อย ' + catchment.catchment_id : 'ยังระบุลุ่มน้ำย่อยไม่ได้';
    $('#catchmentDetail').textContent = catchment
      ? 'HydroBASINS · พื้นที่ ' + (catchment.area_km2 == null ? 'ไม่ทราบ' : Number(catchment.area_km2).toFixed(1) + ' ตร.กม.') +
        (reach ? ' · ลำน้ำ HydroRIVERS ห่างประมาณ ' + (Number(reach.distance_m) / 1000).toFixed(1) + ' กม.' : '')
      : 'ตำแหน่งนี้ไม่มีขอบเขตลุ่มน้ำในชุดข้อมูลที่นำเข้า';
  }

  function renderSourceStatus(quality) {
    const health = quality.source_health || [];
    const valid = health.filter((item) => item.state === 'VALID');
    const stage = health.find((item) => item.source_id === 'thaiwater_v3' && item.state === 'VALID');
    const stationCount = stage && stage.details && stage.details.parsed_station_count;
    const rainfall = health.find((item) => item.source_id === 'thaiwater_rain_24h' && item.state === 'VALID');
    const rainCount = rainfall && rainfall.details && rainfall.details.parsed_station_count;
    const live = $('.live-status');
    live.lastChild.textContent = stationCount
      ? ' ระดับน้ำ ' + stationCount + ' · ฝน ' + (rainCount || 0) + ' สถานี'
      : valid.length ? ' ตรวจพบการเชื่อมต่อ ' + valid.length + ' แหล่ง' : ' ยังตรวจแหล่งข้อมูลไม่ได้';
    const empty = $('.source-not-ready span:last-child');
    if (empty) empty.textContent = stationCount
      ? 'มีข้อมูลสถานีระดับน้ำ ' + stationCount + ' และสถานีฝน ' + (rainCount || 0) + ' แห่ง · การประเมินความเสี่ยงยังไม่พร้อม'
      : valid.length
      ? 'ตรวจพบการเชื่อมต่อแหล่งข้อมูลทางการ ' + valid.length + ' แหล่ง เลือกพื้นที่เพื่อดูข้อมูลที่ระบุตำแหน่งได้'
      : 'ยังไม่มีแหล่งข้อมูลทางการที่ผ่านการตรวจสอบ';
    if (!state.selected && stationCount) $('#updatedAt').textContent =
      'มีข้อมูลระดับน้ำและฝนที่สถานี · การประเมินความเสี่ยงยังไม่พร้อม';
  }

  function renderRisk(risk, forecast, explanation) {
    const occurrenceEligible = risk.occurrence && risk.occurrence.eligible;
    const level = occurrenceEligible ? risk.risk_level : 'UNKNOWN';
    const riskLevels = {
      NORMAL: { symbol: '✓', label: 'ปกติ', className: 'is-normal' },
      WATCH: { symbol: '!', label: 'เฝ้าระวัง', className: 'is-watch' },
      HIGH: { symbol: '▲', label: 'เสี่ยงสูง', className: 'is-high' },
      DANGER: { symbol: '⚠', label: 'อันตราย', className: 'is-danger' },
      UNKNOWN: { symbol: '?', label: 'ข้อมูลไม่เพียงพอ', className: '' },
    };
    const riskPresentation = riskLevels[level] || riskLevels.UNKNOWN;
    $('#riskBadgeSymbol').textContent = riskPresentation.symbol;
    $('#riskBadgeLabel').textContent = riskPresentation.label;
    $('#riskBadge').className = 'status-badge ' + riskPresentation.className;
    const confidenceLabels = { HIGH: 'สูง', MEDIUM: 'ปานกลาง', LOW: 'ต่ำ' };
    const confidenceLevel = risk.confidence && risk.confidence.occurrence;
    $('#occurrenceConfidence').textContent = confidenceLabels[confidenceLevel] || 'ยังประเมินไม่ได้';
    if (occurrenceEligible && risk.risk_level && risk.risk_level !== 'UNKNOWN') {
      const floodOutput = forecast.will_flood;
      $('#riskHeadline').textContent = floodOutput && floodOutput.eligible && floodOutput.value === false
        ? 'ไม่พบสัญญาณน้ำท่วมในแบบจำลอง'
        : (risk.risk_headline || 'มีสัญญาณความเสี่ยงที่ต้องติดตาม');
      $('#riskSubhead').textContent = 'ผลประเมินใช้เฉพาะข้อมูลที่ผ่านเกณฑ์';
    } else {
      $('#riskHeadline').textContent = 'ยังประเมินความเสี่ยงไม่ได้';
      $('#riskSubhead').textContent = 'ข้อมูลตรวจวัดและแบบจำลองที่จำเป็นยังไม่พร้อม';
    }
    const impact = forecast.first_impact;
    $('#impactValue').textContent = impact && impact.eligible && impact.range_hours
      ? 'ประมาณ ' + impact.range_hours[0] + '–' + impact.range_hours[1] + ' ชม.'
      : 'ยังประเมินเวลาไม่ได้';
    $('#hazardValue').textContent = risk.dominant_hazard || 'ข้อมูลไม่พอจำแนกภัย';
    const hazardLabels = {
      RIVER_OVERFLOW: 'น้ำล้นตลิ่ง', FLASH_FLOOD: 'น้ำป่าไหลหลาก', LOCAL_RAIN: 'ฝนในพื้นที่',
      COASTAL_TIDAL: 'น้ำทะเลหนุน', COMPOUND: 'หลายปัจจัยร่วมกัน',
    };
    if (risk.dominant_hazard && hazardLabels[risk.dominant_hazard]) $('#hazardValue').textContent = hazardLabels[risk.dominant_hazard];
    $('#bankfullValue').textContent = formatOutput(forecast.time_to_bankfull, 'time');
    $('#peakValue').textContent = formatOutput(forecast.peak_above_bank_m, 'meters');
    $('#peakTimeValue').textContent = formatOutput(forecast.time_to_peak, 'time');
    $('#durationValue').textContent = formatOutput(forecast.duration_above_bank, 'duration');
    $('#exposureValue').textContent = formatOutput(forecast.location_exposure, 'boolean');
    $('#depthValue').textContent = formatOutput(forecast.point_depth, 'depth');
    renderOfficialWarnings(risk.official_warning || { available: false });
    $('#multiWaveNotice').hidden = !(forecast.event_status === 'RECESSION' && Number(forecast.active_waves) > 0);
    const uncertaintyCount = (explanation.uncertainties || []).length;
    $('#uncertaintyText').textContent = uncertaintyCount
      ? 'มีข้อจำกัดด้านข้อมูล ' + uncertaintyCount + ' รายการ ระบบจะแสดงความเสี่ยงเมื่อมีหลักฐานเพียงพอ'
      : 'ข้อมูลที่ขาดหายไม่ถือว่าเป็นความเสี่ยงต่ำหรือไม่มีน้ำท่วม';
    const list = $('#uncertaintyList');
    list.replaceChildren();
    const messages = (explanation.uncertainties || []).map((item) => item.message || item.code);
    if (!messages.length) messages.push('ไม่มีข้อจำกัดที่ระบบรายงาน');
    messages.forEach((message) => {
      const li = document.createElement('li');
      li.textContent = message;
      list.appendChild(li);
    });
    $('#expertEligibility').dataset.forecast = JSON.stringify(forecast);
  }

  function renderOfficialWarnings(official) {
    const warningItems = official.items || [];
    const historical = official.historical_context || [];
    const latestWarningObservation = official.source && official.source.last_observation
      ? new Date(official.source.last_observation).toLocaleString('th-TH', { timeZone: 'Asia/Bangkok' })
      : null;
    if (!warningItems.length && historical.length) {
      $('#officialHeadline').textContent = 'มีประกาศย้อนหลังในพื้นที่';
      $('#officialDetail').textContent = historical[0].title + ' · ประกาศเมื่อ ' +
        new Date(historical[0].issued_at).toLocaleString('th-TH', { timeZone: 'Asia/Bangkok' }) +
        ' · ไม่ยืนยันว่าเป็นคำเตือนปัจจุบัน';
      $('#officialState').textContent = 'ข้อมูลย้อนหลัง';
    } else if (!official.available) {
      if (official.reason === 'WARNING_SOURCE_STALE') {
        $('#officialHeadline').textContent = 'ข้อมูลประกาศเตือนอัปเดตไม่ทันเวลา';
        $('#officialDetail').textContent = 'เชื่อมต่อแหล่ง DWR ได้ แต่ข้อมูลล่าสุด' +
          (latestWarningObservation ? ' ถึง ' + latestWarningObservation : '') +
          ' จึงยังยืนยันประกาศปัจจุบันไม่ได้';
        $('#officialState').textContent = 'ข้อมูลล้าสมัย';
      } else if (official.reason === 'UNRESOLVED_WARNING_SCOPE') {
        $('#officialHeadline').textContent = 'มีประกาศที่ยังระบุพื้นที่ไม่ได้';
        $('#officialDetail').textContent = 'ไม่นำประกาศที่ยังยืนยันขอบเขตไม่ได้มาแสดงว่าอยู่ในพื้นที่นี้';
        $('#officialState').textContent = 'ต้องตรวจสอบขอบเขต';
      } else if (official.reason === 'WARNING_SOURCE_UNAVAILABLE') {
        $('#officialHeadline').textContent = 'แหล่งประกาศเตือนยังไม่ตอบสนอง';
        $('#officialDetail').textContent = 'ยังยืนยันสถานะประกาศจากหน่วยงานต้นทางไม่ได้';
        $('#officialState').textContent = 'แหล่งข้อมูลขัดข้อง';
      } else {
        $('#officialHeadline').textContent = 'ยังตรวจสอบประกาศไม่ได้';
        $('#officialDetail').textContent = 'กำลังตรวจสอบสถานะล่าสุดของแหล่งประกาศทางการ';
        $('#officialState').textContent = 'กำลังตรวจสอบ';
      }
    } else if (!warningItems.length) {
      $('#officialHeadline').textContent = 'ไม่พบประกาศเตือนที่ยังมีผลในพื้นที่นี้';
      $('#officialDetail').textContent = 'แหล่ง DWR อัปเดตถึง' +
        (latestWarningObservation ? ' ' + latestWarningObservation : ' ล่าสุด') +
        ' · ผลประกาศทางการแยกจากผลประเมินของระบบ';
      $('#officialState').textContent = 'ตรวจสอบแล้ว';
    } else {
      const firstWarning = warningItems[0];
      $('#officialHeadline').textContent = firstWarning.title || firstWarning.warning_type || 'มีประกาศเตือนทางการ';
      $('#officialDetail').textContent = firstWarning.authority || 'ตรวจพบประกาศจากหน่วยงานทางการ';
      $('#officialState').textContent = firstWarning.severity || 'มีประกาศ';
    }
  }

  function renderReadiness(readiness) {
    const hazardNames = {
      river_overflow: 'น้ำล้นตลิ่ง', flash_flood: 'น้ำป่าไหลหลาก',
      local_rain: 'ฝนในพื้นที่', coastal_tidal: 'น้ำทะเลหนุน',
      compound: 'หลายปัจจัยร่วมกัน',
    };
    const statusNames = { READY: 'มีหลักฐานในพื้นที่', PARTIAL: 'มีข้อมูลประกอบบางส่วน',
      NOT_READY: 'ยังไม่มีหลักฐานเพียงพอ', NOT_APPLICABLE: 'ไม่เกี่ยวกับพื้นที่นี้' };
    const reasonNames = {
      SCOPED_OFFICIAL_WARNING: 'ประกาศทางการครอบคลุมจุดนี้',
      SCOPED_COASTAL_WARNING: 'ประกาศเตือนชายฝั่งครอบคลุมจุดนี้',
      NEARBY_STAGE_UNCONNECTED: 'มีสถานีระดับน้ำใกล้เคียง แต่ยังไม่ยืนยันว่าเชื่อมถึงจุดนี้',
      STAGE_TIMEZONE_UNVERIFIED: 'ยังยืนยันเวลาตรวจวัดระดับน้ำไม่ได้',
      DATUM_OR_TIMEZONE_UNVERIFIED: 'ยังยืนยัน datum หรือเวลาตรวจวัดระดับน้ำไม่ได้',
      LOCAL_RAIN_OBSERVED: 'มีฝนที่สถานีใกล้เคียง',
      CATCHMENT_RAIN_OBSERVED: 'มีฝนในลุ่มน้ำเดียวกัน',
      RAIN_TRIGGER_THRESHOLD_UNVERIFIED: 'ยังไม่มีเกณฑ์ฝนที่ยืนยันสำหรับพื้นที่นี้',
      WETNESS_AND_TIMEZONE_UNVERIFIED: 'ยังขาดความชื้นสะสมและการยืนยันเวลาฝน',
      NEARBY_RAIN_STATION: 'มีสถานีวัดฝนใกล้เคียง',
      OBSERVATION_TIMEZONE_UNVERIFIED: 'ยังยืนยันเวลาตรวจวัดไม่ได้',
      NO_CONNECTED_STAGE_OR_SCOPED_WARNING: 'ยังไม่มีระดับน้ำที่เชื่อมถึงจุดนี้หรือประกาศที่ระบุพื้นที่',
      NO_SCOPED_WARNING_OR_VERIFIED_RAIN_TRIGGER: 'ยังไม่มีประกาศหรือฝนที่ยืนยันเป็นตัวกระตุ้น',
      NO_NEARBY_RAIN_OBSERVATION: 'ไม่พบสถานีฝนใกล้จุดนี้ในข้อมูลล่าสุด',
      NO_VERIFIED_COASTAL_BOUNDARY_OR_TIDE_EVIDENCE: 'ยังไม่มีข้อมูลน้ำทะเลและขอบเขตปลายน้ำที่ยืนยัน',
      MULTIPLE_PROCESSES_WITH_INCOMPLETE_LINKAGE: 'มีหลักฐานหลายด้าน แต่ยังเชื่อมโยงผลกระทบไม่ได้',
      FEWER_THAN_TWO_SUPPORTED_PROCESSES: 'ยังไม่มีหลักฐานสองปัจจัยที่เกิดร่วมกัน',
    };
    const active = Object.entries(readiness.hazards || {}).filter(([, value]) => value.status === 'READY');
    if (active.length) {
      $('#riskBadgeSymbol').textContent = '!';
      $('#riskBadgeLabel').textContent = 'พบหลักฐานในพื้นที่';
      $('#riskBadge').className = 'status-badge is-evidence';
      $('#riskHeadline').textContent = 'พบหลักฐานภัยที่ระบุถึงพื้นที่นี้';
      $('#riskSubhead').textContent = 'ตรวจพบ ' + active.map(([key]) => hazardNames[key]).join(', ') + ' · ยังไม่มีค่าความน่าจะเป็นน้ำท่วม';
    } else if (readiness.overall === 'PARTIAL') {
      $('#riskBadgeSymbol').textContent = '~';
      $('#riskBadgeLabel').textContent = 'มีข้อมูลบางส่วน';
      $('#riskBadge').className = 'status-badge is-partial';
      $('#riskHeadline').textContent = 'มีข้อมูลพื้นที่บางส่วน';
      $('#riskSubhead').textContent = 'ยังไม่พอระบุระดับความเสี่ยงหรือเวลาที่อาจเกิดน้ำท่วม';
    }
    const list = $('#uncertaintyList');
    list.replaceChildren();
    Object.entries(readiness.hazards || {}).forEach(([key, value]) => {
      const item = document.createElement('li');
      item.textContent = (hazardNames[key] || key) + ': ' + (statusNames[value.status] || value.status) +
        ' — ' + (value.reasons || []).map((reason) => reasonNames[reason] || reason).join('; ');
      list.appendChild(item);
    });
    $('#uncertaintyText').textContent = 'ความพร้อมของหลักฐานตามประเภทภัย ณ จุดที่เลือก · ไม่มีตัวเลขพยากรณ์ที่ผ่านเกณฑ์';
  }

  function formatOutput(output, format) {
    if (!output || !output.eligible) return 'ยังประเมินไม่ได้';
    const value = output.value;
    if (format === 'time' && output.range_hours) return output.range_hours[0] + '–' + output.range_hours[1] + ' ชั่วโมง';
    if (format === 'time' && output.p50_hours != null) return output.p50_hours + ' ชั่วโมง';
    if (value == null) return 'ยังประเมินไม่ได้';
    if (format === 'boolean') return value === true ? 'มีโอกาสได้รับผลกระทบ' : 'ไม่พบการเชื่อมต่อในแบบจำลอง';
    if (format === 'meters' && typeof value === 'number') return value.toFixed(2) + ' ม.';
    if (format === 'meters' && typeof value === 'object' && value.min_m != null && value.max_m != null) return value.min_m + '–' + value.max_m + ' ม.';
    if (format === 'time' && typeof value === 'object' && value.range_hours) return value.range_hours[0] + '–' + value.range_hours[1] + ' ชั่วโมง';
    if (format === 'duration' && typeof value === 'object' && value.hours != null) return value.hours + ' ชั่วโมง';
    if (format === 'depth' && typeof value === 'object' && value.min_m != null && value.max_m != null) return value.min_m + '–' + value.max_m + ' ม.';
    return 'ผลพยากรณ์พร้อมให้ดูในรายละเอียด';
  }

  const outputLabels = {
    will_flood: 'เกิดน้ำท่วม',
    first_impact: 'เวลาเริ่มกระทบ',
    time_to_bankfull: 'เวลาถึงระดับตลิ่ง',
    peak_above_bank_m: 'ระดับสูงสุดเหนือตลิ่ง',
    time_to_peak: 'เวลาถึงจุดสูงสุด',
    duration_above_bank: 'ระยะเวลาน้ำสูงกว่าตลิ่ง',
    location_exposure: 'น้ำเข้าถึงตำแหน่ง',
    point_depth: 'ความลึก ณ จุดนี้',
  };

  function renderExpert(forecast, quality) {
    const rows = [];
    Object.keys(outputLabels).forEach((key) => {
      const output = forecast[key];
      if (!output) return;
      const status = output.eligible ? 'ผ่านเกณฑ์' : (output.reason || 'ยังประเมินไม่ได้');
      rows.push('<div class="eligibility-row"><span>' + escapeHtml(outputLabels[key]) + '</span><strong>' + escapeHtml(status) + '</strong></div>');
    });
    $('#expertEligibility').innerHTML = rows.join('');
    const sources = (quality && quality.source_registry) || [];
    const health = new Map(((quality && quality.source_health) || []).map((item) => [item.source_id, item]));
    $('#expertSources').innerHTML = sources.map((source) =>
      '<div class="source-row"><span class="source-state-dot"></span><div><strong>' + escapeHtml(source.provider) + ' · ' +
      escapeHtml((health.get(source.source_id) || {}).state || source.status) + '</strong><small>' +
      escapeHtml((health.get(source.source_id) || {}).blocker || source.blocker || '') + '</small></div></div>'
    ).join('') || '<span>ไม่มีรายการแหล่งข้อมูล</span>';
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (character) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[character]));
  }

  function setLayerPanel(open) {
    const panel = $('#layersPanel');
    panel.hidden = !open;
    if (open) $('#searchSuggestions').hidden = true;
    $('#layersButton').setAttribute('aria-expanded', String(open));
  }

  function setExpertMode(enabled) {
    state.expert = enabled;
    $('#expertButton').setAttribute('aria-pressed', String(enabled));
    $('#expertPanel').hidden = !enabled || !state.selected;
    $('#advancedLayersGroup').hidden = !enabled;
    if (enabled && state.selected) {
      const forecast = JSON.parse($('#expertEligibility').dataset.forecast || '{}');
      if (state.dataQuality) renderExpert(forecast, state.dataQuality);
      else api('/v1/data-quality').then((quality) => {
        state.dataQuality = quality;
        if (state.expert && state.selected) renderExpert(forecast, quality);
      }).catch(() => showToast('ยังอ่านทะเบียนแหล่งข้อมูลไม่ได้'));
    }
  }

  async function showRoute(direction) {
    if (!state.selected) {
      showToast('เลือกตำแหน่งบนแผนที่ก่อน');
      return;
    }
    const message = $('#routeMessage');
    message.hidden = false;
    message.textContent = 'กำลังอ่านโครงข่ายลำน้ำ…';
    try {
      const route = await api(queryLocation('/v1/network/' + direction, state.selected));
      if (!route.available) {
        message.textContent = 'ยังไม่พบลำน้ำที่ยืนยันแล้วใกล้ตำแหน่งนี้';
        return;
      }
      const length = (route.reaches || []).reduce((sum, reach) => sum + (Number(reach.length_m) || 0), 0) / 1000;
      message.textContent = (direction === 'upstream' ? 'ต้นน้ำ' : 'ปลายน้ำ') + ': โครงข่าย HydroRIVERS ' + route.reaches.length +
        ' ช่วงลำน้ำ ระยะทางตามเส้นประมาณ ' + length.toFixed(1) + ' กม. · เป็นเส้นทางตามข้อมูลต้นฉบับ ไม่ใช่ทิศทางการไหลหรือเวลาเดินทางของน้ำ ณ ตอนนี้';
    } catch (_) {
      message.textContent = 'อ่านเส้นทางลำน้ำไม่ได้ โปรดลองอีกครั้ง';
    }
  }

  function closeRouteMessage() {
    const message = $('#routeMessage');
    if (message) message.hidden = true;
  }

  async function findPlaces(query) {
    const request = ++state.searchRequest;
    try {
      const result = await api('/v1/places/search?q=' + encodeURIComponent(query));
      if (request !== state.searchRequest) return;
      const list = $('#searchSuggestions');
      list.replaceChildren();
      if (!result.items.length) {
        const message = document.createElement('div');
        message.className = 'search-empty';
        message.textContent = 'ไม่พบชื่อตำบลในข้อมูลอ้างอิง';
        list.appendChild(message);
      }
      result.items.forEach((place) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.setAttribute('role', 'option');
        button.textContent = place.label;
        button.addEventListener('click', () => selectLocation(place.lat, place.lon, place.label));
        list.appendChild(button);
      });
      if (result.total > result.items.length) {
        const note = document.createElement('div');
        note.className = 'search-empty';
        note.textContent = 'มีอีก ' + (result.total - result.items.length) + ' รายการ · เพิ่มชื่ออำเภอหรือจังหวัด';
        list.appendChild(note);
      }
      list.hidden = false;
    } catch (_) {
      showToast('ค้นหาตำบลไม่ได้ โปรดลองอีกครั้ง');
    }
  }

  $('#locationSearch').addEventListener('input', () => {
    clearTimeout(state.searchTimer);
    const query = $('#locationSearch').value.trim();
    state.searchRequest += 1;
    if (query.length < 2 || /^-?\d/.test(query)) {
      $('#searchSuggestions').hidden = true;
      return;
    }
    state.searchTimer = setTimeout(() => findPlaces(query), 220);
  });

  $('#searchForm').addEventListener('submit', (event) => {
    event.preventDefault();
    const input = $('#locationSearch').value.trim();
    if (state.selected && input === $('#selectedName').textContent) {
      $('#searchSuggestions').hidden = true;
      return;
    }
    const coordinate = input.match(/^\s*(-?\d+(?:\.\d+)?)\s*[,\s]\s*(-?\d+(?:\.\d+)?)\s*$/);
    if (coordinate) {
      selectLocation(Number(coordinate[1]), Number(coordinate[2]));
      return;
    }
    if (input.length < 2) {
      showToast('พิมพ์ชื่อตำบลอย่างน้อย 2 ตัวอักษร');
      return;
    }
    findPlaces(input);
  });

  function locateUser() {
    if (!navigator.geolocation) {
      showToast('อุปกรณ์นี้ไม่รองรับการระบุตำแหน่ง');
      return;
    }
    showToast('กำลังขอตำแหน่งจากอุปกรณ์');
    navigator.geolocation.getCurrentPosition(
      (position) => selectLocation(position.coords.latitude, position.coords.longitude),
      () => showToast('อ่านตำแหน่งไม่ได้ โปรดเลือกจุดบนแผนที่หรือพิมพ์พิกัด'),
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 },
    );
  }

  $('#locateButton').addEventListener('click', locateUser);
  $('#emptyLocateButton').addEventListener('click', locateUser);
  $('#clearSelection').addEventListener('click', clearLocation);
  $('#upstreamButton').addEventListener('click', () => showRoute('upstream'));
  $('#downstreamButton').addEventListener('click', () => showRoute('downstream'));
  $('#layersButton').addEventListener('click', () => setLayerPanel($('#layersPanel').hidden));
  $('#settingsButton').addEventListener('click', () => {
    setExpertMode(!state.expert);
    if (window.matchMedia('(max-width: 760px)').matches && state.selected) $('#locationPanel').classList.add('is-expanded');
  });
  $('#expertButton').addEventListener('click', () => setExpertMode(!state.expert));
  const sheetHandle = $('#sheetHandle');
  sheetHandle.addEventListener('pointerdown', (event) => {
    if (!window.matchMedia('(max-width: 760px)').matches) return;
    state.sheetDrag = { startY: event.clientY, startHeight: $('#locationPanel').getBoundingClientRect().height };
    sheetHandle.setPointerCapture(event.pointerId);
    $('#locationPanel').style.transition = 'none';
  });
  sheetHandle.addEventListener('pointermove', (event) => {
    if (!state.sheetDrag) return;
    const nextHeight = Math.max(250, Math.min(window.innerHeight - 12, state.sheetDrag.startHeight + state.sheetDrag.startY - event.clientY));
    $('#locationPanel').style.height = nextHeight + 'px';
  });
  const finishSheetDrag = () => {
    if (!state.sheetDrag) return;
    const height = $('#locationPanel').getBoundingClientRect().height;
    $('#locationPanel').style.transition = '';
    $('#locationPanel').style.height = '';
    $('#locationPanel').classList.toggle('is-expanded', height > window.innerHeight * .51);
    state.sheetDrag = null;
  };
  sheetHandle.addEventListener('pointerup', finishSheetDrag);
  sheetHandle.addEventListener('pointercancel', finishSheetDrag);
  $('#zoomIn').addEventListener('click', () => map.zoomIn());
  $('#zoomOut').addEventListener('click', () => map.zoomOut());
  $('#resetMap').addEventListener('click', () => {
    map.flyTo({ center: state.selected ? [state.selected.lon, state.selected.lat] : [101, 15.2], zoom: DEFAULT_ZOOM });
  });
  $('#timelineDetails').addEventListener('click', () => {
    if (state.selected) showToast('ยังไม่มีช่วงเวลาพยากรณ์ที่ผ่านเกณฑ์');
    else showToast('เลือกตำแหน่งเพื่อดูข้อมูลเฉพาะพื้นที่');
  });

  document.querySelectorAll('[data-close]').forEach((button) => button.addEventListener('click', () => {
    const target = $('#' + button.dataset.close);
    if (target.id === 'layersPanel') setLayerPanel(false);
    else target.hidden = true;
  }));
  document.querySelectorAll('[data-layer], [data-layer-shortcut]').forEach((button) => button.addEventListener('click', () => {
    const layer = button.dataset.layer || button.dataset.layerShortcut;
    if (layer === 'flow' || layer === 'network-confidence' || layer === 'gauges' || layer === 'rain') {
      state.activeLayer = state.activeLayer === layer ? null : layer;
      const flowState = document.querySelector('[data-layer-shortcut="flow"] .chip-state');
      if (flowState) flowState.textContent = state.activeLayer === 'flow' ? 'กำลังแสดง' : 'กดเพื่อแสดง';
      const gaugeState = document.querySelector('[data-layer-shortcut="gauges"] .chip-state');
      if (gaugeState) gaugeState.textContent = state.activeLayer === 'gauges' ? 'กำลังแสดง' : 'กดเพื่อแสดง';
      if (state.activeLayer) {
        scheduleLayer();
        showToast(layer === 'gauges' ? 'กำลังแสดงสถานีระดับน้ำ ThaiWater' :
          layer === 'rain' ? 'กำลังแสดงฝนตรวจวัด 24 ชั่วโมง ThaiWater' : 'กำลังแสดงโครงข่ายลำน้ำ HydroRIVERS');
      } else {
        state.layerRequest += 1;
        clearMapLayers();
        showToast('ปิดชั้นข้อมูลแล้ว');
      }
    } else {
      showToast('ชั้นข้อมูลนี้ยังไม่มีข้อมูลที่ผ่านเกณฑ์สำหรับแสดงบนแผนที่');
    }
    setLayerPanel(false);
  }));

  const resizeObserver = new ResizeObserver(() => map.resize());
  resizeObserver.observe(mapEl);
  refreshQuality();
})();
