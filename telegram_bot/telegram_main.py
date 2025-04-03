import os
import logging
from datetime import datetime
import pymongo
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from dotenv import load_dotenv

from config import THRESHOLDS, MONGO_CONFIG

load_dotenv()

# Configuración desde variables de entorno
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
MONGO_URI = os.getenv('MONGO_URI')
CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', 3600))

# Configuración del logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Conexión a MongoDB
client = pymongo.MongoClient(MONGO_URI)
db = client.weather_db

# Colección para almacenar preferencias de usuarios
user_prefs_collection = db['user_preferences']

# Crear índice para búsqueda eficiente por user_id
user_prefs_collection.create_index([("user_id", pymongo.ASCENDING)], unique=True)

def load_user_preferences(user_id):
    """Carga las preferencias del usuario desde la base de datos"""
    pref = user_prefs_collection.find_one({"user_id": user_id})
    if not pref:
        # Si no existen, crear preferencias por defecto
        pref = {
            'user_id': user_id,
            'cities': [],
            'alerts': {
                'temp_high': True,
                'temp_low': True,
                'wind': True,
                'humidity': True,
                'rain': True
            }
        }
        # Guardar las preferencias por defecto en la base de datos
        user_prefs_collection.insert_one(pref)

    return pref

def save_user_preferences(user_id, preferences):
    """Guarda las preferencias del usuario en la base de datos"""
    # Asegurarse de que user_id está en las preferencias
    preferences['user_id'] = user_id

    user_prefs_collection.update_one(
        {"user_id": user_id},
        {"$set": preferences},
        upsert=True
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /start para iniciar el bot"""
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
        "Usa /weather para obtener el clima actual de tus ciudades."
    )

async def add_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando para añadir una ciudad a monitorizar"""
    user_id = update.effective_user.id

    # Obtener la lista de ciudades disponibles
    cities = db[MONGO_CONFIG['collections']['hourly_forecast']].distinct("city.name")

    # Crear un teclado en línea con botones para cada ciudad
    keyboard = []
    row = []
    for i, city in enumerate(cities):
        # Añadir 3 ciudades por fila
        row.append(InlineKeyboardButton(city, callback_data=f"add_{city}"))
        if (i + 1) % 3 == 0 or i == len(cities) - 1:
            keyboard.append(row)
            row = []

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Selecciona una ciudad para añadir:", reply_markup=reply_markup)

async def my_cities(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando para mostrar y gestionar las ciudades monitorizadas"""
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

async def configure_alerts(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando para configurar tipos de alertas"""
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

async def get_weather(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando para obtener el clima actual de las ciudades monitorizadas"""
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

    for city in prefs['cities']:
        # Obtener datos más recientes para la ciudad
        weather_data = db[MONGO_CONFIG['collections']['hourly_forecast']].find(
            {"city.name": city}
        ).sort("collected_at", -1).limit(1)
        weather = list(weather_data)

        if weather and 'list' in weather[0]:
            # Get the most recent forecast (first item in the list)
            forecast = weather[0]['list'][0] if weather[0]['list'] else None

            if forecast:
                temp = forecast['main']['temp']
                description = forecast['weather'][0]['description']
                humidity = forecast['main']['humidity']
                wind_speed = forecast['wind']['speed']
                pressure = forecast['main']['pressure']

                response += f"*{city}*\n"
                response += f"🌡️ {temp:.1f}°C - {description}\n"
                response += f"💧 Humedad: {humidity}%\n"
                response += f"🌬️ Viento: {wind_speed} m/s\n"
                response += f"⏲️ Presión: {pressure} hPa\n\n"
            else:
                response += f"*{city}*: Datos no disponibles\n\n"
        else:
            response += f"*{city}*: Datos no disponibles\n\n"

    await update.message.reply_text(response, parse_mode='Markdown')

async def forecast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando para obtener el pronóstico de 5 días para una ciudad"""
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

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestiona los callbacks de los botones inline"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data

    # Acción para añadir ciudad
    if data.startswith("add_"):
        city = data[4:]

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

    # Acción para eliminar ciudad
    elif data.startswith("remove_"):
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

    # Acción para cambiar configuración de alertas
    elif data.startswith("toggle_"):
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

    # Acción para mostrar pronóstico
    elif data.startswith("forecast_"):
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

async def check_and_send_alerts(context: ContextTypes.DEFAULT_TYPE = None) -> None:
    """Comprueba condiciones y envía alertas a usuarios"""
    logger.info("Comprobando condiciones para alertas...")

    # Obtener todos los usuarios con sus preferencias
    all_users = list(user_prefs_collection.find())

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

    # Procesar los datos del tiempo para obtener la predicción más reciente
    processed_weather = {}

    for city_data in weather_data:
        if 'list' in city_data and city_data['list']:
            city_name = city_data['city']['name']
            latest_forecast = city_data['list'][0]  # Usar el pronóstico más reciente

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
                'collected_at': city_data['collected_at']
            }

    # Para cada usuario, comprobar sus ciudades
    for user in all_users:
        user_id = user['user_id']
        cities = user.get('cities', [])
        alerts = user.get('alerts', {})

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
                    'value': f"{data['temp']:.1f}°C"
                })

            if alerts.get('temp_low', True) and data['temp'] < THRESHOLDS['temp_low']:
                user_alerts.append({
                    'city': data['city'],
                    'type': 'Temperatura baja',
                    'value': f"{data['temp']:.1f}°C"
                })

            if alerts.get('wind', True) and data['wind_speed'] > THRESHOLDS['wind']:
                user_alerts.append({
                    'city': data['city'],
                    'type': 'Viento fuerte',
                    'value': f"{data['wind_speed']} m/s"
                })

            if alerts.get('humidity', True) and data['humidity'] > THRESHOLDS['humidity']:
                user_alerts.append({
                    'city': data['city'],
                    'type': 'Humedad extrema',
                    'value': f"{data['humidity']}%"
                })

            if alerts.get('rain', True) and data.get('rain', 0) > THRESHOLDS['rain']:
                user_alerts.append({
                    'city': data['city'],
                    'type': 'Lluvia intensa',
                    'value': f"{data['rain']} mm"
                })

        # Enviar alertas al usuario si hay alguna
        if user_alerts and context:
            message = "⚠️ *ALERTAS METEOROLÓGICAS* ⚠️\n\n"

            for alert in user_alerts:
                message += f"*{alert['city']}*: {alert['type']} - {alert['value']}\n"

            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=message,
                    parse_mode='Markdown'
                )
                logger.info(f"Alerta enviada a usuario {user_id}: {len(user_alerts)} condiciones")
            except Exception as e:
                logger.error(f"Error enviando alerta a usuario {user_id}: {e}")

async def periodic_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Trabajo periódico para comprobar alertas"""
    await check_and_send_alerts(context)

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

    # Registrar manejador de botones
    application.add_handler(CallbackQueryHandler(button_callback))

    # Configurar trabajo periódico para comprobar alertas
    job_queue = application.job_queue
    job_queue.run_repeating(periodic_job, interval=CHECK_INTERVAL, first=10)

    # Iniciar el bot
    logger.info("Bot iniciado")
    application.run_polling()

if __name__ == "__main__":
    main()
