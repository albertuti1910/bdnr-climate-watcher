"""
Archivo de configuración para el sistema de análisis climático.
Contiene configuraciones para:
- Lista de ciudades a monitorizar
- Umbrales para alertas meteorológicas
- Intervalos de recolección de datos
"""
import os
from dotenv import load_dotenv

# Cargar variables de entorno
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path)

# Lista de ciudades para monitorizar
CITIES = [
    {"name": "Las Palmas de Gran Canaria", "lat": 28.151286, "lon": -15.427340},
    {"name": "Santa Cruz de Tenerife", "lat": 28.463163, "lon": -16.251866},
    #{"name": "Madrid", "lat": 40.416775, "lon": -3.703790},
]

# Umbrales para alertas meteorológicas
THRESHOLDS = {
    'temp_high': 10.0,
    'temp_low': 5.0,
    'wind': 10.0,
    'humidity': 90.0,
    'rain_prob': 80.0,
}

# Intervalos de tiempo (en segundos)
INTERVALS = {
    'collection': int(os.getenv('COLLECTION_INTERVAL', '60')),
}

# Configuración de MongoDB
MONGO_CONFIG = {
    'uri': os.getenv('MONGO_URI', 'mongodb://admin:password@mongodb:27017/'),
    'db_name': 'weather_db',
    'collections': {
        'hourly_forecast': 'hourly_forecasts',
    }
}

# Configuración de API
API_CONFIG = {
    'port': int(os.getenv('API_PORT', '5000')),
    'debug': os.getenv('API_DEBUG', 'false').lower() == 'true',
    'host': os.getenv('API_HOST', '0.0.0.0'),
    'rate_limit': os.getenv('API_RATE_LIMIT', '100/minute'),
    'cache_timeout': int(os.getenv('CACHE_TIMEOUT', '300')),
}

# API Key de OpenWeatherMap
OPENWEATHER_API_KEY = os.getenv('OPENWEATHER_API_KEY')

# Función para verificar configuración crítica
def verify_config():
    """Verifica que la configuración crítica esté presente"""
    if not OPENWEATHER_API_KEY:
        raise ValueError("¡OPENWEATHER_API_KEY no está configurada! Verifica tu archivo .env")

    if not MONGO_CONFIG['uri']:
        raise ValueError("¡MONGO_URI no está configurada! Verifica tu archivo .env")

# Verificar configuración al importar
verify_config()