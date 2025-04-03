import time
import requests
import logging
import backoff
from datetime import datetime, timezone
from collections import Counter
from pymongo import MongoClient, UpdateOne
from requests.exceptions import RequestException, HTTPError, Timeout, ConnectionError

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuración desde variables de entorno y archivo config.py
from config import CITIES, INTERVALS, MONGO_CONFIG, OPENWEATHER_API_KEY

# Variables para métricas
metrics = {
    'api_calls': 0,
    'api_errors': 0,
    'successful_updates': 0,
    'failed_updates': 0,
    'api_response_times': [],
    'db_write_times': [],
    'last_run_stats': {}
}

# Mostrar número de ciudades que serán monitorizadas
logger.info(f"Configuración cargada. Monitorizando {len(CITIES)} ciudades.")

def get_mongo_client():
    """Función para obtener un cliente MongoDB con conexión pooling configurada"""
    return MongoClient(
        MONGO_CONFIG['uri'],
        maxPoolSize=10,  # Ajustar según la carga esperada
        minPoolSize=1,
        maxIdleTimeMS=30000,
        socketTimeoutMS=45000,
        connectTimeoutMS=10000,
        serverSelectionTimeoutMS=10000,
        waitQueueTimeoutMS=10000  # Tiempo máximo de espera si todas las conexiones están en uso
    )

def connect_to_mongodb():
    """Establece conexión con MongoDB usando connection pooling"""
    try:
        client = get_mongo_client()
        db = client[MONGO_CONFIG['db_name']]
        logger.info("Conexión exitosa a MongoDB")
        return db
    except Exception as e:
        logger.error(f"Error conectando a MongoDB: {e}")
        raise

def validate_forecast_data(data):
    """Valida que los datos del pronóstico tengan la estructura esperada"""
    if not data:
        return False

    # Verificar campos críticos
    if 'list' not in data or not isinstance(data['list'], list) or len(data['list']) == 0:
        logger.error("Datos recibidos sin pronósticos en 'list'")
        return False

    # Verificar que city exista
    if 'city' not in data:
        logger.error("Datos recibidos sin información de ciudad")
        return False

    # Verificar estructura de cada elemento de pronóstico
    for forecast in data['list'][:1]:  # Revisar al menos el primer elemento
        if 'dt' not in forecast or 'main' not in forecast or 'weather' not in forecast:
            logger.error("Estructura de pronóstico incorrecta")
            return False

        if not isinstance(forecast['weather'], list) or len(forecast['weather']) == 0:
            logger.error("Estructura de 'weather' incorrecta")
            return False

    return True

@backoff.on_exception(
    backoff.expo,  # Usa backoff exponencial (esperas cada vez más largas)
    (RequestException, HTTPError, Timeout, ConnectionError),  # Excepciones a capturar
    max_tries=5,   # Número máximo de intentos
    max_time=30,   # Tiempo máximo total en segundos
    jitter=None    # Añade variabilidad al tiempo de espera para evitar sincronización
)
def fetch_hourly_forecast(lat, lon):
    """Obtiene pronóstico por hora para unas coordenadas específicas (4 días)"""
    url = f"https://pro.openweathermap.org/data/2.5/forecast/hourly?lat={lat}&lon={lon}&units=metric&appid={OPENWEATHER_API_KEY}"

    try:
        api_start = time.time()
        response = requests.get(url, timeout=10)  # Añadir timeout explícito
        response.raise_for_status()  # Lanzará HTTPError para códigos 4xx/5xx
        data = response.json()

        # Validar datos antes de devolverlos
        if not validate_forecast_data(data):
            raise ValueError(f"Datos recibidos inválidos para lat:{lat}, lon:{lon}")

        # Añadir timestamp para análisis temporal
        data['collected_at'] = datetime.utcnow()

        return data
    except Exception as e:
        logger.error(f"Error obteniendo pronóstico por hora para coordenadas lat:{lat}, lon:{lon}: {e}")
        raise  # Importante: re-lanzar la excepción para que backoff funcione

