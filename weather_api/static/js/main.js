// Variables globales
let tempChart = null;

// Variables para gestión de alertas
let userAlertConfig = {
    notifications: true,
    thresholds: {
        temp_high: 35,
        temp_low: 0,
        wind: 15,
        humidity: 90
    }
};

// Add weather description translations
const weatherTranslations = {
    // Condiciones de cielo
    'clear sky': 'Cielo despejado',
    'few clouds': 'Algunas nubes',
    'scattered clouds': 'Nubes dispersas',
    'broken clouds': 'Nubosidad parcial',
    'overcast clouds': 'Cielo cubierto',

    // Lluvia
    'light rain': 'Lluvia débil',
    'moderate rain': 'Lluvia moderada',
    'heavy rain': 'Lluvia fuerte',
    'light intensity drizzle': 'Llovizna débil',
    'drizzle': 'Llovizna',
    'moderate drizzle': 'Llovizna moderada',
    'heavy intensity drizzle': 'Llovizna fuerte',
    'light intensity shower rain': 'Chubasco débil',
    'shower rain': 'Chubasco',
    'heavy intensity shower rain': 'Chubasco fuerte',
    'ragged shower rain': 'Chubasco irregular',

    // Nieve
    'light snow': 'Nevada débil',
    'snow': 'Nevada',
    'moderate snow': 'Nevada moderada',
    'heavy snow': 'Nevada intensa',
    'light shower snow': 'Chubasco de nieve débil',
    'shower snow': 'Chubasco de nieve',
    'heavy shower snow': 'Chubasco de nieve intenso',
    'sleet': 'Aguanieve',
    'light shower sleet': 'Chubasco de aguanieve débil',
    'shower sleet': 'Chubasco de aguanieve',
    'light rain and snow': 'Lluvia y nieve débil',
    'rain and snow': 'Lluvia y nieve',

    // Tormentas
    'thunderstorm': 'Tormenta eléctrica',
    'thunderstorm with light rain': 'Tormenta con lluvia débil',
    'thunderstorm with rain': 'Tormenta con lluvia',
    'thunderstorm with heavy rain': 'Tormenta con lluvia fuerte',

    // Fenómenos de visibilidad reducida
    'mist': 'Neblina',
    'fog': 'Niebla',
    'haze': 'Calima',
    'smoke': 'Humo',
    'dust': 'Polvo en suspensión',
    'sand': 'Arena en suspensión',
    'ash': 'Ceniza volcánica',

    // Otros fenómenos
    'squall': 'Turbonada',
    'tornado': 'Tornado'
};

// Function to translate weather description
function translateWeatherDescription(description) {
    const lowerDesc = description.toLowerCase();
    return weatherTranslations[lowerDesc] || description;
}

// Cargar ciudades disponibles
async function loadCities() {
    try {
        const response = await fetch('/api/cities');
        const cities = await response.json();

        const citySelector = document.getElementById('city-selector');
        cities.forEach(city => {
            const option = document.createElement('option');
            option.value = city;
            option.textContent = city;
            citySelector.appendChild(option);
        });

        // Evento para cambiar de ciudad
        citySelector.addEventListener('change', (e) => {
            const selectedCity = e.target.value;
            if (selectedCity) {
                loadCurrentWeather(selectedCity);
                loadHistoricalData(selectedCity, document.getElementById('history-days').value);
                loadForecast(selectedCity);
            }
        });
    } catch (error) {
        console.error('Error cargando ciudades:', error);
        document.getElementById('city-selector').innerHTML = '<option value="">Error al cargar ciudades</option>';
    }
}

// Cargar clima actual
async function loadCurrentWeather(city) {
    try {
        const response = await fetch(`/api/current/${city}`);

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();

        // Verificar si los datos son demasiado antiguos (más de 1 hora)
        const lastUpdate = new Date(data.last_check);
        const now = new Date();
        const hoursDiff = Math.abs(now - lastUpdate) / 36e5; // diferencia en horas

        if (hoursDiff > 1) {
            console.warn(`Los datos del clima actual tienen ${hoursDiff.toFixed(1)} horas de antigüedad`);
            // Forzar actualización si los datos son muy antiguos
            await fetch(`/api/current/${city}?force_update=true`);
        }

        const container = document.getElementById('current-weather');
        const translatedDescription = translateWeatherDescription(data.description);

        container.innerHTML = `
            <div class="d-flex align-items-center">
                <div>
                    <img src="https://openweathermap.org/img/wn/${data.icon}@2x.png" alt="${translatedDescription}" class="weather-icon">
                </div>
                <div class="ms-3">
                    <h2>${data.temp.toFixed(1)}°C</h2>
                    <p class="mb-0">${translatedDescription}</p>
                </div>
            </div>
            <div class="row mt-3">
                <div class="col-6">
                    <p><strong>Sensación:</strong> ${data.feels_like.toFixed(1)}°C</p>
                    <p><strong>Humedad:</strong> ${data.humidity}%</p>
                </div>
                <div class="col-6">
                    <p><strong>Presión:</strong> ${data.pressure} hPa</p>
                    <p><strong>Viento:</strong> ${data.wind_speed} m/s</p>
                </div>
            </div>
            <div class="text-muted small mt-2">
                Fecha y hora: ${now.toLocaleString()}<br>
                Última verificación: ${new Date(data.last_check).toLocaleString()}
            </div>
        `;

        // Cargar también el pronóstico por hora
        loadHourlyForecast(city);

    } catch (error) {
        console.error('Error cargando clima actual:', error);
        document.getElementById('current-weather').innerHTML =
            '<p class="text-center text-danger">Error al cargar los datos actuales. Por favor, intenta nuevamente.</p>';
    }
}

