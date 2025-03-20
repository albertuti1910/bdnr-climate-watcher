import pymongo
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import argparse
from tabulate import tabulate

# Cargar variables de entorno
load_dotenv()

# Configuración de MongoDB
MONGO_URI = os.getenv("MONGO_URI", "mongodb://admin:password@localhost:27017")
DB_NAME = "weather_db"
COLLECTION_NAME = "weather_forecast"

def connect_to_mongodb():
    """Establece conexión con MongoDB"""
    try:
        client = pymongo.MongoClient(MONGO_URI)
        db = client[DB_NAME]
        collection = db[COLLECTION_NAME]
        return client, collection
    except Exception as e:
        print(f"Error al conectar con MongoDB: {e}")
        return None, None

def get_latest_forecasts(city=None, include_historical=False):
    """Obtiene los pronósticos más recientes para una ciudad o todas"""
    client, collection = connect_to_mongodb()

    if collection is None:
        return None

    query = {}
    if city:
        query["city_name"] = city

    if not include_historical:
        # Solo incluir pronósticos futuros
        query["forecast_time"] = {"$gte": datetime.now()}

    # Ordenar por ciudad y tiempo de pronóstico
    results = list(collection.find(query).sort([
        ("city_name", 1),
        ("forecast_time", 1)
    ]))

    client.close()
    return results

def get_historical_data(city=None, days=7):
    """Obtiene datos históricos para una ciudad o todas"""
    client, collection = connect_to_mongodb()

    if collection is None:
        return None

    start_date = datetime.now() - timedelta(days=days)

    query = {
        "is_historical": True,
        "forecast_time": {"$gte": start_date}
    }

    if city:
        query["city_name"] = city

    # Ordenar por ciudad y tiempo de pronóstico
    results = list(collection.find(query).sort([
        ("city_name", 1),
        ("forecast_time", 1)
    ]))

    client.close()
    return results

def get_specific_day_forecast(target_date, city=None):
    """Obtiene pronósticos para un día específico"""
    client, collection = connect_to_mongodb()

    if collection is None:
        return None

    # Configurar rango de fecha (inicio y fin del día)
    start_of_day = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0)
    end_of_day = start_of_day + timedelta(days=1)

    query = {
        "forecast_time": {
            "$gte": start_of_day,
            "$lt": end_of_day
        }
    }

    if city:
        query["city_name"] = city

    # Ordenar por ciudad y tiempo de pronóstico
    results = list(collection.find(query).sort([
        ("city_name", 1),
        ("forecast_time", 1)
    ]))

    client.close()
    return results

def get_extreme_temperatures(period_days=7, future=True):
    """Obtiene temperaturas máximas y mínimas para el período especificado"""
    client, collection = connect_to_mongodb()

    if collection is None:
        return None

    # Configurar rango de fechas
    now = datetime.now()
    if future:
        start_date = now
        end_date = now + timedelta(days=period_days)
    else:
        start_date = now - timedelta(days=period_days)
        end_date = now

    # Pipeline de agregación para obtener máximos y mínimos
    pipeline = [
        {
            "$match": {
                "forecast_time": {
                    "$gte": start_date,
                    "$lte": end_date
                }
            }
        },
        {
            "$group": {
                "_id": "$city_name",
                "max_temp": {"$max": "$temperature"},
                "min_temp": {"$min": "$temperature"},
                "avg_temp": {"$avg": "$temperature"},
                "city": {"$first": "$city_name"},
                "country": {"$first": "$country"}
            }
        },
        {
            "$sort": {"city": 1}
        }
    ]

    results = list(collection.aggregate(pipeline))

    client.close()
    return results

def display_forecast_data(data, format_type="table"):
    """Muestra los datos de pronóstico en un formato legible"""
    if not data:
        print("No se encontraron datos.")
        return

    if format_type == "table":
        # Preparar datos para mostrar en tabla
        table_data = []
        headers = ["Ciudad", "País", "Fecha pronóstico", "Temperatura (°C)", "Sensación (°C)", "Humedad (%)", "Presión (hPa)", "Viento (m/s)", "Clima", "¿Histórico?"]

        for item in data:
            table_data.append([
                item.get("city_name", "N/A"),
                item.get("country", "N/A"),
                item.get("forecast_time").strftime("%Y-%m-%d %H:%M") if item.get("forecast_time") else "N/A",
                round(item.get("temperature", 0), 1),
                round(item.get("feels_like", 0), 1),
                item.get("humidity", 0),
                item.get("pressure", 0),
                item.get("wind_speed", 0),
                item.get("weather_description", "N/A"),
                "Sí" if item.get("is_historical", False) else "No"
            ])

        print(tabulate(table_data, headers=headers, tablefmt="grid"))
    else:
        # Mostrar datos en formato raw
        for item in data:
            print(item)
            print("-" * 50)

def display_extreme_temps(data):
    """Muestra los datos de temperaturas extremas"""
    if not data:
        print("No se encontraron datos.")
        return

    table_data = []
    headers = ["Ciudad", "País", "Temp. Máx (°C)", "Temp. Mín (°C)", "Temp. Media (°C)"]

    for item in data:
        table_data.append([
            item.get("city", "N/A"),
            item.get("country", "N/A"),
            round(item.get("max_temp", 0), 1),
            round(item.get("min_temp", 0), 1),
            round(item.get("avg_temp", 0), 1)
        ])

    print(tabulate(table_data, headers=headers, tablefmt="grid"))

def main():
    parser = argparse.ArgumentParser(description="Consulta de datos climáticos en MongoDB")

    subparsers = parser.add_subparsers(dest="command", help="Tipo de consulta")

    # Subcomando para pronósticos futuros
    forecast_parser = subparsers.add_parser("forecast", help="Obtener pronósticos futuros")
    forecast_parser.add_argument("--city", help="Nombre de la ciudad (opcional)")

    # Subcomando para datos históricos
    history_parser = subparsers.add_parser("history", help="Obtener datos históricos")
    history_parser.add_argument("--city", help="Nombre de la ciudad (opcional)")
    history_parser.add_argument("--days", type=int, default=7, help="Número de días hacia atrás (por defecto: 7)")

    # Subcomando para datos de un día específico
    day_parser = subparsers.add_parser("day", help="Obtener pronósticos para un día específico")
    day_parser.add_argument("--date", required=True, help="Fecha (YYYY-MM-DD)")
    day_parser.add_argument("--city", help="Nombre de la ciudad (opcional)")

    # Subcomando para temperaturas extremas
    extreme_parser = subparsers.add_parser("extreme", help="Obtener temperaturas extremas")
    extreme_parser.add_argument("--days", type=int, default=5, help="Número de días a analizar (por defecto: 5)")
    extreme_parser.add_argument("--historical", action="store_true", help="Usar datos históricos en lugar de pronósticos")

    args = parser.parse_args()

    if args.command == "forecast":
        results = get_latest_forecasts(args.city)
        display_forecast_data(results)

    elif args.command == "history":
        results = get_historical_data(args.city, args.days)
        display_forecast_data(results)

    elif args.command == "day":
        try:
            target_date = datetime.strptime(args.date, "%Y-%m-%d")
            results = get_specific_day_forecast(target_date, args.city)
            display_forecast_data(results)
        except ValueError:
            print("Formato de fecha incorrecto. Use YYYY-MM-DD.")

    elif args.command == "extreme":
        results = get_extreme_temperatures(args.days, not args.historical)
        display_extreme_temps(results)

    else:
        parser.print_help()

if __name__ == "__main__":
    main()
