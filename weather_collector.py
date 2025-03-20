import requests
import pymongo
from datetime import datetime, timedelta
import time
import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Configuración de API OpenWeatherMap
API_KEY = os.getenv("OPENWEATHER_API_KEY")
FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"  # Endpoint de pronóstico de 5 días

# Configuración de MongoDB
MONGO_URI = os.getenv("MONGO_URI", "mongodb://admin:password@localhost:27017")
DB_NAME = "weather_db"
COLLECTION_NAME = "weather_forecast"

# Lista de ciudades para monitorear
CITIES = [
    {"name": "Madrid", "country": "ES"},
    {"name": "Barcelona", "country": "ES"},
    {"name": "Valencia", "country": "ES"},
    {"name": "Bilbao", "country": "ES"},
    {"name": "Sevilla", "country": "ES"}
]

def connect_to_mongodb():
    """Establece conexión con MongoDB"""
    try:
        client = pymongo.MongoClient(MONGO_URI)
        db = client[DB_NAME]
        collection = db[COLLECTION_NAME]

        # Crear índice compuesto para ciudad y fecha de pronóstico
        collection.create_index([("city_id", 1), ("forecast_time", 1)], unique=True)

        return client, collection
    except Exception as e:
        print(f"Error al conectar con MongoDB: {e}")
        return None, None

def get_forecast_data(city, country):
    """Obtiene datos de pronóstico de OpenWeatherMap API"""
    params = {
        "q": f"{city},{country}",
        "appid": API_KEY,
        "units": "metric",  # Temperaturas en Celsius
        "cnt": 40  # Máximo número de periodos (5 días * 8 periodos por día)
    }

    response = requests.get(FORECAST_URL, params=params)

    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error al obtener datos para {city}: {response.status_code}")
        return None

def process_forecast_data(forecast_data):
    """Procesa los datos de pronóstico para almacenarlos en MongoDB"""
    if not forecast_data or "list" not in forecast_data:
        return []

    city_id = forecast_data["city"]["id"]
    city_name = forecast_data["city"]["name"]
    country = forecast_data["city"]["country"]

    processed_forecasts = []

    for forecast in forecast_data["list"]:
        # Crear un documento para cada periodo de pronóstico
        forecast_time = datetime.fromtimestamp(forecast["dt"])

        forecast_doc = {
            "city_id": city_id,
            "city_name": city_name,
            "country": country,
            "forecast_time": forecast_time,
            "timestamp_collected": datetime.now(),
            "temperature": forecast["main"]["temp"],
            "feels_like": forecast["main"]["feels_like"],
            "temp_min": forecast["main"]["temp_min"],
            "temp_max": forecast["main"]["temp_max"],
            "pressure": forecast["main"]["pressure"],
            "humidity": forecast["main"]["humidity"],
            "weather_main": forecast["weather"][0]["main"],
            "weather_description": forecast["weather"][0]["description"],
            "weather_icon": forecast["weather"][0]["icon"],
            "clouds": forecast.get("clouds", {}).get("all", 0),
            "wind_speed": forecast.get("wind", {}).get("speed", 0),
            "wind_deg": forecast.get("wind", {}).get("deg", 0),
            "rain_3h": forecast.get("rain", {}).get("3h", 0),
            "snow_3h": forecast.get("snow", {}).get("3h", 0),
            "is_historical": False  # Inicialmente todos son pronósticos futuros
        }

        processed_forecasts.append(forecast_doc)

    return processed_forecasts

def store_forecasts(forecasts, collection):
    """Almacena los pronósticos en MongoDB con lógica de actualización"""
    if not forecasts:
        return 0

    current_time = datetime.now()
    updated_count = 0

    for forecast in forecasts:
        forecast_time = forecast["forecast_time"]

        # Marcar como histórico si el tiempo de pronóstico ya pasó
        if forecast_time < current_time:
            forecast["is_historical"] = True

        # Preparar filtro para actualización
        filter_query = {
            "city_id": forecast["city_id"],
            "forecast_time": forecast["forecast_time"]
        }

        try:
            # Si es histórico, no actualizamos
            if forecast["is_historical"]:
                # Verificar si ya existe (insertamos solo si no existe)
                if collection.count_documents(filter_query) == 0:
                    collection.insert_one(forecast)
                    updated_count += 1
            else:
                # Para pronósticos futuros, usamos upsert para actualizar o insertar
                result = collection.update_one(
                    filter_query,
                    {"$set": forecast},
                    upsert=True
                )
                if result.modified_count > 0 or result.upserted_id is not None:
                    updated_count += 1
        except Exception as e:
            print(f"Error al almacenar pronóstico: {e}")

    return updated_count

def mark_old_forecasts_as_historical(collection):
    """Marca como históricos los pronósticos cuya fecha ya ha pasado"""
    current_time = datetime.now()

    result = collection.update_many(
        {
            "forecast_time": {"$lt": current_time},
            "is_historical": False
        },
        {"$set": {"is_historical": True}}
    )

    if result.modified_count > 0:
        print(f"Se marcaron {result.modified_count} pronósticos como históricos")

def collect_forecast_data():
    """Recoge y almacena datos de pronóstico para todas las ciudades"""
    client, collection = connect_to_mongodb()

    if collection is None:
        print("No se pudo conectar a MongoDB")
        return

    total_updates = 0

    for city in CITIES:
        print(f"Obteniendo pronóstico para {city['name']}, {city['country']}...")
        forecast_data = get_forecast_data(city["name"], city["country"])

        if forecast_data:
            processed_forecasts = process_forecast_data(forecast_data)
            updates = store_forecasts(processed_forecasts, collection)
            total_updates += updates
            print(f"  - {updates} pronósticos actualizados/añadidos")

        # Esperar un poco entre solicitudes para no sobrecargar la API
        time.sleep(1)

    # Marcar pronósticos antiguos como históricos
    mark_old_forecasts_as_historical(collection)

    client.close()
    print(f"Total de actualizaciones: {total_updates}")

def main():
    """Función principal que se ejecuta continuamente"""
    print("Iniciando recolección de datos de pronóstico climático...")

    while True:
        collect_forecast_data()
        print(f"Ciclo completado. Esperando para el próximo ciclo...")
        # Esperar 1 hora antes del próximo ciclo de recolección
        time.sleep(3600)  # 3600 segundos = 1 hora

if __name__ == "__main__":
    main()
