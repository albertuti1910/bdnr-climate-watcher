import os
import time
import requests
import logging
from datetime import datetime
from pymongo import MongoClient

from config import CITIES, INTERVALS, MONGO_CONFIG

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuración desde variables de entorno y archivo config.py
OPENWEATHER_API_KEY = os.getenv('OPENWEATHER_API_KEY')
MONGO_URI = MONGO_CONFIG['uri']
COLLECTION_INTERVAL = INTERVALS['collection']

def connect_to_mongodb():
    """Establece conexión con MongoDB"""
    try:
        client = MongoClient(MONGO_URI)
        db = client[MONGO_CONFIG['db_name']]
        logger.info("Conexión exitosa a MongoDB")
        return db
    except Exception as e:
        logger.error(f"Error conectando a MongoDB: {e}")
        raise

def fetch_weather_data(city_id):
    """Obtiene datos climáticos para una ciudad específica"""
    url = f"https://api.openweathermap.org/data/2.5/weather?id={city_id}&appid={OPENWEATHER_API_KEY}&units=metric"

    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()

        # Añadir timestamp para análisis temporal
        data['collected_at'] = datetime.utcnow()

        return data
    except requests.exceptions.RequestException as e:
        logger.error(f"Error obteniendo datos para ciudad {city_id}: {e}")
        return None

def fetch_forecast_data(city_id):
    """Obtiene pronóstico para una ciudad específica (5 días / 3 horas)"""
    url = f"https://api.openweathermap.org/data/2.5/forecast?id={city_id}&appid={OPENWEATHER_API_KEY}&units=metric"

    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()

        # Añadir timestamp para análisis temporal
        data['collected_at'] = datetime.utcnow()

        return data
    except requests.exceptions.RequestException as e:
        logger.error(f"Error obteniendo pronóstico para ciudad {city_id}: {e}")
        return None

def store_weather_data(db, data):
    """Almacena datos climáticos en MongoDB"""
    try:
        collection = db[MONGO_CONFIG['collections']['current']]
        result = collection.insert_one(data)
        logger.info(f"Datos almacenados para {data.get('name')}, ID: {result.inserted_id}")
        return result.inserted_id
    except Exception as e:
        logger.error(f"Error almacenando datos: {e}")
        return None

def store_forecast_data(db, data):
    """Almacena datos de pronóstico en MongoDB"""
    try:
        collection = db[MONGO_CONFIG['collections']['forecast']]
        result = collection.insert_one(data)
        logger.info(f"Pronóstico almacenado para {data.get('city', {}).get('name')}, ID: {result.inserted_id}")
        return result.inserted_id
    except Exception as e:
        logger.error(f"Error almacenando pronóstico: {e}")
        return None

def collect_data():
    """Función principal para recolectar y almacenar datos"""
    try:
        db = connect_to_mongodb()

        # Crear índices para mejorar rendimiento en consultas
        db[MONGO_CONFIG['collections']['current']].create_index([("collected_at", 1)])
        db[MONGO_CONFIG['collections']['current']].create_index([("name", 1)])
        db[MONGO_CONFIG['collections']['forecast']].create_index([("collected_at", 1)])
        db[MONGO_CONFIG['collections']['forecast']].create_index([("city.name", 1)])

        logger.info(f"Iniciando recolección para {len(CITIES)} ciudades")

        for city in CITIES:
            # Obtener y almacenar clima actual
            weather_data = fetch_weather_data(city["id"])
            if weather_data:
                store_weather_data(db, weather_data)

            # Obtener y almacenar pronóstico
            forecast_data = fetch_forecast_data(city["id"])
            if forecast_data:
                store_forecast_data(db, forecast_data)

            # Pequeña pausa para no sobrecargar la API
            time.sleep(1)

    except Exception as e:
        logger.error(f"Error en proceso de recolección: {e}")

def main():
    """Función principal que ejecuta la recolección periódicamente"""
    logger.info("Iniciando servicio de recolección de datos climáticos")
    logger.info(f"Monitorizando {len(CITIES)} ciudades")

    while True:
        try:
            logger.info(f"Iniciando recolección de datos. Próxima ejecución en {COLLECTION_INTERVAL} segundos")
            collect_data()
            logger.info("Recolección completada")

            # Esperar hasta la próxima recolección
            time.sleep(COLLECTION_INTERVAL)

        except Exception as e:
            logger.error(f"Error en ciclo principal: {e}")
            # En caso de error, esperar un minuto antes de reintentar
            time.sleep(60)

if __name__ == "__main__":
    main()
