"""
Archivo de configuración para el sistema de análisis climático.
Contiene configuraciones para:
- Lista de ciudades a monitorizar
- Umbrales para alertas meteorológicas
- Otros parámetros configurables
"""

import os
from dotenv import load_dotenv

# Cargar variables de entorno
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path)

# Lista de ciudades para monitorizar
# Formato: {"id": ID_OPENWEATHER, "name": "NOMBRE_CIUDAD", "country": "CÓDIGO_PAÍS"}
CITIES = [
    {"id": 2515270, "name": "Las Palmas", "country": "ES"},
    {"id": 2511174, "name": "Santa Cruz de Tenerife", "country": "ES"},
    {"id": 3117735, "name": "Madrid", "country": "ES"},
    #{"id": 2643743, "name": "London", "country": "GB"},
    #{"id": 5128581, "name": "New York", "country": "US"},
    # Añade más ciudades según necesites
    # Puedes encontrar los IDs de ciudad en: https://openweathermap.org/
    # Busca la ciudad y toma el ID de la URL
]

# Umbrales para alertas meteorológicas
THRESHOLDS = {
    'temp_high': float(os.getenv('THRESHOLD_TEMP_HIGH', 18.0)),
    'temp_low': float(os.getenv('THRESHOLD_TEMP_LOW', 0.0)),
    'wind': float(os.getenv('THRESHOLD_WIND', 20.0)),
    'humidity': float(os.getenv('THRESHOLD_HUMIDITY', 95.0)),
    'rain': float(os.getenv('THRESHOLD_RAIN', 10.0))
}

# THRESHOLDS = {
#     'temp_high': float(os.getenv('THRESHOLD_TEMP_HIGH')),
#     'temp_low': float(os.getenv('THRESHOLD_TEMP_LOW')),
#     'wind': float(os.getenv('THRESHOLD_WIND')),
#     'humidity': float(os.getenv('THRESHOLD_HUMIDITY')),
#     'rain': float(os.getenv('THRESHOLD_RAIN'))
# }

# Intervalos de tiempo (en segundos)
def safe_int(value, default):
    """Convierte de forma segura un valor a entero"""
    try:
        if isinstance(value, str):
            # Eliminar comentarios y espacios
            cleaned_value = value.split('#')[0].strip()
            return int(cleaned_value)
        elif value is None:
            return default
        return int(value)
    except (ValueError, IndexError):
        return default

# Intervalos de tiempo (en segundos)
collection_interval_raw = os.getenv('COLLECTION_INTERVAL', '3600')
print(f"HOlaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" + collection_interval_raw)

INTERVALS = {
    'collection': safe_int(collection_interval_raw, 3600),
    'analysis': safe_int(os.getenv('ANALYSIS_INTERVAL', '86400'), 86400),
    'alert_check': safe_int(os.getenv('CHECK_INTERVAL', '3600'), 3600)
}

# Configuración de MongoDB
MONGO_CONFIG = {
    'uri': os.getenv('MONGO_URI', 'mongodb://admin:password@mongodb:27017/'),
    'db_name': os.getenv('MONGO_DB_NAME', 'weather_db'),
    'collections': {
        'current': 'current_weather',
        'forecast': 'forecasts',
        'analysis': 'analysis_results',
        'alerts': 'weather_alerts'
    }
}

# Configuración de API
API_CONFIG = {
    'port': int(os.getenv('API_PORT', 5000)),
    'debug': os.getenv('DEBUG_MODE', 'false').lower() == 'true',
    'host': os.getenv('API_HOST', '0.0.0.0')
}

# Personalización de alertas
ALERT_CONFIG = {
    'enable_telegram': os.getenv('ENABLE_TELEGRAM', 'false').lower() == 'true',
    'enable_email': os.getenv('ENABLE_EMAIL', 'false').lower() == 'true',
    'email_from': os.getenv('EMAIL_FROM', ''),
    'email_to': os.getenv('EMAIL_TO', '').split(','),
    'telegram_admin_id': int(os.getenv('TELEGRAM_ADMIN_ID', 0)) if os.getenv('TELEGRAM_ADMIN_ID') else None
}

# Opciones para el analizador de datos
ANALYZER_CONFIG = {
    'output_dir': os.getenv('OUTPUT_DIR', '/app/data'),
    'generate_plots': os.getenv('GENERATE_PLOTS', 'true').lower() == 'true',
    'plot_format': os.getenv('PLOT_FORMAT', 'png'),
    'analysis_days': int(os.getenv('ANALYSIS_DAYS', 180))
}
