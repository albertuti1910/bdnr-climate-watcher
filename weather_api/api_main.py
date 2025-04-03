from flask import Flask, jsonify, render_template, request
import pymongo
from datetime import datetime, timedelta
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
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuración de MongoDB
try:
    MONGO_URI = MONGO_CONFIG['uri']
    client = pymongo.MongoClient(MONGO_URI)
    db = client[MONGO_CONFIG['db_name']]
    logger.info("Conexión a MongoDB establecida correctamente")
except Exception as e:
    logger.error(f"Error conectando a MongoDB: {e}")
    raise

@app.route('/')
def index():
    """Página principal del dashboard"""
    return render_template('index.html')

@app.route('/api/cities')
def get_cities():
    """Devuelve la lista de ciudades disponibles"""
    try:
        # Ahora usamos la colección hourly_forecast
        cities = db[MONGO_CONFIG['collections']['hourly_forecast']].distinct("city.name")
        return jsonify(cities)
    except Exception as e:
        logger.error(f"Error obteniendo ciudades: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/current/<city>')
def get_current_weather(city):
    """Obtiene los datos meteorológicos más recientes para una ciudad"""
    try:
        # Buscar la entrada más reciente para la ciudad
        result = db[MONGO_CONFIG['collections']['hourly_forecast']].find(
            {"city.name": city}
        ).sort("collected_at", -1).limit(1)

        data = list(result)

        if not data:
            return jsonify({"error": "Ciudad no encontrada"}), 404

        # Si hay datos, obtener la predicción más próxima al momento actual
        if data and 'list' in data[0]:
            # Ordenar la lista por timestamp (dt)
            forecast_list = sorted(data[0]['list'], key=lambda x: x['dt'])

            # Buscar la predicción más cercana al momento actual
            now_timestamp = int(datetime.utcnow().timestamp())
            closest_forecast = min(forecast_list, key=lambda x: abs(x['dt'] - now_timestamp))

            # Preparar la respuesta
            response = {
                "city": data[0]["city"]["name"],
                "country": data[0]["city"]["country"],
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
                "updated_at": data[0]["collected_at"].strftime('%Y-%m-%d %H:%M:%S')
            }

            return jsonify(response)

        # Si no tiene la estructura esperada
        return jsonify({"error": "Formato de datos inválido"}), 500
    except Exception as e:
        logger.error(f"Error obteniendo clima actual: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/historical/<city>')
def get_historical_data(city):
    """Obtiene datos históricos para una ciudad"""
    try:
        days = int(request.args.get('days', 7))  # Por defecto, últimos 7 días

        # Calcular fecha límite
        date_limit = datetime.utcnow() - timedelta(days=days)

        # Pipeline para obtener datos históricos agrupados por día
        # Usamos todos los pronósticos almacenados en la base de datos
        pipeline = [
            # Filtrar por ciudad y fecha
            {"$match": {
                "city.name": city,
                "collected_at": {"$gte": date_limit}
            }},

            # Desenrollar la lista para procesar cada pronóstico
            {"$unwind": "$list"},

            # Convertir timestamp unix a fecha
            {"$addFields": {
                "forecast_date": {"$toDate": {"$multiply": ["$list.dt", 1000]}}
            }},

            # Filtrar solo pronósticos en el pasado (datos históricos)
            {"$match": {
                "forecast_date": {"$lt": datetime.utcnow()}
            }},

            # Agrupar por día
            {"$group": {
                "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$forecast_date"}},
                "avg_temp": {"$avg": "$list.main.temp"},
                "min_temp": {"$min": "$list.main.temp_min"},
                "max_temp": {"$max": "$list.main.temp_max"},
                "avg_humidity": {"$avg": "$list.main.humidity"},
                "avg_pressure": {"$avg": "$list.main.pressure"},
                "data_points": {"$sum": 1}  # Contar cuántos datos tenemos por día
            }},

            # Ordenar por fecha
            {"$sort": {"_id": 1}}
        ]

        results = list(db[MONGO_CONFIG['collections']['hourly_forecast']].aggregate(pipeline))
        return json.loads(json_util.dumps(results))
    except Exception as e:
        logger.error(f"Error obteniendo datos históricos: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/forecast/<city>')
def get_forecast(city):
    """Obtiene el pronóstico más reciente para una ciudad"""
    try:
        # Buscar los pronósticos más recientes
        result = db[MONGO_CONFIG['collections']['hourly_forecast']].find(
            {"city.name": city}
        ).sort("collected_at", -1).limit(1)

        data = list(result)

        if not data:
            return jsonify({"error": "Pronóstico no encontrado"}), 404

        # Simplificar la respuesta para incluir solo datos relevantes
        forecast = []
        now = datetime.utcnow()

        # Ordenar cronológicamente y filtrar solo pronósticos futuros
        forecast_list = sorted(data[0]["list"], key=lambda x: x["dt"])
        future_forecasts = [f for f in forecast_list if datetime.fromtimestamp(f["dt"]) > now]

        # Limitar a las próximas 24 horas (~ 24 entradas)
        for item in future_forecasts[:24]:
            forecast_time = datetime.fromtimestamp(item["dt"])
            forecast.append({
                "datetime": forecast_time.strftime("%Y-%m-%d %H:%M:%S"),
                "timestamp": item["dt"],
                "temp": item["main"]["temp"],
                "description": item["weather"][0]["description"],
                "icon": item["weather"][0]["icon"],
                "wind_speed": item["wind"]["speed"],
                "humidity": item["main"]["humidity"]
            })

        response = {
            "city": data[0]["city"]["name"],
            "country": data[0]["city"]["country"],
            "forecast": forecast,
            "updated_at": data[0]["collected_at"].strftime("%Y-%m-%d %H:%M:%S")
        }

        return jsonify(response)
    except Exception as e:
        logger.error(f"Error obteniendo pronóstico: {e}")
        return jsonify({"error": str(e)}), 500

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

        # Convertir ObjectId y datetime a formato serializable
        return json.loads(json_util.dumps(alerts))
    except Exception as e:
        logger.error(f"Error obteniendo alertas: {e}")
        return jsonify({"error": str(e)}), 500

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
            "last_update": None
        }

        # Obtener última actualización
        last_entry = db[hourly_collection].find_one(
            sort=[("collected_at", -1)]
        )

        if last_entry:
            stats["last_update"] = last_entry["collected_at"].strftime("%Y-%m-%d %H:%M:%S")
        else:
            stats["last_update"] = "No hay datos"

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

if __name__ == '__main__':
    logger.info(f"Iniciando API en {API_CONFIG['host']}:{API_CONFIG['port']}")
    app.run(
        host=API_CONFIG['host'],
        port=API_CONFIG['port'],
        debug=API_CONFIG['debug']
    )