// Cargar pronóstico por hora
async function loadHourlyForecast(city) {
    try {
        const response = await fetch(`/api/forecast/${city}`);

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();

        const container = document.getElementById('hourly-forecast');

        if (!data.forecast || data.forecast.length === 0) {
            container.innerHTML = '<p class="text-center text-muted">No hay datos de pronóstico por hora disponibles</p>';
            return;
        }

        console.log(`Recibidos ${data.forecast.length} pronósticos horarios`);

        let hourlyHTML = '';

        // Crear HTML para cada hora
        data.forecast.forEach((item, index) => {
            const date = new Date(item.datetime);
            const hour = date.getHours().toString().padStart(2, '0') + ':00';
            const dayMonth = date.toLocaleDateString('es-ES', { day: 'numeric', month: 'short' });

            hourlyHTML += `
                <div class="hourly-item">
                    <div class="small fw-bold">${hour}</div>
                    <div class="small text-muted">${dayMonth}</div>
                    <img src="https://openweathermap.org/img/wn/${item.icon}.png" alt="${item.description}" width="40">
                    <div><strong>${item.temp.toFixed(1)}°C</strong></div>
                    <div class="small text-muted">${item.wind_speed} m/s</div>
                </div>
            `;
        });

        container.innerHTML = hourlyHTML;

    } catch (error) {
        console.error('Error cargando pronóstico por hora:', error);
        document.getElementById('hourly-forecast').innerHTML =
            '<p class="text-center text-danger">Error al cargar el pronóstico por hora</p>';
    }
}

// Cargar datos históricos
async function loadHistoricalData(city, days = 7) {
    try {
        const response = await fetch(`/api/historical/${city}?days=${days}`);

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();

        if (!data.data || data.data.length === 0) {
            document.getElementById('temp-chart').parentNode.innerHTML =
                '<p class="text-center text-muted">No hay datos disponibles para esta ciudad</p>';
            return;
        }

        // Ordenar los datos por fecha de más antigua a más reciente
        const sortedData = data.data.sort((a, b) => new Date(a.date) - new Date(b.date));

        // Formatear fechas para mostrar
        const labels = sortedData.map(d => {
            const date = new Date(d.date);
            return date.toLocaleDateString('es-ES', {
                day: '2-digit',
                month: '2-digit',
                year: 'numeric'
            });
        });

        const category = document.getElementById('history-category').value;

        let datasets = [];
        let yAxisTitle = '';

        switch (category) {
            case 'temperature':
                datasets = [
                    {
                        label: 'Temp. Media',
                        data: sortedData.map(d => d.temp_avg),
                        borderColor: 'rgba(54, 162, 235, 1)',
                        backgroundColor: 'rgba(54, 162, 235, 0.2)',
                        fill: false,
                        tension: 0.1
                    },
                    {
                        label: 'Temp. Máxima',
                        data: sortedData.map(d => d.temp_max),
                        borderColor: 'rgba(255, 99, 132, 1)',
                        backgroundColor: 'rgba(255, 99, 132, 0.2)',
                        fill: false,
                        tension: 0.1
                    },
                    {
                        label: 'Temp. Mínima',
                        data: sortedData.map(d => d.temp_min),
                        borderColor: 'rgba(75, 192, 192, 1)',
                        backgroundColor: 'rgba(75, 192, 192, 0.2)',
                        fill: false,
                        tension: 0.1
                    }
                ];
                yAxisTitle = 'Temperatura (°C)';
                break;
            case 'precipitation':
                datasets = [{
                    label: 'Precipitación',
                    data: sortedData.map(d => d.precipitation || 0),
                    borderColor: 'rgba(0, 123, 255, 1)',
                    backgroundColor: 'rgba(0, 123, 255, 0.2)',
                    fill: true,
                    tension: 0.1
                }];
                yAxisTitle = 'Precipitación (mm)';
                break;
            case 'wind':
                datasets = [{
                    label: 'Velocidad del Viento',
                    data: sortedData.map(d => d.wind_speed || 0),
                    borderColor: 'rgba(255, 193, 7, 1)',
                    backgroundColor: 'rgba(255, 193, 7, 0.2)',
                    fill: true,
                    tension: 0.1
                }];
                yAxisTitle = 'Velocidad del Viento (m/s)';
                break;
            case 'humidity':
                datasets = [{
                    label: 'Humedad',
                    data: sortedData.map(d => d.humidity_avg || 0),
                    borderColor: 'rgba(23, 162, 184, 1)',
                    backgroundColor: 'rgba(23, 162, 184, 0.2)',
                    fill: true,
                    tension: 0.1
                }];
                yAxisTitle = 'Humedad (%)';
                break;
        }

        const ctx = document.getElementById('temp-chart').getContext('2d');

        // Destruir gráfico anterior si existe
        if (tempChart) {
            tempChart.destroy();
        }

        tempChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: datasets
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                scales: {
                    y: {
                        beginAtZero: category === 'precipitation' || category === 'wind',
                        title: {
                            display: true,
                            text: yAxisTitle
                        }
                    },
                    x: {
                        title: {
                            display: true,
                            text: 'Fecha'
                        },
                        ticks: {
                            callback: function(value, index, values) {
                                const today = new Date().toLocaleDateString('es-ES', {
                                    day: '2-digit',
                                    month: '2-digit',
                                    year: 'numeric'
                                });
                                const label = this.getLabelForValue(value);
                                if (label === today) {
                                    return [label, 'Hoy'];
                                }
                                return label;
                            },
                            color: function(context) {
                                const today = new Date().toLocaleDateString('es-ES', {
                                    day: '2-digit',
                                    month: '2-digit',
                                    year: 'numeric'
                                });
                                const label = context.chart.data.labels[context.index];
                                if (label === today) {
                                    return '#dc3545';
                                }
                                return Chart.defaults.color;
                            }
                        }
                    }
                },
                plugins: {
                    tooltip: {
                        mode: 'index',
                        intersect: false
                    },
                    legend: {
                        position: 'top',
                    }
                }
            }
        });
    } catch (error) {
        console.error('Error cargando datos históricos:', error);
        document.getElementById('temp-chart').parentNode.innerHTML =
            '<p class="text-center text-danger">Error al cargar los datos históricos</p>';
    }
}

