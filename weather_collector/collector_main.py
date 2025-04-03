import os
import time
import requests
import logging
from datetime import datetime
from pymongo import MongoClient, UpdateOne

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuración desde variables de entorno y archivo config.py
from config import CITIES, INTERVALS, MONGO_CONFIG, OPENWEATHER_API_KEY

# Mostrar número de ciudades que serán monitorizadas
logger.info(f"Configuración cargada. Monitorizando {len(CITIES)} ciudades.")

def connect_to_mongodb():
    """Establece conexión con MongoDB"""
    try:
        client = MongoClient(MONGO_CONFIG['uri'])
        db = client[MONGO_CONFIG['db_name']]
        logger.info("Conexión exitosa a MongoDB")
        return db
    except Exception as e:
        logger.error(f"Error conectando a MongoDB: {e}")
        raise

def fetch_hourly_forecast(lat, lon):
    """Obtiene pronóstico por hora para unas coordenadas específicas (4 días)"""
    url = f"https://pro.openweathermap.org/data/2.5/forecast/hourly?lat={lat}&lon={lon}&units=metric&appid={OPENWEATHER_API_KEY}"

    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()

        # Añadir timestamp para análisis temporal
        data['collected_at'] = datetime.utcnow()

        return data
    except requests.exceptions.RequestException as e:
        logger.error(f"Error obteniendo pronóstico por hora para coordenadas lat:{lat}, lon:{lon}: {e}")
        return None

def store_differential_data(db, data, city_name):
    """
    Almacena datos de manera diferencial en MongoDB:
    - Si los datos para un timestamp específico no existen, los inserta
    - Si existen pero son diferentes, los actualiza
    - Si son iguales, no hace nada
    """
    try:
        collection = db[MONGO_CONFIG['collections']['hourly_forecast']]

        if 'list' in data:  # Para pronósticos que tienen una lista de predicciones
            city_id = data.get('city', {}).get('id')

            # Asegurarse de usar el nombre de la ciudad de la configuración
            if 'city' in data:
                # Forzar que el nombre en data sea el de la configuración
                data['city']['name'] = city_name

            # Preparar operaciones en lote
            bulk_operations = []
            updated_count = 0

            for forecast in data['list']:
                # Usar dt (timestamp de la predicción) como identificador único
                forecast_time = forecast.get('dt')

                # Buscar si ya existe un pronóstico para este timestamp y ciudad
                existing = collection.find_one({
                    'city.id': city_id,
                    'list.dt': forecast_time
                })

                if existing:
                    # Verificar si el pronóstico ha cambiado comparando valores clave
                    existing_forecast = next((f for f in existing['list'] if f.get('dt') == forecast_time), None)

                    if existing_forecast:
                        # Comparar temperatura, humedad, etc.
                        if (existing_forecast.get('main', {}).get('temp') != forecast.get('main', {}).get('temp') or
                            existing_forecast.get('main', {}).get('humidity') != forecast.get('main', {}).get('humidity') or
                            existing_forecast.get('weather', [{}])[0].get('id') != forecast.get('weather', [{}])[0].get('id')):

                            # El pronóstico ha cambiado, actualizar
                            bulk_operations.append(
                                UpdateOne(
                                    {'city.id': city_id, 'list.dt': forecast_time},
                                    {'$set': {'list.$': forecast, 'last_updated': datetime.utcnow()}}
                                )
                            )
                            updated_count += 1
                else:
                    # No existe, insertar nuevo documento para esta ciudad y timestamp
                    new_data = {
                        'city': data.get('city', {}),
                        'list': [forecast],
                        'collected_at': datetime.utcnow(),
                        'last_updated': datetime.utcnow()
                    }
                    bulk_operations.append(
                        UpdateOne(
                            {'city.id': city_id, 'list.dt': forecast_time},
                            {'$setOnInsert': new_data},
                            upsert=True
                        )
                    )
                    updated_count += 1

            # Ejecutar operaciones en lote si hay alguna
            if bulk_operations:
                result = collection.bulk_write(bulk_operations)
                logger.info(f"Datos actualizados para {city_name}: {result.modified_count} modificados, {result.upserted_count} insertados")
            else:
                logger.info(f"No se requieren actualizaciones para {city_name}")

            return updated_count

    except Exception as e:
        logger.error(f"Error almacenando datos diferenciales para {city_name}: {e}")
        return 0

def collect_data():
    """Función principal para recolectar y almacenar datos"""
    try:
        db = connect_to_mongodb()

        # Crear índices para mejorar rendimiento en consultas
        collection = db[MONGO_CONFIG['collections']['hourly_forecast']]
        collection.create_index([("city.id", 1), ("list.dt", 1)])
        collection.create_index([("collected_at", 1)])
        collection.create_index([("city.name", 1)])
        collection.create_index([("list.dt", 1)])

        logger.info(f"Iniciando recolección para {len(CITIES)} ciudades")

        total_updates = 0
        for city in CITIES:
            # Obtener pronóstico horario por coordenadas (usar lat/lon en lugar de ID)
            lat = city.get("lat")
            lon = city.get("lon")
            city_name = city.get("name")  # Obtén explícitamente el nombre de la configuración

            if lat is None or lon is None:
                logger.warning(f"Ciudad {city_name} no tiene coordenadas definidas, omitiendo")
                continue

            hourly_data = fetch_hourly_forecast(lat, lon)

            if hourly_data:
                # Asegurar que tenemos los datos de la ciudad correctamente
                if 'city' not in hourly_data and city_name:
                    hourly_data['city'] = {
                        'id': city.get('id'),
                        'name': city_name,  # Usar el nombre de la configuración
                        'coord': {
                            'lat': lat,
                            'lon': lon
                        }
                    }
                # Si 'city' ya existe en hourly_data, sobreescribir el nombre
                elif 'city' in hourly_data and city_name:
                    hourly_data['city']['name'] = city_name  # Forzar el nombre de la configuración

                # Almacenar datos de manera diferencial
                updates = store_differential_data(db, hourly_data, city_name)
                total_updates += updates

            # Pequeña pausa para no sobrecargar la API
            time.sleep(1)

        logger.info(f"Recolección completada. Total de actualizaciones: {total_updates}")

    except Exception as e:
        logger.error(f"Error en proceso de recolección: {e}")

def main():
    """Función principal que ejecuta la recolección periódicamente"""
    logger.info("Iniciando servicio de recolección de datos climáticos")
    logger.info(f"Monitorizando {len(CITIES)} ciudades")
    logger.info(f"Intervalo de recolección: {INTERVALS['collection']} segundos")

    while True:
        try:
            logger.info(f"Iniciando recolección de datos. Próxima ejecución en {INTERVALS['collection']} segundos")
            collect_data()

            # Esperar hasta la próxima recolección
            time.sleep(INTERVALS['collection'])

        except Exception as e:
            logger.error(f"Error en ciclo principal: {e}")
            # En caso de error, esperar un minuto antes de reintentar
            time.sleep(60)

if __name__ == "__main__":
    main()
