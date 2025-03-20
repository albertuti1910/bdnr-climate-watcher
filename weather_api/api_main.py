from flask import Flask, jsonify, render_template, request
import pymongo
from datetime import datetime, timedelta
from bson import json_util
import json
import logging

from config import THRESHOLDS, MONGO_CONFIG, API_CONFIG

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuración de MongoDB
MONGO_URI = MONGO_CONFIG['uri']
client = pymongo.MongoClient(MONGO_URI)
db = client[MONGO_CONFIG['db_name']]

@app.route('/')
def index():
    """Página principal del dashboard"""
    return render_template('index.html')

@app.route('/api/cities')
def get_cities():
    """Devuelve la lista de ciudades disponibles"""
    cities = db[MONGO_CONFIG['collections']['current']].distinct("name")
    return jsonify(cities)

@app.route('/api/current/<city>')
def get_current_weather(city):
    """Obtiene el clima actual de una ciudad específica"""
    result = db[MONGO_CONFIG['collections']['current']].find({"name": city}).sort("collected_at", -1).limit(1)
    data = list(result)

    if not data:
        return jsonify({"error": "Ciudad no encontrada"}), 404

    # Convertir ObjectId a string para serialización JSON
    return json.loads(json_util.dumps(data[0]))

@app.route('/api/historical/<city>')
def get_historical_data(city):
    """Obtiene datos históricos para una ciudad"""
    days = int(request.args.get('days', 7))  # Por defecto, últimos 7 días

    # Calcular fecha límite
    date_limit = datetime.utcnow() - timedelta(days=days)

    # Consulta para obtener datos agrupados por día
    pipeline = [
        {"$match": {"name": city, "collected_at": {"$gte": date_limit}}},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$collected_at"}},
            "avg_temp": {"$avg": "$main.temp"},
            "min_temp": {"$min": "$main.temp_min"},
            "max_temp": {"$max": "$main.temp_max"},
            "avg_humidity": {"$avg": "$main.humidity"},
            "avg_pressure": {"$avg": "$main.pressure"},
        }},
        {"$sort": {"_id": 1}}
    ]

    results = list(db[MONGO_CONFIG['collections']['current']].aggregate(pipeline))
    return json.loads(json_util.dumps(results))

@app.route('/api/forecast/<city>')
def get_forecast(city):
    """Obtiene el pronóstico más reciente para una ciudad"""
    result = db[MONGO_CONFIG['collections']['forecast']].find({"city.name": city}).sort("collected_at", -1).limit(1)
    data = list(result)

    if not data:
        return jsonify({"error": "Pronóstico no encontrado"}), 404

    # Simplificar la respuesta para incluir solo datos relevantes
    forecast = []
    for item in data[0]["list"]:
        forecast.append({
            "datetime": item["dt_txt"],
            "temp": item["main"]["temp"],
            "description": item["weather"][0]["description"],
            "icon": item["weather"][0]["icon"],
            "wind_speed": item["wind"]["speed"],
            "humidity": item["main"]["humidity"]
        })

    response = {
        "city": data[0]["city"]["name"],
        "country": data[0]["city"]["country"],
        "forecast": forecast
    }

    return jsonify(response)

@app.route('/api/alerts')
def get_alerts():
    """Obtiene alertas meteorológicas activas"""
    # Criterios para generar alertas basados en los umbrales de config.py
    pipeline = [
        # Obtener datos más recientes para cada ciudad
        {"$sort": {"collected_at": -1}},
        {"$group": {
            "_id": "$name",
            "latest": {"$first": "$$ROOT"}
        }},
        {"$replaceRoot": {"newRoot": "$latest"}},
        # Aplicar criterios de alerta
        {"$match": {
            "$or": [
                {"main.temp": {"$gt": THRESHOLDS['temp_high']}},  # Alerta por calor extremo
                {"main.temp": {"$lt": THRESHOLDS['temp_low']}},   # Alerta por frío extremo
                {"wind.speed": {"$gt": THRESHOLDS['wind']}},      # Alerta por vientos fuertes
                {"main.humidity": {"$gt": THRESHOLDS['humidity']}} # Alerta por humedad extrema
            ]
        }},
        # Proyectar solo los campos necesarios
        {"$project": {
            "_id": 0,
            "city": "$name",
            "country": "$sys.country",
            "temp": "$main.temp",
            "wind_speed": "$wind.speed",
            "humidity": "$main.humidity",
            "collected_at": 1,
            "alert_type": {
                "$cond": [
                    {"$gt": ["$main.temp", THRESHOLDS['temp_high']]},
                    "Calor extremo",
                    {"$cond": [
                        {"$lt": ["$main.temp", THRESHOLDS['temp_low']]},
                        "Frío extremo",
                        {"$cond": [
                            {"$gt": ["$wind.speed", THRESHOLDS['wind']]},
                            "Vientos fuertes",
                            "Humedad extrema"
                        ]}
                    ]}
                ]
            }
        }}
    ]

    alerts = list(db[MONGO_CONFIG['collections']['current']].aggregate(pipeline))
    return json.loads(json_util.dumps(alerts))

@app.route('/api/stats')
def get_stats():
    """Obtiene estadísticas generales del sistema"""
    stats = {
        "total_records": db[MONGO_CONFIG['collections']['current']].count_documents({}),
        "total_forecasts": db[MONGO_CONFIG['collections']['forecast']].count_documents({}),
        "cities_count": len(db[MONGO_CONFIG['collections']['current']].distinct("name")),
        "last_update": db[MONGO_CONFIG['collections']['current']].find_one(
            sort=[("collected_at", -1)]
        )["collected_at"].strftime("%Y-%m-%d %H:%M:%S") if db[MONGO_CONFIG['collections']['current']].count_documents({}) > 0 else "No hay datos"
    }
    return jsonify(stats)

@app.route('/api/config/thresholds')
def get_thresholds():
    """Devuelve los umbrales de alertas actuales"""
    return jsonify(THRESHOLDS)

if __name__ == '__main__':
    logger.info(f"Iniciando API en {API_CONFIG['host']}:{API_CONFIG['port']}")
    app.run(
        host=API_CONFIG['host'],
        port=API_CONFIG['port'],
        debug=API_CONFIG['debug']
    )
