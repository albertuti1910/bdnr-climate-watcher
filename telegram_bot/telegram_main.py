import os
import logging
import backoff
from datetime import datetime, timezone, timedelta
import pymongo
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.error import TelegramError, NetworkError
from dotenv import load_dotenv

from config import THRESHOLDS, MONGO_CONFIG

load_dotenv()

# Diccionario para traducir descripciones del tiempo
weather_descriptions = {
    # Condiciones de cielo
    'clear sky': 'Cielo despejado',
    'few clouds': 'Algunas nubes',
    'scattered clouds': 'Nubes dispersas',
    'broken clouds': 'Nubosidad parcial',
    'overcast clouds': 'Cielo cubierto',

    # Lluvia
    'light rain': 'Lluvia débil',
    'moderate rain': 'Lluvia moderada',
    'heavy rain': 'Lluvia fuerte',
    'light intensity drizzle': 'Llovizna débil',
    'drizzle': 'Llovizna',
    'moderate drizzle': 'Llovizna moderada',
    'heavy intensity drizzle': 'Llovizna fuerte',
    'light intensity shower rain': 'Chubasco débil',
    'shower rain': 'Chubasco',
    'heavy intensity shower rain': 'Chubasco fuerte',
    'ragged shower rain': 'Chubasco irregular',

    # Nieve
    'light snow': 'Nevada débil',
    'snow': 'Nevada',
    'moderate snow': 'Nevada moderada',
    'heavy snow': 'Nevada intensa',
    'light shower snow': 'Chubasco de nieve débil',
    'shower snow': 'Chubasco de nieve',
    'heavy shower snow': 'Chubasco de nieve intenso',
    'sleet': 'Aguanieve',
    'light shower sleet': 'Chubasco de aguanieve débil',
    'shower sleet': 'Chubasco de aguanieve',
    'light rain and snow': 'Lluvia y nieve débil',
    'rain and snow': 'Lluvia y nieve',

    # Tormentas
    'thunderstorm': 'Tormenta eléctrica',
    'thunderstorm with light rain': 'Tormenta con lluvia débil',
    'thunderstorm with rain': 'Tormenta con lluvia',
    'thunderstorm with heavy rain': 'Tormenta con lluvia fuerte',

    # Fenómenos de visibilidad reducida
    'mist': 'Neblina',
    'fog': 'Niebla',
    'haze': 'Calima',
    'smoke': 'Humo',
    'dust': 'Polvo en suspensión',
    'sand': 'Arena en suspensión',
    'ash': 'Ceniza volcánica',

    # Otros fenómenos
    'squall': 'Turbonada',
    'tornado': 'Tornado'
}

# Configuración desde variables de entorno
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_ADMIN_ID = os.getenv('TELEGRAM_ADMIN_ID')
CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', 3600))  # Intervalo predeterminado: 1 hora

# Configuración del logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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

# Conexión a MongoDB
try:
    client = get_mongo_client()
    db = client[MONGO_CONFIG['db_name']]
    logger.info("Conexión exitosa a MongoDB")
except Exception as e:
    logger.error(f"Error conectando a MongoDB: {e}")
    raise

# Colección para almacenar preferencias de usuarios
user_prefs_collection = db['user_preferences']

# Crear índice para búsqueda eficiente por user_id
user_prefs_collection.create_index([("user_id", pymongo.ASCENDING)], unique=True)

# Métricas para monitoreo
metrics = {
    'bot_started': datetime.utcnow(),
    'commands_processed': 0,
    'alerts_sent': 0,
    'errors': 0,
    'users_total': 0
}

def save_metrics_to_db():
    """Guarda las métricas actuales en MongoDB"""
    try:
        # Contar usuarios actuales
        metrics['users_total'] = user_prefs_collection.count_documents({})

        doc = {
            "service": "telegram_bot",
            "timestamp": datetime.utcnow(),
            "uptime_hours": (datetime.utcnow() - metrics['bot_started']).total_seconds() / 3600,
            "commands_processed": metrics['commands_processed'],
            "alerts_sent": metrics['alerts_sent'],
            "errors": metrics['errors'],
            "users_total": metrics['users_total']
        }

        db['system_metrics'].insert_one(doc)
        logger.info("Métricas de bot guardadas correctamente")
    except Exception as e:
        logger.error(f"Error guardando métricas de bot: {e}")

