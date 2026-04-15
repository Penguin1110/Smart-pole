(() => {
  const CWA_STATIONS = {
    taipei: {
      id: '466920',
      name: '臺北',
      folder: '466920_臺北',
      filePrefix: '466920',
      lat: 25.03758,
      lng: 121.51453
    },
    xinyi: {
      id: 'C0AC70',
      name: '信義',
      folder: 'C0A9C0_信義',
      filePrefix: 'C0AC70',
      lat: 25.037822,
      lng: 121.564597
    },
    songshan: {
      id: 'C0AH70',
      name: '松山',
      folder: 'C0AH70_松山',
      filePrefix: 'C0AH70',
      lat: 25.0487,
      lng: 121.55042
    },
    wenshan: {
      id: 'C0AC80',
      name: '文山',
      folder: 'C0AC80_文山',
      filePrefix: 'C0AC80',
      lat: 25.0235,
      lng: 121.57528
    },
    neihu: {
      id: 'C0A9F0',
      name: '內湖',
      folder: 'C0A9F0_內湖',
      filePrefix: 'C0A9F0',
      lat: 25.079422,
      lng: 121.5745
    },
    yonghe: {
      id: 'C0AH10',
      name: '永和',
      folder: 'C0AH10_永和',
      filePrefix: 'C0AH10',
      lat: 25.01125,
      lng: 121.508111
    }
  };

  const STATION_MAPPING = {
    'SP-05': {
      smartPoleName: 'SP-05 松菸',
      city: '臺北市',
      weatherStationKey: 'songshan',
      weatherStation: '松山',
      airQualityStation: '松山',
      lat: 25.044,
      lng: 121.5598,
      nearbyKeys: ['songshan', 'zhongshan', 'guting', 'shilin'],
      profile: 'taipei-urban'
    },
    'SP-01': {
      smartPoleName: 'SP-01',
      city: '臺北市',
      weatherStationKey: 'taipei',
      weatherStation: '臺北',
      airQualityStation: '中山',
      lat: 25.056,
      lng: 121.533,
      nearbyKeys: ['zhongshan', 'songshan', 'guting', 'shilin'],
      profile: 'taipei-urban'
    },
    'SP-02': {
      smartPoleName: 'SP-02',
      city: '臺北市',
      weatherStationKey: 'taipei',
      weatherStation: '臺北',
      airQualityStation: '士林',
      lat: 25.088,
      lng: 121.525,
      nearbyKeys: ['shilin', 'zhongshan', 'yangming', 'guting'],
      profile: 'taipei-basin'
    },
    A1: {
      smartPoleName: 'A1 左營',
      city: '高雄市',
      weatherStationKey: 'taipei',
      weatherStation: '臺北',
      airQualityStation: '左營',
      lat: 22.685,
      lng: 120.308,
      nearbyKeys: [],
      profile: 'kaohsiung-harbor'
    }
  };

  const AQ_LABELS = [
    { upper: 12, label: '良好', color: '#34d399' },
    { upper: 35, label: '普通', color: '#fbbf24' },
    { upper: 54, label: '對敏感族群不健康', color: '#fb923c' },
    { upper: 150, label: '對所有族群不健康', color: '#ef4444' },
    { upper: Infinity, label: '非常不健康', color: '#a855f7' }
  ];

  const PROFILE_FACTORS = {
    'taipei-urban': { tempBase: 20, humidityBase: 73, windBase: 2.4, rainBias: 0.18 },
    'taipei-basin': { tempBase: 19, humidityBase: 76, windBase: 2.1, rainBias: 0.22 },
    'kaohsiung-harbor': { tempBase: 25, humidityBase: 69, windBase: 3.8, rainBias: 0.1 }
  };

  function normalizeNumber(value) {
    if (value === null || value === undefined || value === '' || value === '--' || value === 'X') return null;
    const num = Number(value);
    return Number.isFinite(num) ? num : null;
  }

  function round(value, digits = 1) {
    if (!Number.isFinite(value)) return null;
    const base = 10 ** digits;
    return Math.round(value * base) / base;
  }

  function hashString(input) {
    let hash = 0;
    for (let i = 0; i < input.length; i += 1) {
      hash = ((hash << 5) - hash) + input.charCodeAt(i);
      hash |= 0;
    }
    return Math.abs(hash);
  }

  function seasonalOffset(month) {
    if ([12, 1, 2].includes(month)) return -3.5;
    if ([3, 4, 5].includes(month)) return 1.5;
    if ([6, 7, 8].includes(month)) return 7;
    return 3;
  }

  function getAQStatus(pm25) {
    const value = normalizeNumber(pm25);
    if (value === null) return { label: '--', color: '#64748b', aqiApprox: null };
    const matched = AQ_LABELS.find((item) => value < item.upper) || AQ_LABELS[AQ_LABELS.length - 1];
    return { label: matched.label, color: matched.color, aqiApprox: Math.round(Math.max(0, value * 2.2)) };
  }

  function calculateTimeFeatures(timestamp) {
    const date = new Date(timestamp);
    const hour = date.getHours();
    const month = date.getMonth() + 1;
    const day = date.getDay();
    const season = month <= 2 || month === 12 ? '冬季' : month <= 5 ? '春季' : month <= 8 ? '夏季' : '秋季';
    return {
      iso: date.toISOString(),
      hour,
      dayOfWeek: day,
      dayName: ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六'][day],
      dayOfMonth: date.getDate(),
      month,
      season,
      isWeekend: day === 0 || day === 6,
      isRushHour: [7, 8, 9, 17, 18, 19].includes(hour),
      isNight: hour >= 22 || hour <= 5
    };
  }

  function buildStaticWeatherSnapshot(timestamp, stationConfig, pm25Value) {
    const date = new Date(timestamp);
    const profile = PROFILE_FACTORS[stationConfig.profile] || PROFILE_FACTORS['taipei-urban'];
    const hour = date.getHours();
    const month = date.getMonth() + 1;
    const seed = hashString(`${timestamp}-${stationConfig.weatherStation}`);
    const pm25 = normalizeNumber(pm25Value) ?? 12;
    const dayWave = Math.sin((hour / 24) * Math.PI * 2 - Math.PI / 2);
    const humidityWave = Math.cos((hour / 24) * Math.PI * 2);
    const gust = ((seed % 7) - 3) * 0.12;
    const rainTrigger = ((seed % 100) / 100) < profile.rainBias && humidityWave > 0;

    const temperature = round(profile.tempBase + seasonalOffset(month) + dayWave * 5.5 - (pm25 / 50) + gust, 1);
    const humidity = round(Math.min(96, Math.max(45, profile.humidityBase - dayWave * 10 + (pm25 / 6))), 0);
    const windSpeed = round(Math.max(0.4, profile.windBase + Math.abs(humidityWave) * 1.6 - (pm25 / 45) + gust), 1);
    const windDirection = round((seed + hour * 18) % 360, 0);
    const rainfall = round(rainTrigger ? Math.max(0, (humidity - 72) * 0.08) : 0, 1);
    const pressure = round(1007 + humidityWave * 4 - rainfall * 0.6 + (month <= 2 ? 4 : 0), 1);
    const station = CWA_STATIONS[stationConfig.weatherStationKey] || null;

    return {
      stationName: station?.name || stationConfig.weatherStation,
      stationId: station?.id || null,
      stationLat: station?.lat ?? null,
      stationLng: station?.lng ?? null,
      observationTime: timestamp,
      temperature,
      humidity,
      windSpeed,
      windDirection,
      rainfall,
      pressure,
      source: 'static-estimate'
    };
  }

  function buildStaticAirQualitySnapshot(timestamp, stationConfig, pm25Value, row = {}) {
    const seed = hashString(`${timestamp}-${stationConfig.airQualityStation}`);
    const pm25 = normalizeNumber(pm25Value);
    const neighbors = ['songshan', 'zhongshan', 'wanhua', 'guting', 'shilin', 'yangming']
      .map((key) => normalizeNumber(row[key]))
      .filter((value) => value !== null);
    const regionalAvg = neighbors.length ? neighbors.reduce((sum, value) => sum + value, 0) / neighbors.length : pm25 ?? 12;
    const base = pm25 ?? regionalAvg ?? 12;
    const drift = ((seed % 9) - 4) * 0.18;
    const status = getAQStatus(base);

    return {
      siteName: stationConfig.airQualityStation,
      county: stationConfig.city,
      publishTime: timestamp,
      pollutant: base >= 35 ? 'PM2.5' : '臭氧/細懸浮微粒',
      status: status.label,
      aqi: status.aqiApprox,
      pm25: round(base, 1),
      pm10: round(base * 1.45 + 6 + drift, 1),
      o3: round(Math.max(8, 28 + (seed % 11) - base * 0.32), 1),
      no2: round(Math.max(4, 11 + base * 0.38 + drift), 1),
      so2: round(Math.max(1, 2.5 + base * 0.08), 1),
      co: round(Math.max(0.1, 0.28 + base * 0.018), 2),
      source: 'static-estimate'
    };
  }

  function getNearbyStations(row, stationId) {
    const stationConfig = STATION_MAPPING[stationId] || STATION_MAPPING['SP-05'];
    const pm25 = normalizeNumber(row.sp05_hourly) ?? normalizeNumber(row.sp05_raw);
    const distanceMap = { songshan: 1.7, zhongshan: 4.1, guting: 4.8, shilin: 7.2, wanhua: 6.1, yangming: 15.4 };
    const labelMap = { songshan: '松山', zhongshan: '中山', guting: '古亭', shilin: '士林', wanhua: '萬華', yangming: '陽明' };

    return stationConfig.nearbyKeys
      .map((key) => {
        const neighborValue = normalizeNumber(row[key]);
        return {
          key,
          siteName: labelMap[key] || key,
          distanceKm: distanceMap[key] ?? null,
          pm25: neighborValue,
          diffFromPole: pm25 !== null && neighborValue !== null ? round(pm25 - neighborValue, 1) : null
        };
      })
      .filter((item) => item.pm25 !== null);
  }

  window.SmartPoleStaticData = {
    CWA_STATIONS,
    STATION_MAPPING,
    calculateTimeFeatures,
    buildStaticWeatherSnapshot,
    buildStaticAirQualitySnapshot,
    getNearbyStations,
    getAQStatus,
    normalizeNumber,
    round
  };
})();
