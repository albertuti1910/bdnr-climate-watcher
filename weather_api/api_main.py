from flask import Flask, jsonify, render_template, request
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
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Función para obtener un cliente MongoDB con connection pooling
def get_mongo_client():
    """Función para obtener un cliente MongoDB con conexión pooling configurada"""
    return pymongo.MongoClient(
        MONGO_CONFIG['uri'],
        maxPoolSize=10,  # Ajustar según la carga esperada
        minPoolSize=1,
        maxIdleTimeMS=30000,
        socketTimeoutMS=45000,
        connectTimeoutMS=10000,
        serverSelectionTimeoutMS=10000,
        waitQueueTimeoutMS=10000  # Tiempo máximo de espera si todas las conexiones están en uso
    )

# Configuración de MongoDB
try:
    client = get_mongo_client()
    db = client[MONGO_CONFIG['db_name']]
    logger.info("Conexión a MongoDB establecida correctamente")
except Exception as e:
    logger.error(f"Error conectando a MongoDB: {e}")
    raise

@app.route('/')
def index():
    """Página principal del dashboard"""
    return render_template('index.html')

@app.route('/health')
def health():
    """Endpoint para verificar el estado del servicio"""
    try:
        # Verificar conexión a MongoDB
        db.command('ping')
        return jsonify({"status": "ok", "service": "weather_api"}), 200
    except Exception as e:
        logger.error(f"Health check falló: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

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
        date_limit = datetime.utcnow() - timedelta(days=days)

        # Buscar todos los documentos de la ciudad a partir de la fecha límite
        results = db[MONGO_CONFIG['collections']['hourly_forecast']].find({
            "city.name": city,
            "collected_at": {"$gte": date_limit}
        })

        # Unir todos los pronósticos individuales en una lista única
        forecast_list = []
        for doc in results:
            forecast_list.extend(doc.get("list", []))

        if not forecast_list:
            return jsonify([])

        # Eliminar duplicados por timestamp
        seen = set()
        unique_forecasts = []
        for item in forecast_list:
            if item["dt"] not in seen:
                seen.add(item["dt"])
                unique_forecasts.append(item)

        # Convertir a estructura con fecha
        processed = []
        for f in unique_forecasts:
            forecast_dt = datetime.fromtimestamp(f["dt"])
            if forecast_dt < datetime.utcnow():  # Solo históricos (pasado)
                processed.append({
                    "date": forecast_dt.date().isoformat(),
                    "temp": f["main"]["temp"],
                    "temp_min": f["main"].get("temp_min", f["main"]["temp"]),
                    "temp_max": f["main"].get("temp_max", f["main"]["temp"]),
                    "humidity": f["main"]["humidity"],
                    "pressure": f["main"]["pressure"]
                })

        # Agrupar por día
        from collections import defaultdict
        grouped = defaultdict(list)
        for item in processed:
            grouped[item["date"]].append(item)

        # Calcular promedios por día
        result = []
        for date, items in grouped.items():
            avg_temp = sum(i["temp"] for i in items) / len(items)
            min_temp = min(i["temp_min"] for i in items)
            max_temp = max(i["temp_max"] for i in items)
            avg_humidity = sum(i["humidity"] for i in items) / len(items)
            avg_pressure = sum(i["pressure"] for i in items) / len(items)

            result.append({
                "_id": date,
                "avg_temp": round(avg_temp, 2),
                "min_temp": round(min_temp, 2),
                "max_temp": round(max_temp, 2),
                "avg_humidity": round(avg_humidity, 2),
                "avg_pressure": round(avg_pressure, 2),
                "data_points": len(items)
            })

        # Ordenar por fecha
        result = sorted(result, key=lambda x: x["_id"])

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error obteniendo datos históricos: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/forecast/<city>')
def get_forecast(city):
    """Obtiene el pronóstico más reciente para una ciudad"""
    try:
        # Buscar todos los pronósticos de la ciudad (últimos 4 días)
        results = db[MONGO_CONFIG['collections']['hourly_forecast']].find(
            {"city.name": city}
        )

        # Unir todas las listas de pronósticos
        forecast_list = []
        for doc in results:
            forecast_list.extend(doc.get("list", []))

        if not forecast_list:
            return jsonify({"error": "Pronóstico no encontrado"}), 404

        # Eliminar duplicados por 'dt'
        seen = set()
        unique_forecasts = []
        for f in forecast_list:
            if f["dt"] not in seen:
                unique_forecasts.append(f)
                seen.add(f["dt"])

        # Ordenar cronológicamente
        forecast_list = sorted(unique_forecasts, key=lambda x: x["dt"])

        now = datetime.utcnow()
        forecast = []

        # Filtrar pronósticos futuros
        future_forecasts = [f for f in forecast_list if datetime.fromtimestamp(f["dt"]) > now]

        if len(future_forecasts) < 2:
            # Agregar el pronóstico más reciente del pasado
            past_forecasts = [f for f in forecast_list if datetime.fromtimestamp(f["dt"]) <= now]
            if past_forecasts:
                most_recent = max(past_forecasts, key=lambda x: x["dt"])
                future_forecasts = [most_recent] + future_forecasts

        forecast_items = future_forecasts[:12]

        for item in forecast_items:
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

        # Obtener la ciudad desde el último documento insertado
        latest_doc = db[MONGO_CONFIG['collections']['hourly_forecast']].find_one(
            {"city.name": city}, sort=[("collected_at", -1)]
        )

        response = {
            "city": city,
            "country": latest_doc.get("city", {}).get("country", "") if latest_doc else "",
            "forecast": forecast,
            "updated_at": latest_doc["collected_at"].strftime("%Y-%m-%d %H:%M:%S") if latest_doc else ""
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