def load_user_preferences(user_id):
    """Carga las preferencias del usuario desde la base de datos"""
    try:
        pref = user_prefs_collection.find_one({"user_id": user_id})
        if not pref:
            # Si no existen, crear preferencias por defecto
            now = datetime.utcnow()
            pref = {
                'user_id': user_id,
                'cities': [],
                'alerts': {
                    'temp_high': True,
                    'temp_low': True,
                    'wind': True,
                    'humidity': True,
                    'rain': True
                },
                'alert_interval': CHECK_INTERVAL,  # Intervalo predeterminado
                'alert_history': [],               # Nueva estructura para almacenar historial de alertas
                'last_alert_sent': now - timedelta(hours=24),  # Para que reciba alertas pronto
                'created_at': now,
                'last_activity': now,               # Tracking de actividad
                'thresholds': {
                    'temp_high': 35,
                    'temp_low': 0,
                    'wind': 15,
                    'humidity': 90,
                    'rain': 80
                }
            }
            # Guardar las preferencias por defecto en la base de datos
            user_prefs_collection.insert_one(pref)
            metrics['users_total'] += 1

        # Actualizar última actividad
        user_prefs_collection.update_one(
            {"user_id": user_id},
            {"$set": {"last_activity": datetime.utcnow()}}
        )

        return pref
    except Exception as e:
        logger.error(f"Error cargando preferencias para usuario {user_id}: {e}")
        metrics['errors'] += 1
        # En caso de error, devolver preferencias por defecto pero no guardarlas
        return {
            'user_id': user_id,
            'cities': [],
            'alerts': {
                'temp_high': True,
                'temp_low': True,
                'wind': True,
                'humidity': True,
                'rain': True
            },
            'alert_interval': CHECK_INTERVAL,
            'alert_history': [],
            'last_alert_sent': datetime.utcnow() - timedelta(hours=24),
            'thresholds': {
                'temp_high': 35,
                'temp_low': 0,
                'wind': 15,
                'humidity': 90,
                'rain': 80
            }
        }

def save_user_preferences(user_id, preferences):
    """Guarda las preferencias del usuario en la base de datos"""
    try:
        # Asegurarse de que user_id está en las preferencias
        preferences['user_id'] = user_id
        preferences['updated_at'] = datetime.utcnow()

        user_prefs_collection.update_one(
            {"user_id": user_id},
            {"$set": preferences},
            upsert=True
        )
        return True
    except Exception as e:
        logger.error(f"Error guardando preferencias para usuario {user_id}: {e}")
        metrics['errors'] += 1
        return False