// Event listener para cambios en el selector de categoría
document.getElementById('history-category').addEventListener('change', function() {
    const selectedCity = document.getElementById('city-selector').value;
    if (selectedCity) {
        loadHistoricalData(selectedCity, document.getElementById('history-days').value);
    }
});

// Cargar pronóstico diario
async function loadForecast(city) {
    try {
        const response = await fetch(`/api/forecast/${city}`);

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();

        const container = document.getElementById('forecast-container');

        if (!data.forecast || data.forecast.length === 0) {
            container.innerHTML = '<p class="text-center text-muted">No hay datos de pronóstico disponibles</p>';
            return;
        }

        console.log(`Recibidos ${data.forecast.length} pronósticos para agrupar por días`);

        // Agrupar pronósticos por día y calcular min/max
        const dailyForecasts = {};

        data.forecast.forEach(item => {
            const date = item.datetime.split(' ')[0];
            const hour = parseInt(item.datetime.split(' ')[1].split(':')[0]);

            if (!dailyForecasts[date]) {
                dailyForecasts[date] = {
                    forecasts: [],
                    min_temp: Infinity,
                    max_temp: -Infinity,
                    avg_humidity: 0,
                    avg_wind: 0,
                    precipitation_chance: 0,
                    main_weather: null,
                    main_icon: null,
                    main_description: null
                };
            }

            dailyForecasts[date].forecasts.push(item);

            // Update min/max temperatures
            dailyForecasts[date].min_temp = Math.min(dailyForecasts[date].min_temp, item.temp);
            dailyForecasts[date].max_temp = Math.max(dailyForecasts[date].max_temp, item.temp);

            // Accumulate for averages
            dailyForecasts[date].avg_humidity += item.humidity;
            dailyForecasts[date].avg_wind += item.wind_speed;

            // Find the forecast closest to noon (12:00) for main weather
            if (!dailyForecasts[date].main_weather || Math.abs(hour - 12) < Math.abs(parseInt(dailyForecasts[date].main_weather.datetime.split(' ')[1].split(':')[0]) - 12)) {
                dailyForecasts[date].main_weather = item;
                dailyForecasts[date].main_icon = item.icon;
                dailyForecasts[date].main_description = translateWeatherDescription(item.description);
            }
        });

        // Calculate averages and format data
        Object.keys(dailyForecasts).forEach(date => {
            const dayData = dailyForecasts[date];
            const forecastCount = dayData.forecasts.length;

            dayData.avg_humidity = Math.round(dayData.avg_humidity / forecastCount);
            dayData.avg_wind = (dayData.avg_wind / forecastCount).toFixed(1);

            // Calculate precipitation chance (simplified)
            const rainyForecasts = dayData.forecasts.filter(f =>
                f.description.toLowerCase().includes('rain') ||
                f.description.toLowerCase().includes('drizzle') ||
                f.description.toLowerCase().includes('shower')
            );
            dayData.precipitation_chance = Math.round((rainyForecasts.length / forecastCount) * 100);
        });

        // Convert to array and sort by date
        const forecasts = Object.entries(dailyForecasts)
            .map(([date, data]) => ({
                date,
                ...data
            }))
            .sort((a, b) => new Date(a.date) - new Date(b.date));

        console.log(`Agrupados en ${forecasts.length} días únicos`);

        // Create HTML for each day
        let forecastHTML = '<div class="row">';
        forecasts.forEach(day => {
            const date = new Date(day.date);
            const dayName = date.toLocaleDateString('es-ES', { weekday: 'long' });
            const formattedDate = date.toLocaleDateString('es-ES', { day: 'numeric', month: 'long' });

            // Only show future forecasts
            if (date >= new Date()) {
                console.log(`Mostrando pronóstico para ${date.toISOString()}`);
                forecastHTML += `
                    <div class="col-md-3 col-sm-6 mb-4">
                        <div class="card h-100">
                            <div class="card-header bg-light">
                                <h6 class="mb-0">${dayName}</h6>
                                <small class="text-muted">${formattedDate}</small>
                            </div>
                            <div class="card-body p-3">
                                <div class="text-center mb-3">
                                    <img src="https://openweathermap.org/img/wn/${day.main_icon}@2x.png"
                                         alt="${day.main_description}"
                                         style="width: 80px; height: 80px;">
                                    <h5 class="mt-2">${day.main_description}</h5>
                                </div>
                                <div class="row text-center">
                                    <div class="col-6">
                                        <div class="small text-muted">Máxima</div>
                                        <h4 class="text-danger">${day.max_temp.toFixed(1)}°C</h4>
                                    </div>
                                    <div class="col-6">
                                        <div class="small text-muted">Mínima</div>
                                        <h4 class="text-primary">${day.min_temp.toFixed(1)}°C</h4>
                                    </div>
                                </div>
                                <div class="mt-3">
                                    <div class="d-flex justify-content-between small mb-2">
                                        <span>Humedad:</span>
                                        <span>${day.avg_humidity}%</span>
                                    </div>
                                    <div class="d-flex justify-content-between small mb-2">
                                        <span>Viento:</span>
                                        <span>${day.avg_wind} m/s</span>
                                    </div>
                                    <div class="d-flex justify-content-between small">
                                        <span>Prob. de lluvia:</span>
                                        <span>${day.precipitation_chance}%</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                `;
            } else {
                console.log(`Omitiendo pronóstico pasado para ${date.toISOString()}`);
            }
        });
        forecastHTML += '</div>';

        container.innerHTML = forecastHTML;
    } catch (error) {
        console.error('Error cargando pronóstico:', error);
        document.getElementById('forecast-container').innerHTML =
            '<p class="text-center text-danger">Error al cargar el pronóstico</p>';
    }
}

