from flask import Flask, jsonify, render_template, request, send_file
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_caching import Cache
from pydantic import BaseModel, validator
from typing import Optional, List
import pymongo
import datetime
from datetime import datetime, timezone, timedelta
from bson import json_util
import json
import logging
import os
from dotenv import load_dotenv

# Cargar variables de entorno
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path)

# Configuración desde archivo config.py
from config import MONGO_CONFIG, API_CONFIG

# Configuración de logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configurar rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=[API_CONFIG['rate_limit']]
)

# Configurar caché
cache = Cache(app, config={
    'CACHE_TYPE': 'simple',
    'CACHE_DEFAULT_TIMEOUT': API_CONFIG['cache_timeout']
})

# Modelos de validación
class WeatherQuery(BaseModel):
    days: int = 7

    @validator('days')
    def validate_days(cls, v):
        if v < 1 or v > 365:
            raise ValueError('Days must be between 1 and 365')
        return v

class CityQuery(BaseModel):
    city: str

    @validator('city')
    def validate_city(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('City name cannot be empty')
        return v.strip()

# Función para obtener un cliente MongoDB con connection pooling
def get_mongo_client():
    """Función para obtener un cliente MongoDB con conexión pooling configurada"""
    return pymongo.MongoClient(
        MONGO_CONFIG['uri'],
        maxPoolSize=10,
        minPoolSize=1,
        maxIdleTimeMS=30000,
        socketTimeoutMS=45000,
        connectTimeoutMS=10000,
        serverSelectionTimeoutMS=10000,
        waitQueueTimeoutMS=10000
    )

# Configuración de MongoDB
try:
    client = get_mongo_client()
    db = client[MONGO_CONFIG['db_name']]
    logger.info("Conexión a MongoDB establecida correctamente")
except Exception as e:
    logger.error(f"Error conectando a MongoDB: {e}")
    raise

@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({"error": "ratelimit exceeded", "message": str(e.description)}), 429

@app.errorhandler(400)
def bad_request_handler(e):
    return jsonify({"error": "bad request", "message": str(e.description)}), 400

@app.errorhandler(500)
def internal_error_handler(e):
    return jsonify({"error": "internal server error", "message": "An unexpected error occurred"}), 500

@app.route('/')
def index():
    """Página principal del dashboard"""
    return render_template('index.html')

@app.route('/health')
@limiter.limit("10/minute")
def health():
    """Endpoint para verificar el estado del servicio"""
    try:
        db.command('ping')
        return jsonify({"status": "ok", "service": "weather_api"}), 200
    except Exception as e:
        logger.error(f"Health check falló: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/cities')
@limiter.limit("30/minute")
@cache.cached(timeout=3600)  # Cache for 1 hour
def get_cities():
    """Devuelve la lista de ciudades disponibles"""
    try:
        cities = db[MONGO_CONFIG['collections']['hourly_forecast']].distinct("city.name")
        return jsonify(cities)
    except Exception as e:
        logger.error(f"Error obteniendo ciudades: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/metrics/collector')
def get_collector_metrics():
    """Obtiene métricas del servicio de recolección"""
    try:
        # Leer métricas de MongoDB
        result = db['system_metrics'].find_one(
            {"service": "weather_collector"},
            sort=[("timestamp", -1)]
        )

        if not result:
            return jsonify({"error": "No hay métricas disponibles"}), 404

        # Convertir a formato JSON serializable usando bson.json_util
        result_json = json_util.dumps(result)
        result_dict = json.loads(result_json)

        return jsonify(result_dict)
    except Exception as e:
        logger.error(f"Error obteniendo métricas: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/metrics/summary')
def get_metrics_summary():
    """Obtiene un resumen de métricas de los últimos días"""
    try:
        days = int(request.args.get('days', 7))
        date_limit = datetime.utcnow() - timedelta(days=days)

        # Obtener métricas de los últimos días
        metrics = list(db['system_metrics'].find(
            {"timestamp": {"$gte": date_limit}},
            sort=[("timestamp", 1)]
        ))

        if not metrics:
            return jsonify({"error": "No hay métricas disponibles para el período solicitado"}), 404

        # Procesar datos para el resumen
        summary = {
            "period": {
                "start": date_limit.isoformat(),
                "end": datetime.utcnow().isoformat(),
                "days": days
            },
            "api_calls": {
                "total": sum(m.get('api_calls_total', 0) for m in metrics),
                "errors": sum(m.get('api_errors_total', 0) for m in metrics),
                "success_rate": 0
            },
            "updates": {
                "total": sum(m.get('successful_updates_total', 0) for m in metrics),
                "failed": sum(m.get('failed_updates_total', 0) for m in metrics)
            },
            "performance": {
                "avg_api_time": sum(m.get('avg_api_response_time', 0) for m in metrics) / len(metrics) if metrics else 0,
                "avg_db_time": sum(m.get('avg_db_write_time', 0) for m in metrics) / len(metrics) if metrics else 0
            }
        }

        # Calcular tasa de éxito
        total_calls = summary["api_calls"]["total"]
        if total_calls > 0:
            summary["api_calls"]["success_rate"] = (
                (total_calls - summary["api_calls"]["errors"]) / total_calls * 100
            )

        return jsonify(summary)
    except Exception as e:
        logger.error(f"Error obteniendo resumen de métricas: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/current/<city>')
@limiter.limit("60/minute")
@cache.cached(timeout=300, unless=lambda: request.args.get('force_update') == 'true')
def get_current_weather(city):
    """Obtiene los datos meteorológicos más recientes para una ciudad"""
    try:
        # Validar entrada
        city_query = CityQuery(city=city)

        # Get current timestamp
        current_timestamp = get_current_timestamp()

        # Get forecast data from MongoDB
        forecast_data = list(db[MONGO_CONFIG['collections']['hourly_forecast']].find(
            {"city.name": city_query.city},
            {"_id": 0}
        ).sort("collected_at", -1))  # Get most recent first

        if not forecast_data:
            return jsonify({"error": "Ciudad no encontrada"}), 404

        # Collect all forecasts from all documents
        all_forecasts = []
        for doc in forecast_data:
            if 'list' in doc:
                all_forecasts.extend(doc['list'])

        if not all_forecasts:
            return jsonify({"error": "No hay datos de pronóstico disponibles"}), 404

        # Sort all forecasts by timestamp
        all_forecasts.sort(key=lambda x: x['dt'])

        # Find closest forecast to current time
        closest_forecast = min(all_forecasts, key=lambda x: abs(x['dt'] - current_timestamp))

        # Check if the closest forecast is too far in the future (more than 24h)
        time_diff_hours = (closest_forecast['dt'] - current_timestamp) / 3600

        # Only update last_check if the data is older than an hour
        current_time = datetime.utcnow()
        last_check = forecast_data[0].get("last_check", forecast_data[0]["collected_at"])
        if (current_time - last_check).total_seconds() > 3600:
            db[MONGO_CONFIG['collections']['hourly_forecast']].update_many(
                {"city.name": city_query.city},
                {"$set": {"last_check": current_time}}
            )
            last_check = current_time

        response = {
            "city": forecast_data[0]["city"]["name"],
            "country": forecast_data[0]["city"]["country"],
            "timestamp": closest_forecast["dt"],
            "datetime": datetime.fromtimestamp(closest_forecast["dt"]).strftime('%Y-%m-%d %H:%M:%S'),
            "temp": closest_forecast["main"]["temp"],
            "feels_like": closest_forecast["main"]["feels_like"],
            "humidity": closest_forecast["main"]["humidity"],
            "pressure": closest_forecast["main"]["pressure"],
            "weather": closest_forecast["weather"][0]["main"],
            "description": closest_forecast["weather"][0]["description"],
            "icon": closest_forecast["weather"][0]["icon"],
            "wind_speed": closest_forecast["wind"]["speed"],
            "last_check": last_check.strftime('%Y-%m-%d %H:%M:%S')
        }

        # Add warning if forecast is far from current time
        if abs(time_diff_hours) > 24:
            response["warning"] = f"Este pronóstico es para {time_diff_hours:.1f} horas {('adelante' if time_diff_hours >= 0 else 'atrás')} del tiempo actual"
            logger.warning(f"Closest forecast for {city} is {time_diff_hours:.1f} hours away from current time!")

        return jsonify(response)

    except Exception as e:
        logger.error(f"Error obteniendo clima actual: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/historical/<city>')
@limiter.limit("30/minute")
def get_historical_data(city):
    """Obtiene datos históricos para una ciudad con paginación"""
    try:
        # Validar entrada
        city_query = CityQuery(city=city)
        weather_query = WeatherQuery(days=int(request.args.get('days', 7)))

        # Parámetros de paginación
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 100))

        if page < 1:
            page = 1
        if per_page < 1 or per_page > 1000:
            per_page = 100

        # Calcular skip para paginación
        skip = (page - 1) * per_page

        # Obtener la fecha más reciente para esta ciudad
        last_entry = db[MONGO_CONFIG['collections']['hourly_forecast']].find_one(
            {"city.name": city_query.city},
            sort=[("collected_at", -1)]
        )

        if not last_entry:
            return jsonify({
                "data": [],
                "pagination": {
                    "total": 0,
                    "page": page,
                    "per_page": per_page,
                    "total_pages": 0
                }
            })

        # Obtener todos los documentos para esta ciudad
        results = db[MONGO_CONFIG['collections']['hourly_forecast']].find({
            "city.name": city_query.city
        }).sort("collected_at", 1).skip(skip).limit(per_page)

        # Recolectar todos los pronósticos
        all_forecasts = []
        for doc in results:
            for forecast in doc.get("list", []):
                forecast_dt = datetime.fromtimestamp(forecast["dt"])
                all_forecasts.append({
                    "date": forecast_dt.date().isoformat(),
                    "temp": forecast["main"]["temp"],
                    "humidity": forecast["main"]["humidity"],
                    "pressure": forecast["main"]["pressure"],
                    "wind_speed": forecast["wind"]["speed"],
                    "precipitation": forecast.get("rain", {}).get("1h", 0) if "rain" in forecast else 0
                })

        if not all_forecasts:
            return jsonify({
                "data": [],
                "pagination": {
                    "total": 0,
                    "page": page,
                    "per_page": per_page,
                    "total_pages": 0
                }
            })

        # Agrupar por día
        from collections import defaultdict
        grouped = defaultdict(list)
        for forecast in all_forecasts:
            grouped[forecast["date"]].append(forecast)

        # Calcular estadísticas por día
        result = []
        for date, forecasts in grouped.items():
            # Extraer todas las temperaturas del día
            temps = [f["temp"] for f in forecasts]

            # Calcular estadísticas de temperatura
            max_temp = max(temps)
            min_temp = min(temps)
            avg_temp = sum(temps) / len(temps)

            # Calcular otros promedios
            avg_humidity = sum(f["humidity"] for f in forecasts) / len(forecasts)
            avg_pressure = sum(f["pressure"] for f in forecasts) / len(forecasts)
            avg_wind = sum(f["wind_speed"] for f in forecasts) / len(forecasts)
            total_precipitation = sum(f["precipitation"] for f in forecasts)

            result.append({
                "date": date,
                "temp_max": round(max_temp, 2),
                "temp_min": round(min_temp, 2),
                "temp_avg": round(avg_temp, 2),
                "humidity_avg": round(avg_humidity, 2),
                "pressure_avg": round(avg_pressure, 2),
                "wind_speed": round(avg_wind, 2),
                "precipitation": round(total_precipitation, 2)
            })

        # Ordenar por fecha (ascendente)
        result.sort(key=lambda x: x["date"])

        # Filtrar por el número de días solicitado
        if result:
            last_date = datetime.fromisoformat(result[-1]["date"])
            date_limit = last_date - timedelta(days=weather_query.days)
            result = [r for r in result if datetime.fromisoformat(r["date"]) >= date_limit]

        return jsonify({
            "data": result,
            "pagination": {
                "total": len(result),
                "page": page,
                "per_page": per_page,
                "total_pages": (len(result) + per_page - 1) // per_page
            }
        })
    except Exception as e:
        logger.error(f"Error obteniendo datos históricos: {e}")
        return jsonify({"error": str(e)}), 500

def get_current_timestamp():
    """Get current timestamp in UTC"""
    # Get current time in UTC
    current_time_utc = datetime.now(timezone.utc)

    # Create UTC+1 timezone
    utc_plus_1 = timezone(timedelta(hours=1))

    # Convert UTC time to UTC+1
    local_time = current_time_utc.astimezone(utc_plus_1)

    # Calculate the timezone offset in seconds (3600 seconds = 1 hour)
    timezone_offset = 3600

    # Add the timezone offset to get the correct local timestamp
    local_timestamp = int(current_time_utc.timestamp() + timezone_offset)

    return local_timestamp

@app.route('/api/forecast/<city>')
def get_forecast(city):
    """Get weather forecast for a city"""
    try:
        # Get current timestamp
        current_timestamp = get_current_timestamp()
        current_time = datetime.fromtimestamp(current_timestamp)

        # Calculate next hour timestamp (rounded up)
        next_hour = current_time.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        next_hour_timestamp = int(next_hour.timestamp())

        # Get forecast data from MongoDB
        forecast_data = list(db[MONGO_CONFIG['collections']['hourly_forecast']].find(
            {"city.name": city},
            {"_id": 0}
        ).sort("collected_at", -1))  # Get most recent first

        if not forecast_data:
            return jsonify({"status": "error", "message": "No forecast data available"}), 404

        # First, collect all forecasts from all documents
        all_forecasts = []
        for forecast in forecast_data:
            if 'list' not in forecast:
                continue
            all_forecasts.extend(forecast['list'])

        # Sort all forecasts by timestamp
        all_forecasts.sort(key=lambda x: x.get('dt', 0))

        # Now filter for future forecasts, excluding current hour
        filtered_forecast = []
        for forecast_item in all_forecasts:
            forecast_timestamp = forecast_item.get('dt')
            if not forecast_timestamp:
                continue

            forecast_time = datetime.fromtimestamp(forecast_timestamp)

            # Only include forecasts from the next hour onwards
            if forecast_timestamp > current_timestamp:  # Changed from >= to > to exclude current hour
                # Format the forecast data properly
                formatted_forecast = {
                    "datetime": forecast_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "timestamp": forecast_timestamp,
                    "temp": forecast_item.get('main', {}).get('temp', 0),
                    "description": forecast_item.get('weather', [{}])[0].get('description', ''),
                    "icon": forecast_item.get('weather', [{}])[0].get('icon', ''),
                    "wind_speed": forecast_item.get('wind', {}).get('speed', 0),
                    "humidity": forecast_item.get('main', {}).get('humidity', 0)
                }
                filtered_forecast.append(formatted_forecast)

        if not filtered_forecast:
            return jsonify({"status": "error", "message": "No forecast data available"}), 404

        return jsonify({
            "status": "success",
            "forecast": filtered_forecast
        })

    except Exception as e:
        logger.error(f"Error getting forecast: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/alerts')
def get_alerts():
    """Obtiene alertas meteorológicas basadas en umbrales preestablecidos"""
    try:
        # Obtener umbrales desde la configuración
        from config import THRESHOLDS

        # Obtener el último pronóstico para cada ciudad
        pipeline = [
            # Primero, desenrollar la lista de cada documento
            {"$unwind": "$list"},

            # Ordenar por ciudad y timestamp del pronóstico
            {"$sort": {"city.name": 1, "list.dt": 1}},

            # Filtrar solo pronósticos futuros (próximas 24 horas)
            {"$match": {
                "list.dt": {
                    "$gte": int(datetime.utcnow().timestamp()),
                    "$lte": int((datetime.utcnow() + timedelta(hours=24)).timestamp())
                }
            }},

            # Agrupar por ciudad para obtener el primer pronóstico futuro de cada ciudad
            {"$group": {
                "_id": "$city.name",
                "city": {"$first": "$city.name"},
                "country": {"$first": "$city.country"},
                "coord": {"$first": "$city.coord"},
                "temp": {"$first": "$list.main.temp"},
                "feels_like": {"$first": "$list.main.feels_like"},
                "humidity": {"$first": "$list.main.humidity"},
                "wind_speed": {"$first": "$list.wind.speed"},
                "weather_id": {"$first": "$list.weather.0.id"},
                "weather_main": {"$first": "$list.weather.0.main"},
                "weather_description": {"$first": "$list.weather.0.description"},
                "forecast_time": {"$first": "$list.dt"},
                "collected_at": {"$first": "$collected_at"}
            }},

            # Filtrar solo aquellos que cumplen con los criterios de alerta
            {"$match": {
                "$or": [
                    {"temp": {"$gt": THRESHOLDS['temp_high']}},
                    {"temp": {"$lt": THRESHOLDS['temp_low']}},
                    {"wind_speed": {"$gt": THRESHOLDS['wind']}},
                    {"humidity": {"$gt": THRESHOLDS['humidity']}},
                    {"weather_id": {"$in": [200, 201, 202, 210, 211, 212, 221, 230, 231, 232]}}  # Códigos de tormenta
                ]
            }},

            # Añadir un campo para el tipo de alerta
            {"$addFields": {
                "alert_type": {
                    "$cond": [
                        {"$gt": ["$temp", THRESHOLDS['temp_high']]},
                        "Calor extremo",
                        {"$cond": [
                            {"$lt": ["$temp", THRESHOLDS['temp_low']]},
                            "Frío extremo",
                            {"$cond": [
                                {"$gt": ["$wind_speed", THRESHOLDS['wind']]},
                                "Vientos fuertes",
                                {"$cond": [
                                    {"$gt": ["$humidity", THRESHOLDS['humidity']]},
                                    "Humedad extrema",
                                    "Tormenta"
                                ]}
                            ]}
                        ]}
                    ]
                }
            }}
        ]

        alerts = list(db[MONGO_CONFIG['collections']['hourly_forecast']].aggregate(pipeline))

        # Convertir ObjectId y datetime a formato serializable y devolver como JSON
        return jsonify(json.loads(json_util.dumps(alerts)))
    except Exception as e:
        logger.error(f"Error obteniendo alertas: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/alerts/custom')
@limiter.limit("30/minute")
def get_custom_alerts():
    try:
        # Obtener parámetros de la URL
        temp_high = float(request.args.get('temp_high', 35))
        temp_low = float(request.args.get('temp_low', 0))
        wind = float(request.args.get('wind', 15))
        humidity = float(request.args.get('humidity', 90))

        logger.info(f"Thresholds received - temp_high: {temp_high}, temp_low: {temp_low}, wind: {wind}, humidity: {humidity}")

        # Obtener timestamp actual
        current_time = datetime.utcnow()
        current_timestamp = int(current_time.timestamp())

        # Obtener el próximo pronóstico para cada ciudad
        pipeline = [
            # Primero, desenrollar la lista de cada documento
            {"$unwind": "$list"},

            # Ordenar por ciudad y timestamp del pronóstico
            {"$sort": {"city.name": 1, "list.dt": 1}},

            # Filtrar solo pronósticos futuros
            {"$match": {
                "list.dt": {"$gt": current_timestamp}
            }},

            # Agrupar por ciudad para obtener el primer pronóstico futuro
            {"$group": {
                "_id": "$city.name",
                "city": {"$first": "$city.name"},
                "temp": {"$first": "$list.main.temp"},
                "wind_speed": {"$first": "$list.wind.speed"},
                "humidity": {"$first": "$list.main.humidity"},
                "forecast_time": {"$first": "$list.dt"}
            }},

            # Filtrar solo aquellos que cumplen con los criterios de alerta personalizados
            {"$match": {
                "$or": [
                    {"temp": {"$gt": temp_high}},
                    {"temp": {"$lt": temp_low}},
                    {"wind_speed": {"$gt": wind}},
                    {"humidity": {"$gt": humidity}}
                ]
            }},

            # Añadir un campo para el tipo de alerta
            {"$addFields": {
                "alert_types": {
                    "$concatArrays": [
                        {"$cond": [{"$gt": ["$temp", temp_high]}, ["Temperatura alta"], []]},
                        {"$cond": [{"$lt": ["$temp", temp_low]}, ["Temperatura baja"], []]},
                        {"$cond": [{"$gt": ["$wind_speed", wind]}, ["Vientos fuertes"], []]},
                        {"$cond": [{"$gt": ["$humidity", humidity]}, ["Humedad extrema"], []]}
                    ]
                }
            }},

            # Desenrollar los tipos de alerta para crear un documento por cada tipo
            {"$unwind": "$alert_types"},

            # Renombrar alert_types a alert_type
            {"$project": {
                "city": 1,
                "temp": 1,
                "wind_speed": 1,
                "humidity": 1,
                "forecast_time": 1,
                "alert_type": "$alert_types"
            }}
        ]

        # Ejecutar la consulta y obtener resultados
        alerts = list(db[MONGO_CONFIG['collections']['hourly_forecast']].aggregate(pipeline))
        logger.info(f"Found {len(alerts)} alerts")

        # Convertir ObjectId y datetime a formato serializable
        serialized_alerts = json.loads(json_util.dumps(alerts))

        # Devolver respuesta JSON
        return jsonify({
            'status': 'success',
            'alerts': serialized_alerts
        })

    except Exception as e:
        logger.error(f"Error en get_custom_alerts: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/api/config/thresholds')
def get_thresholds():
    """Devuelve los umbrales de alertas actuales"""
    try:
        from config import THRESHOLDS
        return jsonify(THRESHOLDS)
    except Exception as e:
        logger.error(f"Error obteniendo umbrales: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/stats')
def get_stats():
    """Obtiene estadísticas generales del sistema"""
    try:
        hourly_collection = MONGO_CONFIG['collections']['hourly_forecast']

        stats = {
            "total_forecasts": db[hourly_collection].count_documents({}),
            "cities_count": len(db[hourly_collection].distinct("city.name")),
            "last_verification": None
        }

        # Obtener última verificación de cualquier ciudad
        pipeline = [
            # Desenrollar los documentos para obtener el último check de cada uno
            {"$sort": {"last_check": -1}},
            {"$limit": 1},
            {"$project": {
                "last_verification": "$last_check"
            }}
        ]

        result = list(db[hourly_collection].aggregate(pipeline))

        if result and result[0].get("last_verification"):
            stats["last_verification"] = result[0]["last_verification"].strftime("%Y-%m-%d %H:%M:%S")
        else:
            # Si no hay last_check, buscar el collected_at más reciente
            last_entry = db[hourly_collection].find_one(
                sort=[("collected_at", -1)]
            )
            if last_entry:
                stats["last_verification"] = last_entry["collected_at"].strftime("%Y-%m-%d %H:%M:%S")
            else:
                stats["last_verification"] = "No hay datos"

        # Obtener número total de pronósticos por hora almacenados
        total_hourly_forecasts = 0
        result = db[hourly_collection].aggregate([
            {"$project": {"count": {"$size": "$list"}}},
            {"$group": {"_id": None, "total": {"$sum": "$count"}}}
        ])

        result_list = list(result)
        if result_list:
            total_hourly_forecasts = result_list[0]["total"]

        stats["total_hourly_entries"] = total_hourly_forecasts

        return jsonify(stats)
    except Exception as e:
        logger.error(f"Error obteniendo estadísticas: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/cities/search')
@limiter.limit("30/minute")
def search_cities():
    """Busca ciudades por nombre (parcial)"""
    try:
        query = request.args.get('q', '').strip()
        if not query or len(query) < 2:
            return jsonify([])

        # Usar una expresión regular para buscar coincidencias parciales
        # i: case insensitive
        regex_query = {"$regex": f".*{query}.*", "$options": "i"}

        cities = list(db[MONGO_CONFIG['collections']['hourly_forecast']].aggregate([
            {"$match": {"city.name": regex_query}},
            {"$group": {
                "_id": "$city.name",
                "name": {"$first": "$city.name"},
                "country": {"$first": "$city.country"},
                "lat": {"$first": "$city.coord.lat"},
                "lon": {"$first": "$city.coord.lon"},
            }},
            {"$sort": {"name": 1}},
            {"$limit": 10}  # Limitar a 10 resultados
        ]))

        return jsonify(cities)
    except Exception as e:
        logger.error(f"Error buscando ciudades: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/export/pdf')
def export_to_pdf():
    """Genera un PDF con datos históricos o pronóstico"""
    try:
        # Obtener parámetros
        data_type = request.args.get('type', 'historical')  # historical o forecast
        city = request.args.get('city')
        days = int(request.args.get('days', 7))

        if not city:
            return jsonify({"error": "Se requiere el parámetro 'city'"}), 400

        # Validar tipo de datos
        if data_type not in ['historical', 'forecast']:
            return jsonify({"error": "Tipo de datos inválido. Use 'historical' o 'forecast'"}), 400

        # Obtener datos según el tipo
        if data_type == 'historical':
            # Reutilizar función existente pero sin paginación
            response = get_historical_data(city)
            title = f"Datos históricos para {city} - Últimos {days} días"

        else:  # forecast
            response = get_forecast(city)
            title = f"Pronóstico para {city}"

        # Verificar respuesta
        if isinstance(response, tuple) and len(response) > 1 and response[1] != 200:
            return response

        # Convertir respuesta a diccionario si es jsonify
        if hasattr(response, 'get_json'):
            data = response.get_json()
        else:
            data = response

        # Extraer datos específicos según el tipo
        if data_type == 'historical' and 'data' in data:
            table_data = data['data']
        elif data_type == 'forecast' and 'forecast' in data:
            table_data = data['forecast']
        else:
            return jsonify({"error": "Formato de datos inesperado"}), 500

        # Generar PDF usando una biblioteca como ReportLab o WeasyPrint
        # Esta es una implementación simplificada
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import landscape, A4
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
        from reportlab.lib.styles import getSampleStyleSheet
        import io

        # Crear buffer para PDF
        buffer = io.BytesIO()

        # Configurar documento
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4))

        # Estilos
        styles = getSampleStyleSheet()
        title_style = styles['Title']

        # Elementos del PDF
        elements = []

        # Título
        elements.append(Paragraph(title, title_style))

        # Crear tabla
        if table_data:
            # Obtener encabezados de las claves del primer elemento
            headers = list(table_data[0].keys())

            # Crear datos de tabla con encabezados
            table_content = [headers]

            # Añadir filas
            for row in table_data:
                table_row = []
                for key in headers:
                    value = row.get(key)
                    # Formatear según el tipo
                    if isinstance(value, (int, float)):
                        # Formatear números
                        if isinstance(value, float):
                            formatted = f"{value:.2f}"
                        else:
                            formatted = str(value)
                    elif isinstance(value, str) and value.startswith('20') and 'T' in value:
                        # Parece una fecha ISO
                        from datetime import datetime
                        try:
                            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
                            formatted = dt.strftime('%d/%m/%Y %H:%M')
                        except:
                            formatted = value
                    else:
                        formatted = str(value) if value is not None else '-'

                    table_row.append(formatted)

                table_content.append(table_row)

            # Crear tabla
            table = Table(table_content)

            # Estilo de tabla
            table_style = TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ])

            table.setStyle(table_style)
            elements.append(table)

        # Construir PDF
        doc.build(elements)

        # Preparar respuesta
        buffer.seek(0)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{city}_{data_type}_{timestamp}.pdf"

        return send_file(
            buffer,
            as_attachment=True,
            download_name=filename,
            mimetype='application/pdf'
        )

    except Exception as e:
        logger.error(f"Error generando PDF: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    logger.info(f"Iniciando API en {API_CONFIG['host']}:{API_CONFIG['port']}")
    app.run(
        host=API_CONFIG['host'],
        port=API_CONFIG['port'],
        debug=True
    )