def paginate_keyboard(items, page=0, items_per_page=5):
    """Crea un teclado paginado para listas largas"""
    keyboard = []
    start = page * items_per_page
    end = min(start + items_per_page, len(items))

    # Botones para elementos
    for i in range(start, end):
        keyboard.append([InlineKeyboardButton(items[i], callback_data=f"select_{items[i]}")])

    # Navegación
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"page_{page-1}"))

    # Mostrar número de página actual
    total_pages = (len(items) - 1) // items_per_page + 1
    nav_row.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))

    if end < len(items):
        nav_row.append(InlineKeyboardButton("➡️", callback_data=f"page_{page+1}"))

    if nav_row:
        keyboard.append(nav_row)

    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /start para iniciar el bot"""
    try:
        metrics['commands_processed'] += 1
        user_id = update.effective_user.id

        # Cargar preferencias (se crearán si no existen)
        prefs = load_user_preferences(user_id)

        # Send welcome message
        await update.message.reply_text(
            f"¡Hola {update.effective_user.first_name}! Soy el bot de alertas meteorológicas TiempoNube.\n\n"
            "Puedo enviarte alertas cuando las condiciones climáticas sean extremas "
            "en las ciudades que elijas monitorizar.\n\n"
            "Usa /addcity para añadir una ciudad a tu lista de monitorización.\n"
            "Usa /mycities para ver y gestionar tus ciudades.\n"
            "Usa /alerts para configurar qué tipos de alertas quieres recibir.\n"
            "Usa /weather para obtener el clima actual de tus ciudades.\n"
            "Usa /setinterval para configurar cada cuánto tiempo recibes alertas.\n"
            "Usa /forecast para obtener el pronóstico de 5 días para una ciudad."
        )
    except Exception as e:
        logger.error(f"Error en comando start: {e}")
        metrics['errors'] += 1
        try:
            await update.message.reply_text("Ha ocurrido un error. Por favor, intenta nuevamente.")
        except Exception as send_error:
            logger.error(f"Error sending error message: {send_error}")

async def add_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando para añadir una ciudad a monitorizar"""
    try:
        metrics['commands_processed'] += 1
        user_id = update.effective_user.id

        # Obtener la lista de ciudades disponibles
        cities = db[MONGO_CONFIG['collections']['hourly_forecast']].distinct("city.name")

        if not cities:
            await update.message.reply_text("No hay ciudades disponibles todavía. Inténtalo más tarde.")
            return

        # Usar paginación para mostrar ciudades
        keyboard = []
        for city in cities:
            keyboard.append([InlineKeyboardButton(city, callback_data=f"select_{city}")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Selecciona una ciudad para añadir:", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error en comando add_city: {e}")
        metrics['errors'] += 1
        await update.message.reply_text("Ha ocurrido un error. Por favor, intenta nuevamente.")

async def my_cities(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando para mostrar y gestionar las ciudades monitorizadas"""
    try:
        metrics['commands_processed'] += 1
        user_id = update.effective_user.id

        # Cargar preferencias
        prefs = load_user_preferences(user_id)

        # Comprobar si el usuario tiene ciudades registradas
        if not prefs['cities']:
            await update.message.reply_text(
                "No tienes ciudades para monitorizar. Usa /addcity para añadir una."
            )
            return

        # Crear un teclado en línea con botones para cada ciudad (para eliminar)
        keyboard = []
        for city in prefs['cities']:
            keyboard.append([InlineKeyboardButton(f"❌ {city}", callback_data=f"remove_{city}")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Tus ciudades monitorizadas:\n\n" +
            "\n".join([f"• {city}" for city in prefs['cities']]) +
            "\n\nPuedes eliminar una ciudad pulsando el botón correspondiente:",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error en comando my_cities: {e}")
        metrics['errors'] += 1
        await update.message.reply_text("Ha ocurrido un error. Por favor, intenta nuevamente.")

async def configure_alerts(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando para configurar tipos de alertas"""
    try:
        metrics['commands_processed'] += 1
        user_id = update.effective_user.id

        # Cargar preferencias
        prefs = load_user_preferences(user_id)

        # Crear teclado para configurar alertas
        keyboard = []
        alerts = prefs['alerts']

        alert_names = {
            'temp_high': 'Temperatura alta',
            'temp_low': 'Temperatura baja',
            'wind': 'Viento fuerte',
            'humidity': 'Humedad extrema',
            'rain': 'Lluvia intensa'
        }

        # Añadir botones para cada tipo de alerta
        for alert_type, enabled in alerts.items():
            status = "✅" if enabled else "❌"
            keyboard.append([
                InlineKeyboardButton(
                    f"{status} {alert_names[alert_type]}",
                    callback_data=f"toggle_{alert_type}"
                )
            ])

        # Añadir botón para configurar umbrales
        keyboard.append([
            InlineKeyboardButton(
                "⚙️ Configurar Umbrales",
                callback_data="thresholds"
            )
        ])

        reply_markup = InlineKeyboardMarkup(keyboard)
        message_text = "Configura qué tipos de alertas quieres recibir:"

        # Verificar si la actualización viene de un mensaje o de un callback
        if update.message:
            await update.message.reply_text(message_text, reply_markup=reply_markup)
        elif update.callback_query:
            await update.callback_query.edit_message_text(message_text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error en comando configure_alerts: {e}")
        metrics['errors'] += 1
        if update.message:
            await update.message.reply_text("Ha ocurrido un error. Por favor, intenta nuevamente.")
        elif update.callback_query:
            await update.callback_query.edit_message_text("Ha ocurrido un error. Por favor, intenta nuevamente.")

async def set_interval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando para configurar el intervalo de alertas"""
    try:
        metrics['commands_processed'] += 1
        user_id = update.effective_user.id

        # Cargar preferencias
        prefs = load_user_preferences(user_id)

        # Opciones de intervalo en horas
        intervals = [1/60, 1, 3, 6, 12, 24]  # 1 minuto, 1h, 3h...

        # Convertir el intervalo actual de segundos a horas
        current_interval_hours = prefs.get('alert_interval', CHECK_INTERVAL) / 3600

        keyboard = []
        for interval in intervals:
            # Redondear para evitar errores de punto flotante
            is_selected = round(interval, 4) == round(current_interval_hours, 4)

            # Etiqueta del botón
            if round(interval, 4) == round(1/60, 4):
                label = "1 minuto"
            else:
                label = f"{int(interval)} {'hora' if interval == 1 else 'horas'}"

            status = "✅ " if is_selected else ""
            keyboard.append([
                InlineKeyboardButton(
                    f"{status}{label}",
                    callback_data=f"interval_{interval}"
                )
            ])

        reply_markup = InlineKeyboardMarkup(keyboard)

        # Texto de configuración actual
        if round(current_interval_hours, 4) == round(1/60, 4):
            current_interval_text = "1 minuto"
        else:
            current_interval_text = f"{int(current_interval_hours)} {'hora' if current_interval_hours == 1 else 'horas'}"

        await update.message.reply_text(
            f"Configuración actual: alertas cada {current_interval_text}\n"
            "Selecciona cada cuánto tiempo quieres recibir alertas:",
            reply_markup=reply_markup
        )

    except Exception as e:
        logger.error(f"Error en comando set_interval: {e}")
        metrics['errors'] += 1
        await update.message.reply_text("Ha ocurrido un error. Por favor, intenta nuevamente.")

async def get_weather(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando para obtener el clima actual de las ciudades monitorizadas"""
    try:
        metrics['commands_processed'] += 1
        user_id = update.effective_user.id

        # Cargar preferencias
        prefs = load_user_preferences(user_id)

        # Comprobar si el usuario tiene ciudades registradas
        if not prefs['cities']:
            await update.message.reply_text(
                "No tienes ciudades para monitorizar. Usa /addcity para añadir una."
            )
            return

        response = "🌤️ *Clima Actual*\n\n"
        now_timestamp = int(datetime.utcnow().timestamp())

        for city in prefs['cities']:
            # Obtener datos más recientes para la ciudad
            weather_data = db[MONGO_CONFIG['collections']['hourly_forecast']].find(
                {"city.name": city}
            ).sort("collected_at", -1).limit(1)
            weather = list(weather_data)

            if weather and 'list' in weather[0]:
                # Ordenar la lista por timestamp (dt)
                forecast_list = sorted(weather[0]['list'], key=lambda x: x['dt'])

                # Buscar la predicción más cercana al momento actual
                future_forecasts = [f for f in forecast_list if f['dt'] >= now_timestamp]
                forecast = future_forecasts[0] if future_forecasts else max(forecast_list, key=lambda x: x['dt'])

                if forecast:
                    temp = forecast['main']['temp']
                    feels_like = forecast['main']['feels_like']
                    description = forecast['weather'][0]['description'].lower()
                    description = weather_descriptions.get(description, description)
                    humidity = forecast['main']['humidity']
                    wind_speed = forecast['wind']['speed']
                    wind_deg = forecast['wind']['deg']
                    pressure = forecast['main']['pressure']
                    clouds = forecast.get('clouds', {}).get('all', 0)
                    visibility = forecast.get('visibility', 10000) / 1000  # Convert to km
                    forecast_time = datetime.fromtimestamp(forecast['dt']).strftime('%H:%M')

                    # Convert wind direction to cardinal points
                    wind_directions = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
                    wind_direction = wind_directions[round(wind_deg / 22.5) % 16]

                    response += f"*{city}*\n"
                    response += f"🌡️ {temp:.1f}°C (Sensación: {feels_like:.1f}°C)\n"
                    response += f"🌤️ {description}\n"
                    response += f"💧 Humedad: {humidity}%\n"
                    response += f"🌬️ Viento: {wind_speed} m/s ({wind_direction})\n"
                    response += f"⏲️ Presión: {pressure} hPa\n"
                    response += f"☁️ Nubes: {clouds}%\n"
                    response += f"👁️ Visibilidad: {visibility:.1f} km\n"
                    #response += f"🕒 Hora: {forecast_time}\n\n"
                else:
                    response += f"*{city}*: Datos no disponibles\n\n"
            else:
                response += f"*{city}*: Datos no disponibles\n\n"

        await update.message.reply_text(response, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error en comando get_weather: {e}")
        metrics['errors'] += 1
        await update.message.reply_text("Ha ocurrido un error. Por favor, intenta nuevamente.")

async def forecast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando para obtener el pronóstico de 5 días para una ciudad"""
    try:
        metrics['commands_processed'] += 1
        user_id = update.effective_user.id

        # Cargar preferencias
        prefs = load_user_preferences(user_id)

        # Comprobar si el usuario tiene ciudades registradas
        if not prefs['cities']:
            await update.message.reply_text(
                "No tienes ciudades para monitorizar. Usa /addcity para añadir una."
            )
            return

        # Crear un teclado en línea con botones para cada ciudad
        keyboard = []
        for city in prefs['cities']:
            keyboard.append([InlineKeyboardButton(city, callback_data=f"forecast_{city}")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Selecciona una ciudad para ver su pronóstico:",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error en comando forecast: {e}")
        metrics['errors'] += 1
        await update.message.reply_text("Ha ocurrido un error. Por favor, intenta nuevamente.")

@backoff.on_exception(
    backoff.expo,
    (TelegramError, NetworkError),
    max_tries=5,
    max_time=30
)
async def send_telegram_message(bot, chat_id, text, parse_mode=None):
    """Envía un mensaje a Telegram con reintentos en caso de error"""
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode
        )
        return True
    except Exception as e:
        logger.error(f"Error enviando mensaje a {chat_id}: {e}")
        metrics['errors'] += 1
        raise  # Relanzar para que backoff funcione

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestiona los callbacks de los botones inline"""
    query = update.callback_query
    await query.answer()

    try:
        # Obtener el tipo de callback y el valor
        callback_data = query.data
        logger.info(f"Received callback data: {callback_data}")

        if callback_data.startswith('forecast_'):
            city = callback_data[9:]  # Remove "forecast_" prefix
            if not city:
                await query.edit_message_text("Error: Ciudad no especificada")
                return

            logger.info(f"Procesando pronóstico para ciudad: {city}")

            # Obtener datos del pronóstico - obtener todos los documentos disponibles
            weather_data = db[MONGO_CONFIG['collections']['hourly_forecast']].find(
                {"city.name": city}
            ).sort("collected_at", -1)  # Removed limit(1)
            weather = list(weather_data)

            if weather:
                # Recolectar todos los pronósticos de todos los documentos
                all_forecasts = []
                for doc in weather:
                    if 'list' in doc:
                        all_forecasts.extend(doc['list'])

                logger.info(f"Total de documentos encontrados: {len(weather)}")
                logger.info(f"Total de pronósticos encontrados: {len(all_forecasts)}")

                # Ordenar la lista por timestamp (dt)
                forecast_list = sorted(all_forecasts, key=lambda x: x['dt'])
                now_timestamp = int(datetime.utcnow().timestamp())
                logger.info(f"Timestamp actual: {now_timestamp}")

                # Filtrar pronósticos futuros y agrupar por día
                daily_forecasts = {}
                for forecast in forecast_list:
                    forecast_date = datetime.fromtimestamp(forecast['dt'])
                    date_key = forecast_date.strftime('%Y-%m-%d')

                    # Solo incluir pronósticos futuros
                    if forecast['dt'] < now_timestamp:
                        logger.debug(f"Omitiendo pronóstico pasado: {forecast_date}")
                        continue

                    logger.debug(f"Procesando pronóstico para fecha: {date_key}")

                    if date_key not in daily_forecasts:
                        daily_forecasts[date_key] = {
                            'temps': [],
                            'descriptions': [],
                            'icons': [],
                            'wind_speeds': [],
                            'humidity': [],
                            'rain': [],
                            'date': forecast_date
                        }

                    daily_forecasts[date_key]['temps'].append(forecast['main']['temp'])
                    weather_desc = forecast['weather'][0]['description'].lower()
                    translated_desc = weather_descriptions.get(weather_desc, weather_desc)
                    daily_forecasts[date_key]['descriptions'].append(translated_desc)
                    daily_forecasts[date_key]['icons'].append(forecast['weather'][0]['icon'])
                    daily_forecasts[date_key]['wind_speeds'].append(forecast['wind']['speed'])
                    daily_forecasts[date_key]['humidity'].append(forecast['main']['humidity'])
                    if 'rain' in forecast and '1h' in forecast['rain']:
                        daily_forecasts[date_key]['rain'].append(forecast['rain']['1h'])

                logger.info(f"Días únicos en el pronóstico: {len(daily_forecasts)}")
                logger.info(f"Fechas disponibles: {sorted(daily_forecasts.keys())}")

                # Crear mensaje de pronóstico
                response = f"*Pronóstico para {city}*\n\n"

                # Diccionario para traducir días al español
                dias = {
                    'Monday': 'Lunes',
                    'Tuesday': 'Martes',
                    'Wednesday': 'Miércoles',
                    'Thursday': 'Jueves',
                    'Friday': 'Viernes',
                    'Saturday': 'Sábado',
                    'Sunday': 'Domingo'
                }

                # Ordenar los días por fecha
                sorted_dates = sorted(daily_forecasts.keys())
                logger.info(f"Días ordenados: {sorted_dates}")

                # Mostrar los próximos 5 días (OpenWeatherMap API proporciona 5 días)
                for date_key in sorted_dates[:5]:
                    data = daily_forecasts[date_key]
                    day_name = data['date'].strftime('%A')
                    day_name_es = dias.get(day_name, day_name)
                    min_temp = min(data['temps'])
                    max_temp = max(data['temps'])
                    avg_wind = sum(data['wind_speeds']) / len(data['wind_speeds'])
                    avg_humidity = sum(data['humidity']) / len(data['humidity'])

                    # Calcular probabilidad de lluvia
                    rain_count = sum(1 for r in data['rain'] if r > 0)
                    rain_prob = (rain_count / len(data['rain'])) * 100 if data['rain'] else 0

                    # Obtener la descripción más frecuente
                    main_desc = max(set(data['descriptions']), key=data['descriptions'].count)

                    logger.info(f"Procesando día {day_name_es} ({date_key}):")
                    logger.info(f"  Temperaturas: {min_temp:.1f}°C - {max_temp:.1f}°C")
                    logger.info(f"  Descripción: {main_desc}")
                    logger.info(f"  Humedad: {avg_humidity:.0f}%")
                    logger.info(f"  Viento: {avg_wind:.1f} m/s")
                    logger.info(f"  Prob. lluvia: {rain_prob:.0f}%")

                    response += f"*{day_name_es}*\n"
                    response += f"🌡️ {min_temp:.1f}°C - {max_temp:.1f}°C\n"
                    response += f"🌤️ {main_desc}\n"
                    response += f"💧 Humedad: {avg_humidity:.0f}%\n"
                    response += f"🌬️ Viento: {avg_wind:.1f} m/s\n"
                    response += f"🌧️ Prob. lluvia: {rain_prob:.0f}%\n\n"

                await query.edit_message_text(response, parse_mode='Markdown')
            else:
                logger.warning(f"No se encontraron datos para la ciudad: {city}")
                await query.edit_message_text(f"No hay datos disponibles para {city}")
        else:
            # Parse callback data
            parts = callback_data.split('_')
            callback_type = parts[0]

            # Special handling for adjust callbacks
            if callback_type == 'adjust' and len(parts) >= 3:
                threshold_type = parts[1]
                adjustment = int(parts[2])
                callback_value = f"{threshold_type}_{adjustment}"
            else:
                callback_value = '_'.join(parts[1:]) if len(parts) > 1 else None

            logger.info(f"Processing callback - Type: {callback_type}, Value: {callback_value}")

            # Get the chat_id of the user
            chat_id = update.effective_chat.id

            # Load user preferences
            user_prefs = load_user_preferences(chat_id)

            if callback_type == 'toggle':
                # Toggle alert type
                alert_type = callback_value
                if alert_type in user_prefs['alerts']:
                    user_prefs['alerts'][alert_type] = not user_prefs['alerts'][alert_type]
                    save_user_preferences(chat_id, user_prefs)
                    # Refresh the alerts configuration menu
                    await configure_alerts(update, context)
                else:
                    await query.edit_message_text("Error: Tipo de alerta no válido")
            elif callback_type == 'thresholds':
                # Handle thresholds configuration
                keyboard = []
                thresholds = user_prefs['thresholds']

                # Add buttons for each threshold with user-friendly labels
                threshold_labels = {
                    'temp_high': '🌡️ Temperatura máxima',
                    'temp_low': '❄️ Temperatura mínima',
                    'wind': '🌬️ Velocidad del viento',
                    'humidity': '💧 Humedad',
                    'rain': '🌧️ Lluvia'
                }

                # Add buttons for each threshold
                for threshold_type, value in thresholds.items():
                    label = threshold_labels.get(threshold_type, threshold_type)
                    unit = '°C' if 'temp' in threshold_type else 'm/s' if threshold_type == 'wind' else '%' if threshold_type == 'humidity' else 'mm'
                    keyboard.append([
                        InlineKeyboardButton(
                            f"{label}: {value}{unit}",
                            callback_data=f"threshold_{threshold_type}"
                        )
                    ])

                # Add back button
                keyboard.append([
                    InlineKeyboardButton("⬅️ Volver", callback_data="back_to_alerts")
                ])

                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    "⚙️ *Configuración de Umbrales*\n\n"
                    "Selecciona un umbral para modificarlo:\n\n"
                    "• Temperatura máxima: Alerta cuando la temperatura supere este valor\n"
                    "• Temperatura mínima: Alerta cuando la temperatura baje de este valor\n"
                    "• Velocidad del viento: Alerta cuando el viento supere esta velocidad\n"
                    "• Humedad: Alerta cuando la humedad supere este porcentaje\n"
                    "• Lluvia: Alerta cuando la lluvia supere este valor",
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            elif callback_type == 'threshold':
                # Handle threshold modification
                threshold_type = callback_value
                current_value = user_prefs['thresholds'][threshold_type]

                # Create keyboard with increment/decrement buttons
                keyboard = []
                row = []

                # Add decrement buttons
                for value in [-10, -5, -1]:
                    row.append(InlineKeyboardButton(
                        f"{value:+d}",
                        callback_data=f"dec_{threshold_type}_{abs(value)}"
                    ))
                keyboard.append(row)

                # Add current value display
                unit = '°C' if 'temp' in threshold_type else 'm/s' if threshold_type == 'wind' else '%' if threshold_type == 'humidity' else 'mm'
                keyboard.append([
                    InlineKeyboardButton(
                        f"Valor actual: {current_value}{unit}",
                        callback_data="noop"
                    )
                ])

                # Add increment buttons
                row = []
                for value in [1, 5, 10]:
                    row.append(InlineKeyboardButton(
                        f"+{value}",
                        callback_data=f"inc_{threshold_type}_{value}"
                    ))
                keyboard.append(row)

                # Add back button
                keyboard.append([
                    InlineKeyboardButton("⬅️ Volver", callback_data="thresholds")
                ])

                reply_markup = InlineKeyboardMarkup(keyboard)

                # Get threshold label
                threshold_labels = {
                    'temp_high': 'Temperatura máxima',
                    'temp_low': 'Temperatura mínima',
                    'wind': 'Velocidad del viento',
                    'humidity': 'Humedad',
                    'rain': 'Lluvia'
                }
                label = threshold_labels.get(threshold_type, threshold_type)

                await query.edit_message_text(
                    f"⚙️ *Ajustar {label}*\n\n"
                    f"Valor actual: {current_value}{unit}\n\n"
                    "Usa los botones para ajustar el valor:",
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            elif callback_type in ['inc', 'dec']:
                # Handle threshold value adjustment
                try:
                    # Split the callback value into threshold type and amount
                    parts = callback_value.split('_')
                    if len(parts) < 2:
                        logger.error(f"Invalid parts length: {len(parts)}, parts: {parts}")
                        raise ValueError("Invalid adjustment format")

                    # Last part is the amount, everything else is the threshold type
                    amount = int(parts[-1])
                    threshold_type = '_'.join(parts[:-1])

                    # Apply the adjustment (negative for decrement)
                    adjustment = -amount if callback_type == 'dec' else amount

                    logger.info(f"Adjusting {threshold_type} by {adjustment}")

                    # Get current value and apply adjustment
                    current_value = user_prefs['thresholds'][threshold_type]
                    new_value = current_value + adjustment

                    # Apply limits based on threshold type
                    if 'temp' in threshold_type:
                        new_value = max(-50, min(50, new_value))  # Temperature limits
                    elif threshold_type == 'wind':
                        new_value = max(0, min(100, new_value))   # Wind speed limits
                    elif threshold_type == 'humidity':
                        new_value = max(0, min(100, new_value))   # Humidity limits
                    elif threshold_type == 'rain':
                        new_value = max(0, min(200, new_value))   # Rain limits

                    # Update the threshold
                    user_prefs['thresholds'][threshold_type] = new_value
                    save_user_preferences(chat_id, user_prefs)

                    # Show updated value
                    unit = '°C' if 'temp' in threshold_type else 'm/s' if threshold_type == 'wind' else '%' if threshold_type == 'humidity' else 'mm'
                    threshold_labels = {
                        'temp_high': 'Temperatura máxima',
                        'temp_low': 'Temperatura mínima',
                        'wind': 'Velocidad del viento',
                        'humidity': 'Humedad',
                        'rain': 'Lluvia'
                    }
                    label = threshold_labels.get(threshold_type, threshold_type)

                    # Create keyboard with increment/decrement buttons
                    keyboard = []
                    row = []

                    # Add decrement buttons
                    for value in [-10, -5, -1]:
                        row.append(InlineKeyboardButton(
                            f"{value:+d}",
                            callback_data=f"dec_{threshold_type}_{abs(value)}"
                        ))
                    keyboard.append(row)

                    # Add current value display
                    keyboard.append([
                        InlineKeyboardButton(
                            f"Valor actual: {new_value}{unit}",
                            callback_data="noop"
                        )
                    ])

                    # Add increment buttons
                    row = []
                    for value in [1, 5, 10]:
                        row.append(InlineKeyboardButton(
                            f"+{value}",
                            callback_data=f"inc_{threshold_type}_{value}"
                        ))
                    keyboard.append(row)

                    # Add back button
                    keyboard.append([
                        InlineKeyboardButton("⬅️ Volver", callback_data="thresholds")
                    ])

                    reply_markup = InlineKeyboardMarkup(keyboard)

                    await query.edit_message_text(
                        f"⚙️ *Ajustar {label}*\n\n"
                        f"Valor actual: {new_value}{unit}\n\n"
                        "Usa los botones para ajustar el valor:",
                        reply_markup=reply_markup,
                        parse_mode='Markdown'
                    )
                except (ValueError, IndexError) as e:
                    logger.error(f"Error adjusting threshold: {e}")
                    logger.error(f"Callback value: {callback_value}")
                    await query.edit_message_text(
                        "Error al ajustar el umbral. Por favor, intenta nuevamente.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("⬅️ Volver", callback_data="thresholds")
                        ]])
                    )
            elif callback_type == 'back_to_alerts':
                # Return to alerts configuration
                await configure_alerts(update, context)
            elif callback_type == 'select':
                # Handle city selection
                city = callback_value
                if city:
                    if city not in user_prefs['cities']:
                        user_prefs['cities'].append(city)
                        save_user_preferences(chat_id, user_prefs)
                        await query.edit_message_text(f"Ciudad {city} añadida a tu lista de monitorización.")
                    else:
                        await query.edit_message_text(f"La ciudad {city} ya está en tu lista de monitorización.")
            elif callback_type == 'remove':
                # Handle city removal
                city = callback_value
                if city in user_prefs['cities']:
                    user_prefs['cities'].remove(city)
                    save_user_preferences(chat_id, user_prefs)
                    await query.edit_message_text(f"Ciudad {city} eliminada de tu lista de monitorización.")
            elif callback_type == 'interval':
                # Handle interval selection
                try:
                    interval = float(callback_value)
                    user_prefs['alert_interval'] = int(interval * 3600)  # Convert hours to seconds
                    save_user_preferences(chat_id, user_prefs)

                    # Show confirmation message
                    if round(interval, 4) == round(1/60, 4):
                        interval_text = "1 minuto"
                    else:
                        interval_text = f"{int(interval)} {'hora' if interval == 1 else 'horas'}"

                    await query.edit_message_text(
                        f"✅ Intervalo de alertas actualizado a {interval_text}."
                    )
                except (ValueError, TypeError) as e:
                    logger.error(f"Error setting interval: {e}")
                    await query.edit_message_text("Error al configurar el intervalo.")

    except Exception as e:
        logger.error(f"Error en callback de botón: {e}")
        metrics['errors'] += 1
        await query.edit_message_text("Ha ocurrido un error. Por favor, intenta nuevamente con /start.")

async def check_and_send_alerts(context: ContextTypes.DEFAULT_TYPE = None) -> None:
    """Comprueba condiciones y envía alertas a usuarios según su intervalo configurado"""
    logger.info("Comprobando condiciones para alertas...")

    try:
        # Obtener todos los usuarios con sus preferencias
        all_users = list(user_prefs_collection.find())
        alerts_count = 0
        now = datetime.utcnow()
        now_timestamp = int(now.timestamp())

        # Criterios para alertas
        pipeline = [
            # Obtener datos más recientes para cada ciudad
            {"$sort": {"collected_at": -1}},
            {"$group": {
                "_id": "$city.name",
                "latest": {"$first": "$$ROOT"}
            }},
            {"$replaceRoot": {"newRoot": "$latest"}},
        ]

        weather_data = list(db[MONGO_CONFIG['collections']['hourly_forecast']].aggregate(pipeline))

        # Procesar los datos del tiempo para obtener la predicción más reciente y cercana al momento actual
        processed_weather = {}
        for doc in weather_data:
            city_name = doc['city']['name']
            if 'list' not in doc:
                continue

            # Ordenar pronósticos por timestamp
            forecasts = sorted(doc['list'], key=lambda x: x['dt'])

            # Filtrar pronósticos futuros
            future_forecasts = [f for f in forecasts if f['dt'] >= now_timestamp]

            if future_forecasts:
                # Tomar el pronóstico más cercano
                processed_weather[city_name] = future_forecasts[0]

        # Procesar alertas para cada usuario
        for user in all_users:
            user_id = user['user_id']
            alerts = user.get('alerts', {})
            thresholds = user.get('thresholds', {
                'temp_high': 35,
                'temp_low': 0,
                'wind': 15,
                'humidity': 90,
                'rain': 80
            })
            cities = user.get('cities', [])
            last_alert = user.get('last_alert_sent', now - timedelta(hours=24))
            alert_interval = user.get('alert_interval', CHECK_INTERVAL)

            # Verificar si ha pasado suficiente tiempo desde la última alerta
            if (now - last_alert).total_seconds() < alert_interval:
                continue

            user_alerts = []

            # Comprobar condiciones para cada ciudad
            for city in cities:
                if city not in processed_weather:
                    continue

                data = processed_weather[city]
                data['city'] = city

                # Comprobar temperatura alta
                if alerts.get('temp_high', True) and data['main']['temp'] > thresholds['temp_high']:
                    user_alerts.append({
                        'city': data['city'],
                        'type': 'Temperatura alta',
                        'value': f"{data['main']['temp']:.1f}°C",
                        'threshold': thresholds['temp_high'],
                        'time': data['dt']
                    })

                # Comprobar temperatura baja
                if alerts.get('temp_low', True) and data['main']['temp'] < thresholds['temp_low']:
                    user_alerts.append({
                        'city': data['city'],
                        'type': 'Temperatura baja',
                        'value': f"{data['main']['temp']:.1f}°C",
                        'threshold': thresholds['temp_low'],
                        'time': data['dt']
                    })

                # Comprobar viento
                if alerts.get('wind', True) and data['wind']['speed'] > thresholds['wind']:
                    user_alerts.append({
                        'city': data['city'],
                        'type': 'Viento fuerte',
                        'value': f"{data['wind']['speed']} m/s",
                        'threshold': thresholds['wind'],
                        'time': data['dt']
                    })

                # Comprobar humedad
                if alerts.get('humidity', True) and data['main']['humidity'] > thresholds['humidity']:
                    user_alerts.append({
                        'city': data['city'],
                        'type': 'Humedad extrema',
                        'value': f"{data['main']['humidity']}%",
                        'threshold': thresholds['humidity'],
                        'time': data['dt']
                    })

                # Comprobar lluvia
                if alerts.get('rain', True) and data.get('rain', {}).get('1h', 0) > thresholds['rain']:
                    user_alerts.append({
                        'city': data['city'],
                        'type': 'Lluvia intensa',
                        'value': f"{data['rain']['1h']} mm",
                        'threshold': thresholds['rain'],
                        'time': data['dt']
                    })

            # Enviar alertas al usuario si hay alguna
            if user_alerts and context:
                # Agrupar alertas por ciudad
                alerts_by_city = {}
                for alert in user_alerts:
                    if alert['city'] not in alerts_by_city:
                        alerts_by_city[alert['city']] = []
                    alerts_by_city[alert['city']].append(alert)

                message = "⚠️ *ALERTAS METEOROLÓGICAS* ⚠️\n\n"

                for city, city_alerts in alerts_by_city.items():
                    message += f"*{city}*\n"
                    for alert in city_alerts:
                        forecast_time = datetime.fromtimestamp(alert['time']).strftime('%H:%M')
                        message += f"• {alert['type']}: {alert['value']} (umbral: {alert['threshold']})\n"
                    message += "\n"

                # Añadir información sobre el intervalo de alertas
                interval_hours = alert_interval / 3600
                if interval_hours < 1:
                    interval_text = f"{int(interval_hours * 60)} minutos"
                else:
                    interval_text = f"{int(interval_hours)} {'hora' if interval_hours == 1 else 'horas'}"
                message += f"\n_Próxima alerta en {interval_text}_"

                # Enviar mensaje
                if await send_telegram_message(context.bot, user_id, message, parse_mode='Markdown'):
                    # Actualizar última alerta enviada
                    user_prefs_collection.update_one(
                        {"user_id": user_id},
                        {"$set": {"last_alert_sent": now}}
                    )
                    alerts_count += 1

        logger.info(f"Enviadas {alerts_count} alertas")
        metrics['alerts_sent'] += alerts_count

    except Exception as e:
        logger.error(f"Error en check_and_send_alerts: {e}")
        metrics['errors'] += 1

async def periodic_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Trabajo periódico para comprobar alertas"""
    await check_and_send_alerts(context)

    # Guardar métricas cada 24 horas
    current_hour = datetime.utcnow().hour
    if current_hour == 0:  # Medianoche
        save_metrics_to_db()

def main():
    """Función principal para ejecutar el bot"""
    # Crear aplicación
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Registrar manejadores de comandos
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("addcity", add_city))
    application.add_handler(CommandHandler("mycities", my_cities))
    application.add_handler(CommandHandler("alerts", configure_alerts))
    application.add_handler(CommandHandler("weather", get_weather))
    application.add_handler(CommandHandler("forecast", forecast))
    application.add_handler(CommandHandler("setinterval", set_interval))

    # Registrar manejador de botones
    application.add_handler(CallbackQueryHandler(button_callback))

    # Configurar trabajo periódico para comprobar alertas
    job_queue = application.job_queue

    # Comprobar cada minuto si hay que enviar alertas a algún usuario
    # (se respetará el intervalo individual de cada usuario)
    job_queue.run_repeating(periodic_job, interval=60, first=10)

    # Notificar al administrador
    if TELEGRAM_ADMIN_ID:
        job_queue.run_once(
            lambda ctx: ctx.bot.send_message(
                chat_id=TELEGRAM_ADMIN_ID,
                text="🤖 Bot iniciado correctamente y listo para enviar alertas."
            ),
            when=10
        )

    # Iniciar el bot
    logger.info("Bot de Telegram iniciado con mejoras de intervalo personalizado")
    application.run_polling()

if __name__ == "__main__":
    main()