// Función para validar y formatear valores de umbral
function validateThresholdValue(value, defaultValue) {
    if (value === undefined || value === null || value === '') {
        return defaultValue;
    }
    const numValue = parseFloat(value);
    if (isNaN(numValue) || numValue < 0) {
        return defaultValue;
    }
    return numValue;
}

// Cargar alertas
async function loadAlerts(forceCustomThresholds = false) {
    try {
        const currentCity = document.getElementById('city-selector').value;
        if (!currentCity) {
            document.getElementById('alerts-container').innerHTML =
                '<p class="text-center text-muted">Selecciona una ciudad para ver las alertas</p>';
            return;
        }

        // Obtener y validar los valores de los umbrales
        const tempHigh = validateThresholdValue(document.getElementById('temp-high').value, DEFAULT_ALERT_THRESHOLDS.temp_high);
        const tempLow = validateThresholdValue(document.getElementById('temp-low').value, DEFAULT_ALERT_THRESHOLDS.temp_low);
        const windSpeed = validateThresholdValue(document.getElementById('wind-speed').value, DEFAULT_ALERT_THRESHOLDS.wind_speed);
        const humidity = validateThresholdValue(document.getElementById('humidity').value, DEFAULT_ALERT_THRESHOLDS.humidity);

        // Asegurarse de que tempLow sea menor que tempHigh
        const finalTempLow = Math.min(tempLow, tempHigh - 1);

        let url = `/api/alerts/custom?temp_high=${tempHigh}&temp_low=${finalTempLow}&wind=${windSpeed}&humidity=${humidity}`;

        const response = await fetch(url);

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        const container = document.getElementById('alerts-container');

        if (data.status === 'error') {
            throw new Error(data.message || 'Error al cargar alertas');
        }

        // Filtrar alertas solo para la ciudad actual
        const cityAlerts = data.alerts.filter(alert => alert.city === currentCity);

        if (cityAlerts.length === 0) {
            container.innerHTML = '<p class="text-center text-success">No hay alertas activas para esta ciudad</p>';
        } else {
            let alertsHTML = '';

            cityAlerts.forEach(alert => {
                // Determinar color de alerta según el tipo
                let alertColor = 'danger';
                if (alert.alert_type === 'Humedad extrema') alertColor = 'primary';
                else if (alert.alert_type === 'Vientos fuertes') alertColor = 'warning';
                else if (alert.alert_type === 'Tormenta') alertColor = 'secondary';

                // Determinar qué indicador mostrar según el tipo de alerta
                let indicatorHTML = '';
                switch(alert.alert_type) {
                    case 'Temperatura alta':
                    case 'Temperatura baja':
                        indicatorHTML = `<span>🌡️ ${alert.temp.toFixed(1)}°C</span>`;
                        break;
                    case 'Vientos fuertes':
                        indicatorHTML = `<span>💨 ${alert.wind_speed} m/s</span>`;
                        break;
                    case 'Humedad extrema':
                        indicatorHTML = `<span>💧 ${alert.humidity}%</span>`;
                        break;
                }

                alertsHTML += `
                    <div class="alert alert-${alertColor} p-2 mb-2 small">
                        <div class="fw-bold">${alert.alert_type}</div>
                        <div>${indicatorHTML}</div>
                        <div class="text-muted small mt-1">
                            Pronóstico: ${new Date(alert.forecast_time * 1000).toLocaleString()}
                        </div>
                    </div>
                `;
            });

            container.innerHTML = alertsHTML;
        }
    } catch (error) {
        console.error('Error cargando alertas:', error);
        document.getElementById('alerts-container').innerHTML =
            `<p class="text-center text-danger">Error al cargar alertas: ${error.message}</p>`;
    }
}

