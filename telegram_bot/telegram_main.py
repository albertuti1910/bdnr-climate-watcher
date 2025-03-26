import os
import time
import logging
import json
from datetime import datetime
import pymongo
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from dotenv import load_dotenv

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

# Diccionario para almacenar preferencias de usuarios
user_prefs = {}

# Umbral para alertas
THRESHOLDS = {
    'temp_high': 35.0,  # Temperatura alta (°C)
    'temp_low': 0.0,    # Temperatura baja (°C)
    'wind': 20.0,       # Viento fuerte (m/s)
    'humidity': 95.0,   # Humedad extrema (%)
    'rain': 10.0        # Lluvia intensa (mm en 3h)
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /start para iniciar el bot"""
    user_id = update.effective_user.id

    # Registrar usuario en preferencias si no existe
    if user_id not in user_prefs:
        user_prefs[user_id] = {
            'cities': [],
            'alerts': {
                'temp_high': True,
                'temp_low': True,
                'wind': True,
                'humidity': True,
                'rain': True
            }
        }

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
    cities = db.current_weather.distinct("name")

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

    # Comprobar si el usuario tiene ciudades registradas
    if user_id not in user_prefs or not user_prefs[user_id]['cities']:
        await update.message.reply_text(
            "No tienes ciudades para monitorizar. Usa /addcity para añadir una."
        )
        return

    # Crear un teclado en línea con botones para cada ciudad (para eliminar)
    keyboard = []
    for city in user_prefs[user_id]['cities']:
        keyboard.append([InlineKeyboardButton(f"❌ {city}", callback_data=f"remove_{city}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Tus ciudades monitorizadas:\n\n" +
        "\n".join([f"• {city}" for city in user_prefs[user_id]['cities']]) +
        "\n\nPuedes eliminar una ciudad pulsando el botón correspondiente:",
        reply_markup=reply_markup
    )

async def configure_alerts(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando para configurar tipos de alertas"""
    user_id = update.effective_user.id

    # Asegurarse de que el usuario tiene preferencias
    if user_id not in user_prefs:
        user_prefs[user_id] = {
            'cities': [],
            'alerts': {
                'temp_high': True,
                'temp_low': True,
                'wind': True,
                'humidity': True,
                'rain': True
            }
        }

    # Crear teclado para configurar alertas
    keyboard = []
    alerts = user_prefs[user_id]['alerts']

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

    # Comprobar si el usuario tiene ciudades registradas
    if user_id not in user_prefs or not user_prefs[user_id]['cities']:
        await update.message.reply_text(
            "No tienes ciudades para monitorizar. Usa /addcity para añadir una."
        )
        return

    response = "🌤️ Clima actual:\n\n"

    for city in user_prefs[user_id]['cities']:
        # Obtener datos más recientes para la ciudad
        weather_data = db.current_weather.find({"name": city}).sort("collected_at", -1).limit(1)
        weather = list(weather_data)

        if weather:
            w = weather[0]
            temp = w['main']['temp']
            description = w['weather'][0]['description']
            humidity = w['main']['humidity']
            wind_speed = w['wind']['speed']
            pressure = w['main']['pressure']

            response += f"*{city}*\n"
            response += f"🌡️ {temp:.1f}°C - {description}\n"
            response += f"💧 Humedad: {humidity}%\n"
            response += f"🌬️ Viento: {wind_speed} m/s\n"
            response += f"⏲️ Presión: {pressure} hPa\n\n"
        else:
            response += f"*{city}*: Datos no disponibles\n\n"

    await update.message.reply_text(response, parse_mode='Markdown')

async def forecast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando para obtener el pronóstico de 5 días para una ciudad"""
    user_id = update.effective_user.id

    # Comprobar si el usuario tiene ciudades registradas
    if user_id not in user_prefs or not user_prefs[user_id]['cities']:
        await update.message.reply_text(
            "No tienes ciudades para monitorizar. Usa /addcity para añadir una."
        )
        return

    # Crear un teclado en línea con botones para cada ciudad
    keyboard = []
    for city in user_prefs[user_id]['cities']:
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

        # Inicializar preferencias si no existen
        if user_id not in user_prefs:
            user_prefs[user_id] = {
                'cities': [],
                'alerts': {
                    'temp_high': True,
                    'temp_low': True,
                    'wind': True,
                    'humidity': True,
                    'rain': True
                }
            }

        # Añadir la ciudad si no está ya en la lista
        if city not in user_prefs[user_id]['cities']:
            user_prefs[user_id]['cities'].append(city)
            await query.edit_message_text(f"✅ {city} añadida a tu lista de monitorización.")
        else:
            await query.edit_message_text(f"⚠️ {city} ya está en tu lista de monitorización.")

    # Acción para eliminar ciudad
    elif data.startswith("remove_"):
        city = data[7:]

        if user_id in user_prefs and city in user_prefs[user_id]['cities']:
            user_prefs[user_id]['cities'].remove(city)
            await query.edit_message_text(f"❌ {city} eliminada de tu lista de monitorización.")
        else:
            await query.edit_message_text("⚠️ Error al eliminar la ciudad.")

    # Acción para cambiar configuración de alertas
    elif data.startswith("toggle_"):
        alert_type = data[7:]

        if user_id in user_prefs and alert_type in user_prefs[user_id]['alerts']:
            # Cambiar estado
            user_prefs[user_id]['alerts'][alert_type] = not user_prefs[user_id]['alerts'][alert_type]

            # Actualizar mensaje con nueva configuración
            await configure_alerts(update, context)

    # Acción para mostrar pronóstico
    elif data.startswith("forecast_"):
        city = data[9:]

        # Obtener pronóstico más reciente
        forecast_data = db.forecasts.find({"city.name": city}).sort("collected_at", -1).limit(1)
        forecast = list(forecast_data)

        if not forecast:
            await query.edit_message_text(f"⚠️ Pronóstico no disponible para {city}.")
            return

        # Filtrar pronóstico para mostrar solo una predicción por día
        daily_forecast = {}

        for item in forecast[0]['list']:
            date = item['dt_txt'].split(' ')[0]
            hour = int(item['dt_txt'].split(' ')[1].split(':')[0])

            # Priorizar pronósticos cercanos al mediodía
            if date not in daily_forecast or abs(hour - 12) < abs(int(daily_forecast[date]['dt_txt'].split(' ')[1].split(':')[0]) - 12):
                daily_forecast[date] = item

        # Ordenar por fecha
        sorted_forecast = sorted(daily_forecast.values(), key=lambda x: x['dt_txt'])

        # Generar respuesta
        response = f"🔮 Pronóstico para *{city}*:\n\n"

        for item in sorted_forecast[:5]:  # Limitar a 5 días
            date = datetime.strptime(item['dt_txt'].split(' ')[0], '%Y-%m-%d')
            day = date.strftime('%A')  # Nombre del día

            temp = item['main']['temp']
            weather = item['weather'][0]['description']

            response += f"*{day}*: {temp:.1f}°C, {weather}\n"

        await query.edit_message_text(response, parse_mode='Markdown')

async def check_and_send_alerts() -> None:
    """Comprueba condiciones y envía alertas a usuarios"""
    logger.info("Comprobando condiciones para alertas...")

    # Criterios para alertas
    pipeline = [
        # Obtener datos más recientes para cada ciudad
        {"$sort": {"collected_at": -1}},
        {"$group": {
            "_id": "$name",
            "latest": {"$first": "$$ROOT"}
        }},
        {"$replaceRoot": {"newRoot": "$latest"}},
        # Proyectar solo los campos necesarios
        {"$project": {
            "_id": 0,
            "city": "$name",
            "country": "$sys.country",
            "temp": "$main.temp",
            "wind_speed": "$wind.speed",
            "humidity": "$main.humidity",
            "rain": {
                "$cond": [
                    {"$ifNull": ["$rain.3h", False]},
                    "$rain.3h",
                    0
                ]
            },
            "collected_at": 1
        }}
    ]

    weather_data = list(db.current_weather.aggregate(pipeline))

    # Para cada usuario, comprobar sus ciudades
    for user_id, prefs in user_prefs.items():
        cities = prefs['cities']
        alerts = prefs['alerts']

        if not cities:
            continue

        user_alerts = []

        for data in weather_data:
            if data['city'] not in cities:
                continue

            # Comprobar cada tipo de alerta según preferencias
            if alerts.get('temp_high') and data['temp'] > THRESHOLDS['temp_high']:
                user_alerts.append({
                    'city': data['city'],
                    'type': 'Temperatura alta',
                    'value': f"{data['temp']:.1f}°C"
                })

            if alerts.get('temp_low') and data['temp'] < THRESHOLDS['temp_low']:
                user_alerts.append({
                    'city': data['city'],
                    'type': 'Temperatura baja',
                    'value': f"{data['temp']:.1f}°C"
                })

            if alerts.get('wind') and data['wind_speed'] > THRESHOLDS['wind']:
                user_alerts.append({
                    'city': data['city'],
                    'type': 'Viento fuerte',
                    'value': f"{data['wind_speed']} m/s"
                })

            if alerts.get('humidity') and data['humidity'] > THRESHOLDS['humidity']:
                user_alerts.append({
                    'city': data['city'],
                    'type': 'Humedad extrema',
                    'value': f"{data['humidity']}%"
                })

            if alerts.get('rain') and data.get('rain', 0) > THRESHOLDS['rain']:
                user_alerts.append({
                    'city': data['city'],
                    'type': 'Lluvia intensa',
                    'value': f"{data['rain']} mm"
                })

        # Enviar alertas al usuario si hay alguna
        if user_alerts:
            message = "⚠️ *ALERTAS METEOROLÓGICAS* ⚠️\n\n"

            for alert in user_alerts:
                message += f"*{alert['city']}*: {alert['type']} - {alert['value']}\n"

            # Aquí enviaríamos el mensaje al usuario
            # Esta parte depende de cómo manejes el envío de mensajes fuera de un comando
            # Para una implementación completa, necesitarías usar application.bot.send_message
            # await application.bot.send_message(chat_id=user_id, text=message, parse_mode='Markdown')

            logger.info(f"Alerta enviada a usuario {user_id}: {len(user_alerts)} condiciones")

async def periodic_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Trabajo periódico para comprobar alertas"""
    await check_and_send_alerts()

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
