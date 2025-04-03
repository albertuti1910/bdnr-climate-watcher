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
                'last_activity': now               # Tracking de actividad
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
            'last_alert_sent': datetime.utcnow() - timedelta(hours=24)
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

        await update.message.reply_text(
            f"¡Hola {update.effective_user.first_name}! Soy el bot de alertas meteorológicas.\n\n"
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
        await update.message.reply_text("Ha ocurrido un error. Por favor, intenta nuevamente.")

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
        keyboard = paginate_keyboard(cities)
        await update.message.reply_text("Selecciona una ciudad para añadir:", reply_markup=keyboard)
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

        for alert_type, enabled in alerts.items():
            status = "✅" if enabled else "❌"
            keyboard.append([
                InlineKeyboardButton(
                    f"{status} {alert_names[alert_type]}",
                    callback_data=f"toggle_{alert_type}"
                )
            ])

        reply_markup = InlineKeyboardMarkup(keyboard)
        message_text = "Configura qué tipos de alertas quieres recibir:"

        # Verificar si la actualización viene de un mensaje o de un callback
        if update.message:
            # Si viene de un comando directo
            await update.message.reply_text(message_text, reply_markup=reply_markup)
        elif update.callback_query:
            # Si viene de un callback de botón
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

        response = "🌤️ Clima actual:\n\n"
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
                # Primero intentar encontrar la más cercana en el futuro
                future_forecasts = [f for f in forecast_list if f['dt'] >= now_timestamp]

                if future_forecasts:
                    # Si hay pronósticos futuros, tomar el más inmediato
                    forecast = future_forecasts[0]
                else:
                    # Si no hay pronósticos futuros, tomar el más reciente del pasado
                    forecast = max(forecast_list, key=lambda x: x['dt']) if forecast_list else None

                if forecast:
                    temp = forecast['main']['temp']
                    description = forecast['weather'][0]['description']
                    humidity = forecast['main']['humidity']
                    wind_speed = forecast['wind']['speed']
                    pressure = forecast['main']['pressure']
                    forecast_time = datetime.fromtimestamp(forecast['dt']).strftime('%H:%M')

                    response += f"*{city}*\n"
                    response += f"🌡️ {temp:.1f}°C - {description}\n"
                    response += f"💧 Humedad: {humidity}%\n"
                    response += f"🌬️ Viento: {wind_speed} m/s\n"
                    response += f"⏲️ Presión: {pressure} hPa\n"
                    response += f"🕒 Hora: {forecast_time}\n\n"
                else:
                    response += f"*{city}*: Datos no disponibles\n\n"
            else:
                response += f"*{city}*: Datos no disponibles\n\n"

        await update.message.reply_text(response, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error en comando get_weather: {e}")
        metrics['errors'] += 1
        await update.message.reply_text("Ha ocurrido un error obteniendo los datos del clima. Por favor, intenta nuevamente.")

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
    try:
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id
        data = query.data

        # No hacer nada para el callback de inactividad (noop)
        if data == "noop":
            return

        # Gestionar paginación
        if data.startswith("page_"):
            page = int(data.split("_")[1])
            # Recuperar la lista original para paginar
            cities = db[MONGO_CONFIG['collections']['hourly_forecast']].distinct("city.name")
            keyboard = paginate_keyboard(cities, page)
            await query.edit_message_text("Selecciona una ciudad para añadir:", reply_markup=keyboard)
            return

        # Acción para configurar intervalo de alertas
        if data.startswith("interval_"):
            try:
                # Usar float en lugar de int para soportar intervalos como 0.0167 (1 minuto)
                interval_hours = float(data.split("_")[1])
                seconds = int(interval_hours * 3600)

                # Cargar preferencias
                prefs = load_user_preferences(user_id)
                prefs['alert_interval'] = seconds
                save_user_preferences(user_id, prefs)

                label = "1 minuto" if round(interval_hours, 4) == round(1 / 60, 4) else f"{int(interval_hours)} {'hora' if interval_hours == 1 else 'horas'}"

                await query.edit_message_text(
                    f"✅ Intervalo de alertas configurado a {label}.\n"
                    f"Recibirás alertas cada {label} cuando haya condiciones meteorológicas extremas."
                )
            except ValueError:
                await query.edit_message_text("❌ Intervalo no válido.")

        # Acción para añadir ciudad
        if data.startswith("select_"):
            city = data[7:]

            # Cargar preferencias
            prefs = load_user_preferences(user_id)

            # Añadir la ciudad si no está ya en la lista
            if city not in prefs['cities']:
                prefs['cities'].append(city)
                # Guardar las preferencias actualizadas
                save_user_preferences(user_id, prefs)
                await query.edit_message_text(f"✅ {city} añadida a tu lista de monitorización.")
            else:
                await query.edit_message_text(f"⚠️ {city} ya está en tu lista de monitorización.")
            return

        # Acción para eliminar ciudad
        if data.startswith("remove_"):
            city = data[7:]

            # Cargar preferencias
            prefs = load_user_preferences(user_id)

            if city in prefs['cities']:
                prefs['cities'].remove(city)
                # Guardar las preferencias actualizadas
                save_user_preferences(user_id, prefs)
                await query.edit_message_text(f"❌ {city} eliminada de tu lista de monitorización.")
            else:
                await query.edit_message_text("⚠️ Error al eliminar la ciudad.")
            return

        # Acción para cambiar configuración de alertas
        if data.startswith("toggle_"):
            alert_type = data[7:]

            # Cargar preferencias
            prefs = load_user_preferences(user_id)

            if alert_type in prefs['alerts']:
                # Cambiar estado
                prefs['alerts'][alert_type] = not prefs['alerts'][alert_type]
                # Guardar las preferencias actualizadas
                save_user_preferences(user_id, prefs)

                # Actualizar mensaje con nueva configuración
                await configure_alerts(update, context)
            else:
                await query.edit_message_text("⚠️ Tipo de alerta desconocido.")
            return

        # Acción para mostrar pronóstico
        if data.startswith("forecast_"):
            city = data[9:]

            # Obtener pronóstico más reciente
            forecast_data = db[MONGO_CONFIG['collections']['hourly_forecast']].find(
                {"city.name": city}
            ).sort("collected_at", -1).limit(1)
            forecast = list(forecast_data)

            if not forecast:
                await query.edit_message_text(f"⚠️ Pronóstico no disponible para {city}.")
                return

            # Filtrar pronóstico para mostrar solo una predicción por día
            daily_forecast = {}

            for item in forecast[0]['list']:
                forecast_date = datetime.fromtimestamp(item['dt'])
                date_str = forecast_date.strftime('%Y-%m-%d')
                hour = forecast_date.hour

                # Priorizar pronósticos cercanos al mediodía
                if date_str not in daily_forecast or abs(hour - 12) < abs(daily_forecast[date_str]['hour'] - 12):
                    item['hour'] = hour
                    daily_forecast[date_str] = item

            # Ordenar por fecha
            sorted_forecast = sorted(daily_forecast.values(), key=lambda x: x['dt'])

            # Generar respuesta
            response = f"🔮 Pronóstico para *{city}*:\n\n"

            for item in sorted_forecast[:5]:  # Limitar a 5 días
                date = datetime.fromtimestamp(item['dt'])
                day = date.strftime('%A')  # Nombre del día

                # Traducir nombres de días al español
                days_es = {
                    'Monday': 'Lunes',
                    'Tuesday': 'Martes',
                    'Wednesday': 'Miércoles',
                    'Thursday': 'Jueves',
                    'Friday': 'Viernes',
                    'Saturday': 'Sábado',
                    'Sunday': 'Domingo'
                }
                day_es = days_es.get(day, day)

                temp = item['main']['temp']
                weather = item['weather'][0]['description']

                response += f"*{day_es}*: {temp:.1f}°C, {weather}\n"

            await query.edit_message_text(response, parse_mode='Markdown')
            return

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

        for city_data in weather_data:
            if 'list' in city_data and city_data['list']:
                city_name = city_data['city']['name']

                # Ordenar pronósticos y buscar el más cercano al momento actual
                forecast_list = sorted(city_data['list'], key=lambda x: x['dt'])

                # Buscar pronósticos futuros
                future_forecasts = [f for f in forecast_list if f['dt'] >= now_timestamp]

                if future_forecasts:
                    # Si hay pronósticos futuros, usar el más inmediato
                    latest_forecast = future_forecasts[0]
                elif forecast_list:
                    # Si no hay pronósticos futuros, usar el más reciente del pasado
                    latest_forecast = max(forecast_list, key=lambda x: x['dt'])
                else:
                    # No hay pronósticos disponibles
                    continue

                processed_weather[city_name] = {
                    'city': city_name,
                    'country': city_data['city'].get('country', ''),
                    'temp': latest_forecast['main']['temp'],
                    'wind_speed': latest_forecast['wind']['speed'],
                    'humidity': latest_forecast['main']['humidity'],
                    'rain': latest_forecast.get('rain', {}).get('3h', 0),
                    'weather_id': latest_forecast['weather'][0]['id'],
                    'weather_main': latest_forecast['weather'][0]['main'],
                    'weather_description': latest_forecast['weather'][0]['description'],
                    'forecast_time': latest_forecast['dt'],
                    'collected_at': city_data['collected_at']
                }

        # Para cada usuario, comprobar si es momento de enviar alertas
        for user in all_users:
            user_id = user['user_id']
            cities = user.get('cities', [])
            alerts = user.get('alerts', {})
            alert_interval = user.get('alert_interval', CHECK_INTERVAL)
            last_alert_sent = user.get('last_alert_sent', now - timedelta(days=1))

            # Verificar si es hora de enviar alertas según el intervalo del usuario
            time_since_last = (now - last_alert_sent).total_seconds()

            if time_since_last < alert_interval:
                logger.debug(f"Saltando usuario {user_id}, próxima alerta en {alert_interval - time_since_last} segundos")
                continue

            if not cities:
                continue

            user_alerts = []

            for city_name in cities:
                if city_name not in processed_weather:
                    continue

                data = processed_weather[city_name]

                # Comprobar cada tipo de alerta según preferencias
                if alerts.get('temp_high', True) and data['temp'] > THRESHOLDS['temp_high']:
                    user_alerts.append({
                        'city': data['city'],
                        'type': 'Temperatura alta',
                        'value': f"{data['temp']:.1f}°C",
                        'threshold': THRESHOLDS['temp_high'],
                        'time': data['forecast_time']
                    })

                if alerts.get('temp_low', True) and data['temp'] < THRESHOLDS['temp_low']:
                    user_alerts.append({
                        'city': data['city'],
                        'type': 'Temperatura baja',
                        'value': f"{data['temp']:.1f}°C",
                        'threshold': THRESHOLDS['temp_low'],
                        'time': data['forecast_time']
                    })

                if alerts.get('wind', True) and data['wind_speed'] > THRESHOLDS['wind']:
                    user_alerts.append({
                        'city': data['city'],
                        'type': 'Viento fuerte',
                        'value': f"{data['wind_speed']} m/s",
                        'threshold': THRESHOLDS['wind'],
                        'time': data['forecast_time']
                    })

                if alerts.get('humidity', True) and data['humidity'] > THRESHOLDS['humidity']:
                    user_alerts.append({
                        'city': data['city'],
                        'type': 'Humedad extrema',
                        'value': f"{data['humidity']}%",
                        'threshold': THRESHOLDS['humidity'],
                        'time': data['forecast_time']
                    })

                if alerts.get('rain', True) and data.get('rain', 0) > THRESHOLDS['rain_prob']:
                    user_alerts.append({
                        'city': data['city'],
                        'type': 'Lluvia intensa',
                        'value': f"{data['rain']} mm",
                        'threshold': THRESHOLDS['rain_prob'],
                        'time': data['forecast_time']
                    })

            # Enviar alertas al usuario si hay alguna
            if user_alerts and context:
                message = "⚠️ *ALERTAS METEOROLÓGICAS* ⚠️\n\n"

                for alert in user_alerts:
                    forecast_time = datetime.fromtimestamp(alert['time']).strftime('%H:%M')
                    message += f"*{alert['city']}*: {alert['type']} - {alert['value']} (hora: {forecast_time})\n"

                try:
                    await send_telegram_message(
                        bot=context.bot,
                        chat_id=user_id,
                        text=message,
                        parse_mode='Markdown'
                    )
                    alerts_count += 1
                    metrics['alerts_sent'] += 1

                    # Guardar alerta en el historial
                    alert_record = {
                        'timestamp': now,
                        'alerts': user_alerts,
                        'message': message
                    }

                    # Actualizar última vez que se enviaron alertas y guardar historial
                    user_prefs_collection.update_one(
                        {"user_id": user_id},
                        {
                            "$set": {"last_alert_sent": now},
                            "$push": {
                                "alert_history": {
                                    "$each": [alert_record],
                                    "$slice": -10  # Mantener solo las 10 alertas más recientes
                                }
                            }
                        }
                    )

                    logger.info(f"Alerta enviada a usuario {user_id}: {len(user_alerts)} condiciones")
                except Exception as e:
                    logger.error(f"Error enviando alerta a usuario {user_id}: {e}")
                    metrics['errors'] += 1

        logger.info(f"Comprobación de alertas completada. Alertas enviadas: {alerts_count}")

        # Guardar métricas periódicamente
        if context and alerts_count > 0:
            save_metrics_to_db()

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