// Mostrar notificaciones para alertas relevantes
function notifyRelevantAlerts(alerts) {
    // Obtener alertas ya notificadas para no mostrarlas de nuevo
    const notifiedAlerts = JSON.parse(localStorage.getItem('notifiedAlerts') || '[]');
    const newNotifiedAlerts = [...notifiedAlerts];

    alerts.forEach(alert => {
        // Crear un ID único para esta alerta
        const alertId = `${alert.city}-${alert.alert_type}-${alert.forecast_time}`;

        // Verificar si ya se ha notificado
        if (!notifiedAlerts.includes(alertId)) {
            // Mostrar notificación
            if ('serviceWorker' in navigator && 'PushManager' in window) {
                // Usar el Service Worker si está disponible
                navigator.serviceWorker.ready.then(registration => {
                    registration.showNotification('Alerta Meteorológica', {
                        body: `${alert.city}: ${alert.alert_type} - ${alert.temp.toFixed(1)}°C`,
                        icon: '/static/img/weather-icon.png',
                        badge: '/static/img/weather-badge.png',
                        vibrate: [200, 100, 200],
                        data: {
                            city: alert.city,
                            alertType: alert.alert_type,
                            dateTime: new Date(alert.forecast_time * 1000).toLocaleString()
                        },
                        actions: [
                            {
                                action: 'viewDetails',
                                title: 'Ver detalles'
                            }
                        ]
                    });
                });
            } else {
                // Usar la API de notificaciones básica
                new Notification('Alerta Meteorológica', {
                    body: `${alert.city}: ${alert.alert_type} - ${alert.temp.toFixed(1)}°C`,
                    icon: '/static/img/weather-icon.png'
                });
            }

            // Marcar como notificada
            newNotifiedAlerts.push(alertId);
        }
    });

    // Limitar a las últimas 100 alertas notificadas para no crecer indefinidamente
    localStorage.setItem('notifiedAlerts', JSON.stringify(newNotifiedAlerts.slice(-100)));
}

// Obtener umbrales para las alertas
async function loadThresholds() {
    try {
        const response = await fetch('/api/config/thresholds');
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Error cargando umbrales:', error);
        return null;
    }
}

// Cargar estadísticas del sistema
async function loadStats() {
    try {
        const response = await fetch('/api/stats');

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const stats = await response.json();

        const container = document.getElementById('stats-container');
        container.innerHTML = `
            Pronósticos: ${stats.total_forecasts.toLocaleString()} |
            Ciudades: ${stats.cities_count} |
            Última verificación: ${new Date(stats.last_verification).toLocaleString()}
        `;
    } catch (error) {
        console.error('Error cargando estadísticas:', error);
        document.getElementById('stats-container').innerHTML =
            'Error al cargar estadísticas';
    }
}

