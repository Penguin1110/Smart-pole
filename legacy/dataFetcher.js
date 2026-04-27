(() => {
  class SmartPoleDataFetcher {
    constructor(config = {}) {
      this.cwaApiKey = config.cwaApiKey || '';
      this.epaApiKey = config.epaApiKey || '';
      this.mode = config.mode || 'static';
      this.cache = {};
      this.cacheTimeout = config.cacheTimeout || 5 * 60 * 1000;
      this.maxRetries = config.maxRetries || 2;
      this.csvCache = {};
    }

    async fetchWeatherData(stationName, context = {}) {
      const cacheKey = `weather_${stationName}_${context.timestamp || 'latest'}_${this.mode}`;
      if (this.isCacheValid(cacheKey)) return this.cache[cacheKey].data;

      let data;
      if (this.mode === 'live') {
        const url = `https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0001-001?Authorization=${encodeURIComponent(this.cwaApiKey)}&locationName=${encodeURIComponent(stationName)}`;
        const payload = await this.fetchJsonWithRetry(url);
        data = this.parseWeatherData(payload);
      } else {
        data = await this.fetchLocalCwaWeather(context);
      }

      this.setCache(cacheKey, data);
      return data;
    }

    async fetchAirQualityData(siteName, context = {}) {
      const cacheKey = `aq_${siteName}_${context.timestamp || 'latest'}_${this.mode}`;
      if (this.isCacheValid(cacheKey)) return this.cache[cacheKey].data;

      let data;
      if (this.mode === 'live') {
        const url = `https://data.moenv.gov.tw/api/v2/aqx_p_02?api_key=${encodeURIComponent(this.epaApiKey)}&filters=SiteName,EQ,${encodeURIComponent(siteName)}`;
        const payload = await this.fetchJsonWithRetry(url);
        data = this.parseAirQualityData(payload.records?.[0]);
      } else {
        data = window.SmartPoleStaticData.buildStaticAirQualitySnapshot(context.timestamp, context.stationConfig, context.pm25, context.row);
      }

      this.setCache(cacheKey, data);
      return data;
    }

    async enrichSmartPoleData(smartPoleData, stationId = 'SP-05') {
      const stationConfig = window.SmartPoleStaticData.STATION_MAPPING[stationId] || window.SmartPoleStaticData.STATION_MAPPING['SP-05'];
      const pm25 = window.SmartPoleStaticData.normalizeNumber(smartPoleData.pm25);
      const timestamp = smartPoleData.timestamp;

      const [weather, airQuality] = await Promise.all([
        this.fetchWeatherData(stationConfig.weatherStation, { timestamp, stationConfig, pm25 }),
        this.fetchAirQualityData(stationConfig.airQualityStation, { timestamp, stationConfig, pm25, row: smartPoleData.rawRow })
      ]);

      return {
        station: stationConfig,
        smartPole: {
          stationId,
          stationName: stationConfig.smartPoleName,
          pm25,
          rawPm25: window.SmartPoleStaticData.normalizeNumber(smartPoleData.rawPm25),
          timestamp
        },
        weather,
        airQuality,
        timeFeatures: window.SmartPoleStaticData.calculateTimeFeatures(timestamp),
        spatialFeatures: {
          nearbyStations: window.SmartPoleStaticData.getNearbyStations(smartPoleData.rawRow || {}, stationId)
        }
      };
    }

    async fetchLocalCwaWeather(context) {
      const fallback = window.SmartPoleStaticData.buildStaticWeatherSnapshot(context.timestamp, context.stationConfig, context.pm25);
      const station = window.SmartPoleStaticData.CWA_STATIONS[context.stationConfig?.weatherStationKey];
      if (!station || !context.timestamp) return fallback;

      const date = this.formatLocalDate(context.timestamp);
      const rows = await this.loadCwaCsv(station, date);
      const hourKey = this.toCwaObsHour(context.timestamp);
      const matched = rows.find((row) => row.ObsTime === hourKey);
      if (!matched) return fallback;

      const temperature = window.SmartPoleStaticData.normalizeNumber(matched.Temperature);
      const humidity = window.SmartPoleStaticData.normalizeNumber(matched.RH);
      const windSpeed = window.SmartPoleStaticData.normalizeNumber(matched.WS);
      const windDirection = window.SmartPoleStaticData.normalizeNumber(matched.WD);
      const rainfall = window.SmartPoleStaticData.normalizeNumber(matched.Precp);
      const pressure = window.SmartPoleStaticData.normalizeNumber(matched.StnPres);

      return {
        stationName: station.name,
        stationId: station.id,
        stationLat: station.lat,
        stationLng: station.lng,
        observationTime: `${date} ${hourKey}:00`,
        temperature: temperature ?? fallback.temperature,
        humidity: humidity ?? fallback.humidity,
        windSpeed: windSpeed ?? fallback.windSpeed,
        windDirection: windDirection ?? fallback.windDirection,
        rainfall: rainfall ?? fallback.rainfall,
        pressure: pressure ?? fallback.pressure,
        source: `CWA CSV (${station.id})`
      };
    }

    async loadCwaCsv(station, date) {
      const cacheKey = `${station.id}_${date}`;
      if (!this.csvCache[cacheKey]) {
        const path = `./CWA_Weather_Final/${station.folder}/${station.filePrefix}-${date}.csv`;
        this.csvCache[cacheKey] = fetch(encodeURI(path))
          .then((response) => {
            if (!response.ok) return [];
            return response.text();
          })
          .then((text) => this.parseCwaCsv(text))
          .catch(() => []);
      }
      return this.csvCache[cacheKey];
    }

    parseCwaCsv(text) {
      const lines = text.trim().split(/\r?\n/);
      if (lines.length < 3) return [];
      const headers = this.parseCsvLine(lines[1]);
      return lines.slice(2)
        .map((line) => {
          const cells = this.parseCsvLine(line);
          return headers.reduce((row, header, index) => {
            row[header] = cells[index] ?? '';
            return row;
          }, {});
        })
        .filter((row) => row.ObsTime);
    }

    parseCsvLine(line) {
      const cells = [];
      let current = '';
      let inQuotes = false;
      for (let index = 0; index < line.length; index += 1) {
        const char = line[index];
        const next = line[index + 1];
        if (char === '"' && next === '"') {
          current += '"';
          index += 1;
        } else if (char === '"') {
          inQuotes = !inQuotes;
        } else if (char === ',' && !inQuotes) {
          cells.push(current);
          current = '';
        } else {
          current += char;
        }
      }
      cells.push(current);
      return cells;
    }

    formatLocalDate(timestamp) {
      const date = new Date(timestamp);
      const yyyy = date.getFullYear();
      const mm = String(date.getMonth() + 1).padStart(2, '0');
      const dd = String(date.getDate()).padStart(2, '0');
      return `${yyyy}-${mm}-${dd}`;
    }

    toCwaObsHour(timestamp) {
      const date = new Date(timestamp);
      return String(Math.min(date.getHours() + 1, 24)).padStart(2, '0');
    }

    parseWeatherData(payload) {
      const station = payload?.records?.Station?.[0] || payload?.records?.location?.[0];
      const weatherElements = station?.WeatherElement || station?.weatherElement || [];
      return {
        stationName: station?.StationName || station?.locationName || '--',
        stationId: station?.StationId || station?.stationId || null,
        observationTime: station?.ObsTime?.DateTime || station?.time?.obsTime || null,
        temperature: this.findElement(weatherElements, 'TEMP', 'T'),
        humidity: this.findElement(weatherElements, 'HUMD', 'RH'),
        windSpeed: this.findElement(weatherElements, 'WDSD', 'WS'),
        windDirection: this.findElement(weatherElements, 'WDIR', 'WD'),
        rainfall: this.findElement(weatherElements, 'RAIN'),
        pressure: this.findElement(weatherElements, 'PRES'),
        source: 'cwa-live'
      };
    }

    parseAirQualityData(record) {
      if (!record) return null;
      return {
        siteName: record.SiteName,
        county: record.County,
        publishTime: record.PublishTime,
        pollutant: record.Pollutant,
        status: record.Status,
        aqi: window.SmartPoleStaticData.normalizeNumber(record.AQI),
        pm25: window.SmartPoleStaticData.normalizeNumber(record['PM2.5']),
        pm10: window.SmartPoleStaticData.normalizeNumber(record.PM10),
        o3: window.SmartPoleStaticData.normalizeNumber(record.O3),
        no2: window.SmartPoleStaticData.normalizeNumber(record.NO2),
        so2: window.SmartPoleStaticData.normalizeNumber(record.SO2),
        co: window.SmartPoleStaticData.normalizeNumber(record.CO),
        source: 'epa-live'
      };
    }

    findElement(elements, ...keys) {
      const matched = elements.find((element) => keys.includes(element.elementName) || keys.includes(element.ElementName));
      const value = matched?.elementValue ?? matched?.ElementValue;
      return window.SmartPoleStaticData.normalizeNumber(value);
    }

    async fetchJsonWithRetry(url) {
      let lastError;
      for (let attempt = 0; attempt <= this.maxRetries; attempt += 1) {
        try {
          const response = await fetch(url);
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          return await response.json();
        } catch (error) {
          lastError = error;
          if (attempt < this.maxRetries) {
            await new Promise((resolve) => setTimeout(resolve, 500 * (attempt + 1)));
          }
        }
      }
      throw lastError;
    }

    isCacheValid(key) {
      return Boolean(this.cache[key]) && (Date.now() - this.cache[key].timestamp) < this.cacheTimeout;
    }

    setCache(key, data) {
      this.cache[key] = { data, timestamp: Date.now() };
    }
  }

  window.SmartPoleDataFetcher = SmartPoleDataFetcher;
})();