def store_differential_data(db, data, city_name):
    """
    Almacena datos de manera diferencial en MongoDB:
    - Si los datos para un timestamp específico no existen, los inserta
    - Si existen pero son diferentes, los actualiza
    - Si son iguales, no hace nada
    """
    try:
        db_start = time.time()
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

            metrics['db_write_times'].append(time.time() - db_start)
            return updated_count

    except Exception as e:
        logger.error(f"Error almacenando datos diferenciales para {city_name}: {e}")
        raise

def save_metrics_to_db(db):
    """Guarda las métricas actuales en MongoDB"""
    try:
        # Calcular algunas estadísticas
        avg_api_time = sum(metrics['api_response_times']) / len(metrics['api_response_times']) if metrics['api_response_times'] else 0
        avg_db_time = sum(metrics['db_write_times']) / len(metrics['db_write_times']) if metrics['db_write_times'] else 0

        # Preparar documento
        doc = {
            "service": "weather_collector",
            "timestamp": datetime.utcnow(),
            "api_calls_total": metrics['api_calls'],
            "api_errors_total": metrics['api_errors'],
            "successful_updates_total": metrics['successful_updates'],
            "failed_updates_total": metrics['failed_updates'],
            "avg_api_response_time": avg_api_time,
            "avg_db_write_time": avg_db_time,
            "last_run": metrics['last_run_stats']
        }

        # Guardar en la colección de métricas
        db['system_metrics'].insert_one(doc)

        # Limpiar métricas temporales
        metrics['api_response_times'] = []
        metrics['db_write_times'] = []

        logger.info("Métricas guardadas correctamente")
    except Exception as e:
        logger.error(f"Error guardando métricas: {e}")

def collect_data():
    """Función principal para recolectar y almacenar datos"""
    start_time = time.time()
    metrics['last_run_stats'] = {
        'start_time': datetime.utcnow().isoformat(),
        'city_results': Counter(),
    }

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
                metrics['last_run_stats']['city_results'][city_name] = 'omitted: no coordinates'
                continue

            try:
                metrics['api_calls'] += 1
                api_start = time.time()
                hourly_data = fetch_hourly_forecast(lat, lon)
                metrics['api_response_times'].append(time.time() - api_start)

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
                    metrics['successful_updates'] += updates
                    metrics['last_run_stats']['city_results'][city_name] = 'success'
                else:
                    metrics['failed_updates'] += 1
                    metrics['last_run_stats']['city_results'][city_name] = 'error: no data'
            except Exception as e:
                metrics['api_errors'] += 1
                metrics['failed_updates'] += 1
                metrics['last_run_stats']['city_results'][city_name] = f'error: {str(e)}'
                logger.error(f"Error procesando {city_name}: {e}")

            # Pequeña pausa para no sobrecargar la API
            time.sleep(1)

        metrics['last_run_stats']['duration'] = time.time() - start_time
        metrics['last_run_stats']['end_time'] = datetime.utcnow().isoformat()
        metrics['last_run_stats']['total_updates'] = total_updates

        # Guardar métricas
        save_metrics_to_db(db)

        logger.info(f"Recolección completada en {metrics['last_run_stats']['duration']:.2f}s. "
                    f"Total de actualizaciones: {total_updates}. "
                    f"Éxitos: {metrics['successful_updates']}, "
                    f"Errores: {metrics['api_errors']}")

    except Exception as e:
        logger.error(f"Error en proceso de recolección: {e}")
        metrics['last_run_stats']['error'] = str(e)
        metrics['last_run_stats']['duration'] = time.time() - start_time
        metrics['last_run_stats']['end_time'] = datetime.utcnow().isoformat()

        # Intentar guardar métricas incluso en caso de error
        try:
            db = connect_to_mongodb()
            save_metrics_to_db(db)
        except:
            logger.error("No se pudieron guardar métricas debido a un error")

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