// Cargar configuración de alertas del almacenamiento local
function loadAlertConfig() {
    const savedConfig = localStorage.getItem('weatherAlertConfig');
    if (savedConfig) {
        try {
            userAlertConfig = JSON.parse(savedConfig);

            // Aplicar configuración a la interfaz
            document.getElementById('enable-notifications').checked = userAlertConfig.notifications;

            // Aplicar umbrales
            document.getElementById('temp-high').value = userAlertConfig.thresholds.temp_high;
            document.getElementById('temp-low').value = userAlertConfig.thresholds.temp_low;
            document.getElementById('wind-speed').value = userAlertConfig.thresholds.wind;
            document.getElementById('humidity').value = userAlertConfig.thresholds.humidity;

            // Update status badge
            updateAlertStatus();

            console.log('Configuración de alertas cargada:', userAlertConfig);
        } catch (e) {
            console.error('Error al cargar configuración de alertas:', e);
        }
    } else {
        // No hay configuración guardada, cargar valores por defecto
        loadDefaultThresholds();
    }
}

// Update the updateAlertStatus function
function updateAlertStatus() {
    const statusBadge = document.getElementById('alert-status');
    if (userAlertConfig.notifications) {
        statusBadge.className = 'badge bg-success';
        statusBadge.textContent = 'ON';
    } else {
        statusBadge.className = 'badge bg-secondary';
        statusBadge.textContent = 'OFF';
    }
}

// Guardar configuración de alertas
async function saveAlertConfig() {
    try {
        // Obtener y validar los valores de los umbrales
        const tempHigh = validateThresholdValue(document.getElementById('temp-high').value, DEFAULT_ALERT_THRESHOLDS.temp_high);
        const tempLow = validateThresholdValue(document.getElementById('temp-low').value, DEFAULT_ALERT_THRESHOLDS.temp_low);
        const windSpeed = validateThresholdValue(document.getElementById('wind-speed').value, DEFAULT_ALERT_THRESHOLDS.wind_speed);
        const humidity = validateThresholdValue(document.getElementById('humidity').value, DEFAULT_ALERT_THRESHOLDS.humidity);

        // Actualizar configuración del usuario
        userAlertConfig = {
            notifications: document.getElementById('enable-notifications').checked,
            thresholds: {
                temp_high: tempHigh,
                temp_low: tempLow,
                wind_speed: windSpeed,
                humidity: humidity
            }
        };

        // Guardar en localStorage
        localStorage.setItem('alertThresholds', JSON.stringify(userAlertConfig.thresholds));

        // Actualizar UI
        updateAlertStatus();
        showToast('Configuración guardada correctamente', 'bg-success');

        // Recargar alertas
        const currentCity = document.getElementById('city-selector').value;
        if (currentCity) {
            await loadAlerts(true);
        }
    } catch (error) {
        console.error('Error guardando configuración:', error);
        showToast('Error al guardar la configuración', 'bg-danger');
    }
}

// Valores por defecto para las alertas
let DEFAULT_ALERT_THRESHOLDS = {
    temp_high: 30,
    temp_low: 5,
    wind_speed: 15,
    humidity: 80
};

// Cargar valores por defecto desde el servidor
async function loadDefaultThresholds() {
    try {
        const response = await fetch('/api/config/thresholds');
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        DEFAULT_ALERT_THRESHOLDS = {
            temp_high: data.temp_high,
            temp_low: data.temp_low,
            wind_speed: data.wind,
            humidity: data.humidity
        };
        return DEFAULT_ALERT_THRESHOLDS;
    } catch (error) {
        console.error('Error cargando umbrales por defecto:', error);
        return DEFAULT_ALERT_THRESHOLDS;
    }
}

// Restablecer valores de alerta a los valores por defecto
async function resetAlertThresholds() {
    try {
        const defaultThresholds = await loadDefaultThresholds();
        document.getElementById('temp-high').value = defaultThresholds.temp_high;
        document.getElementById('temp-low').value = defaultThresholds.temp_low;
        document.getElementById('wind-speed').value = defaultThresholds.wind_speed;
        document.getElementById('humidity').value = defaultThresholds.humidity;

        // Actualizar la configuración del usuario
        userAlertConfig.thresholds = defaultThresholds;
        updateAlertStatus();
        showToast('Valores restablecidos correctamente', 'bg-success');
    } catch (error) {
        console.error('Error al restablecer valores:', error);
        showToast('Error al restablecer valores', 'bg-danger');
    }
}

// Solicitar permiso para notificaciones
function requestNotificationPermission() {
    if (!('Notification' in window)) {
        showToast('Este navegador no admite notificaciones', 'bg-warning');
        return;
    }

    if (Notification.permission === 'granted') {
        return;
    }

    if (Notification.permission !== 'denied') {
        Notification.requestPermission().then(permission => {
            if (permission === 'granted') {
                showToast('Notificaciones activadas correctamente', 'bg-success');
            } else {
                showToast('Permiso de notificaciones denegado', 'bg-warning');
                document.getElementById('enable-notifications').checked = false;
            }
        });
    }
}

// Mostrar toast de notificación
function showToast(message, bgClass = 'bg-primary') {
    let toastContainer = document.getElementById('toast-container');
    if (!toastContainer) {
        toastContainer = document.createElement('div');
        toastContainer.id = 'toast-container';
        toastContainer.className = 'toast-container position-fixed bottom-0 end-0 p-3';
        toastContainer.style.zIndex = '1050';
        document.body.appendChild(toastContainer);
    }

    const toast = document.createElement('div');
    toast.className = `toast ${bgClass} text-white`;
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'assertive');
    toast.setAttribute('aria-atomic', 'true');

    toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">
                ${message}
            </div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
    `;

    toastContainer.appendChild(toast);

    const bsToast = new bootstrap.Toast(toast, { autohide: true, delay: 3000 });
    bsToast.show();

    toast.addEventListener('hidden.bs.toast', function() {
        toast.remove();
    });
}

// Función para buscar ciudades
async function searchCities() {
    const searchTerm = document.getElementById('city-search').value.trim();
    if (searchTerm.length < 2) return;

    try {
        const response = await fetch(`/api/cities/search?q=${encodeURIComponent(searchTerm)}`);
        const cities = await response.json();

        const resultsContainer = document.getElementById('search-results');

        if (cities.length === 0) {
            resultsContainer.innerHTML = '<div class="alert alert-info">No se encontraron ciudades con ese nombre</div>';
            resultsContainer.style.display = 'block';
            return;
        }

        let resultsHTML = '<div class="list-group">';
        cities.forEach(city => {
            resultsHTML += `
                <button type="button" class="list-group-item list-group-item-action city-result"
                    data-city="${city.name}" data-country="${city.country}">
                    ${city.name}, ${city.country}
                </button>
            `;
        });
        resultsHTML += '</div>';

        resultsContainer.innerHTML = resultsHTML;
        resultsContainer.style.display = 'block';

        // Añadir event listeners a los resultados
        document.querySelectorAll('.city-result').forEach(button => {
            button.addEventListener('click', function() {
                const cityName = this.getAttribute('data-city');
                const citySelector = document.getElementById('city-selector');

                // Seleccionar la ciudad en el dropdown
                if (Array.from(citySelector.options).some(option => option.value === cityName)) {
                    citySelector.value = cityName;
                    citySelector.dispatchEvent(new Event('change'));
                    resultsContainer.style.display = 'none';
                }
            });
        });
    } catch (error) {
        console.error('Error buscando ciudades:', error);
    }
}

// Función para añadir a favoritos
function addToFavorites(city) {
    let favorites = JSON.parse(localStorage.getItem('weatherFavorites') || '[]');

    if (!favorites.includes(city)) {
        favorites.push(city);
        localStorage.setItem('weatherFavorites', JSON.stringify(favorites));
        showToast(`${city} añadida a favoritos`, 'bg-success');
        loadFavorites();
    } else {
        showToast(`${city} ya está en favoritos`, 'bg-warning');
    }
}

// Función para cargar favoritos
function loadFavorites() {
    const favorites = JSON.parse(localStorage.getItem('weatherFavorites') || '[]');
    const favoritesList = document.getElementById('favorites-list');

    if (!favoritesList) {
        console.error('No se encontró el elemento favorites-list');
        return;
    }

    if (favorites.length === 0) {
        favoritesList.innerHTML = '<li><span class="dropdown-item text-muted">No hay favoritos</span></li>';
        return;
    }

    let favoritesHTML = '';
    favorites.forEach(city => {
        favoritesHTML += `
            <li>
                <div class="dropdown-item d-flex justify-content-between align-items-center">
                    <span class="favorite-city" data-city="${city}" style="cursor: pointer;">${city}</span>
                    <button class="btn btn-sm btn-outline-danger remove-favorite" data-city="${city}">×</button>
                </div>
            </li>
        `;
    });

    favoritesList.innerHTML = favoritesHTML;

    // Añadir event listeners a los favoritos
    document.querySelectorAll('.favorite-city').forEach(item => {
        item.addEventListener('click', function() {
            const cityName = this.getAttribute('data-city');
            const citySelector = document.getElementById('city-selector');
            if (citySelector) {
                citySelector.value = cityName;
                citySelector.dispatchEvent(new Event('change'));
            }
        });
    });

    document.querySelectorAll('.remove-favorite').forEach(button => {
        button.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            const cityName = this.getAttribute('data-city');
            removeFromFavorites(cityName);
        });
    });
}

// Función para eliminar de favoritos
function removeFromFavorites(cityName) {
    let favorites = JSON.parse(localStorage.getItem('weatherFavorites') || '[]');
    const index = favorites.indexOf(cityName);

    if (index !== -1) {
        favorites.splice(index, 1);
        localStorage.setItem('weatherFavorites', JSON.stringify(favorites));
        showToast(`${cityName} eliminada de favoritos`, 'bg-success');
        loadFavorites();
    }
}

// Inicializar la aplicación
document.addEventListener('DOMContentLoaded', async () => {
    // Inicializar datos
    await loadCities();
    await loadAlerts();
    await loadStats();

    // Modo oscuro: cargar preferencia y configurar toggle
    const darkToggle = document.getElementById('darkModeToggle');
    if (localStorage.getItem('darkMode') === 'true') {
        document.body.classList.add('dark-mode');
        darkToggle.checked = true;
    }

    darkToggle.addEventListener('change', function () {
        document.body.classList.toggle('dark-mode', this.checked);
        localStorage.setItem('darkMode', this.checked);
    });

    // Configurar selector de días históricos
    document.getElementById('history-days').addEventListener('change', function() {
        const selectedCity = document.getElementById('city-selector').value;
        if (selectedCity) {
            loadHistoricalData(selectedCity, this.value);
        }
    });

    // Recargar alertas cada 5 minutos
    setInterval(loadAlerts, 5 * 60 * 1000);

    // Recargar estadísticas cada 10 minutos
    setInterval(loadStats, 10 * 60 * 1000);

    // Funcionalidad de búsqueda
    document.getElementById('search-button').addEventListener('click', searchCities);
    document.getElementById('city-search').addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            searchCities();
        }
    });

    // Gestión de favoritos
    const addFavoriteBtn = document.getElementById('add-favorite');
    if (addFavoriteBtn) {
        addFavoriteBtn.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            const selectedCity = document.getElementById('city-selector').value;
            if (!selectedCity) {
                showToast('Selecciona una ciudad primero', 'bg-warning');
                return;
            }
            addToFavorites(selectedCity);
        });
    }

    // Cargar favoritos al inicio
    await loadFavorites();

    // Cargar configuración de alertas
    loadAlertConfig();

    // Event listener para el botón de guardar configuración
    const saveConfigBtn = document.getElementById('save-alerts');
    if (saveConfigBtn) {
        saveConfigBtn.addEventListener('click', async function(e) {
            e.preventDefault();
            await saveAlertConfig();
        });
    }

    // Event listeners para botones de exportación
    document.querySelectorAll('.export-data').forEach(button => {
        button.addEventListener('click', function() {
            const format = this.getAttribute('data-format');
            exportHistoricalData(format);
        });
    });

    document.querySelectorAll('.export-forecast').forEach(button => {
        button.addEventListener('click', function() {
            const format = this.getAttribute('data-format');
            exportForecastData(format);
        });
    });

    // Event listener para cambios en el selector de ciudad
    const citySelector = document.getElementById('city-selector');
    if (citySelector) {
        citySelector.addEventListener('change', function() {
            const selectedCity = this.value;
            if (selectedCity) {
                loadCurrentWeather(selectedCity);
                loadHistoricalData(selectedCity, document.getElementById('history-days').value);
                loadForecast(selectedCity);
                loadAlerts();
            }
        });
    }

    // Add event listener for alert config button
    const alertConfigButton = document.querySelector('[data-bs-toggle="collapse"][data-bs-target="#alertConfig"]');
    if (alertConfigButton) {
        alertConfigButton.addEventListener('click', function() {
            const alertConfig = document.getElementById('alertConfig');
            if (alertConfig.classList.contains('show')) {
                // If opening, load the current config
                loadAlertConfig();
            }
        });
    }

    // Recargar clima actual cada 5 minutos
    setInterval(() => {
        const selectedCity = document.getElementById('city-selector').value;
        if (selectedCity) {
            loadCurrentWeather(selectedCity);
        }
    }, 5 * 60 * 1000);

    // Cargar valores por defecto al inicio
    const defaultThresholds = await loadDefaultThresholds();

    // Cargar valores guardados o usar valores por defecto
    const savedThresholds = JSON.parse(localStorage.getItem('alertThresholds') || '{}');
    const currentThresholds = {
        temp_high: savedThresholds.temp_high || defaultThresholds.temp_high,
        temp_low: savedThresholds.temp_low || defaultThresholds.temp_low,
        wind_speed: savedThresholds.wind_speed || defaultThresholds.wind_speed,
        humidity: savedThresholds.humidity || defaultThresholds.humidity
    };

    // Actualizar los campos del formulario
    document.getElementById('temp-high').value = currentThresholds.temp_high;
    document.getElementById('temp-low').value = currentThresholds.temp_low;
    document.getElementById('wind-speed').value = currentThresholds.wind_speed;
    document.getElementById('humidity').value = currentThresholds.humidity;

    // Actualizar la configuración del usuario
    userAlertConfig.thresholds = currentThresholds;
    updateAlertStatus();

    // Configurar botón de restablecer valores
    document.getElementById('reset-alerts').addEventListener('click', resetAlertThresholds);
});