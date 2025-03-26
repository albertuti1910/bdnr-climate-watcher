import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from pymongo import MongoClient
from datetime import datetime, timedelta
import json
import logging
from scipy import stats
from dotenv import load_dotenv

load_dotenv()

# Configuración desde variables de entorno
MONGO_URI = os.getenv('MONGO_URI')
OUTPUT_DIR = os.getenv('OUTPUT_DIR', '/app/data')
ANALYSIS_INTERVAL = int(os.getenv('ANALYSIS_INTERVAL', 86400)) # 1 día en segundos

# Configuración del logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Asegurar que el directorio de salida existe
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Conexión a MongoDB
client = MongoClient(MONGO_URI)
db = client.weather_db

def get_data_for_city(city, days=180):
    """Obtiene datos históricos para una ciudad"""
    # Calcular fecha límite
    date_limit = datetime.utcnow() - timedelta(days=days)

    # Consulta para obtener datos de clima actual
    pipeline = [
        {"$match": {"name": city, "collected_at": {"$gte": date_limit}}},
        {"$project": {
            "_id": 0,
            "date": "$collected_at",
            "temp": "$main.temp",
            "feels_like": "$main.feels_like",
            "temp_min": "$main.temp_min",
            "temp_max": "$main.temp_max",
            "pressure": "$main.pressure",
            "humidity": "$main.humidity",
            "wind_speed": "$wind.speed",
            "wind_deg": "$wind.deg",
            "clouds": "$clouds.all",
            "weather": "$weather.main",
            "weather_desc": "$weather.description"
        }},
        {"$sort": {"date": 1}}
    ]

    results = list(db.current_weather.aggregate(pipeline))

    if not results:
        logger.warning(f"No hay datos disponibles para {city} en los últimos {days} días")
        return None

    # Convertir a DataFrame
    df = pd.DataFrame(results)

    # La columna weather es una lista, tomar el primer elemento
    if 'weather' in df.columns and len(df) > 0:
        df['weather'] = df['weather'].apply(lambda x: x[0] if isinstance(x, list) and len(x) > 0 else None)

    if 'weather_desc' in df.columns and len(df) > 0:
        df['weather_desc'] = df['weather_desc'].apply(lambda x: x[0] if isinstance(x, list) and len(x) > 0 else None)

    # Convertir fecha a datetime si no lo es ya
    if 'date' in df.columns:
        if not pd.api.types.is_datetime64_any_dtype(df['date']):
            df['date'] = pd.to_datetime(df['date'])

    return df

def analyze_temperature_trends(df, city):
    """Analiza tendencias de temperatura"""
    if df is None or len(df) < 10:  # Mínimo de datos para análisis significativo
        logger.warning(f"Datos insuficientes para analizar tendencias de temperatura en {city}")
        return None

    # Resample a datos diarios (media diaria)
    df_daily = df.set_index('date')
    daily_temp = df_daily['temp'].resample('D').mean()

    # Calcular estadísticas básicas
    stats_temp = {
        'ciudad': city,
        'temperatura_media': df['temp'].mean(),
        'temperatura_max': df['temp'].max(),
        'temperatura_min': df['temp'].min(),
        'desviacion_estandar': df['temp'].std()
    }

    # Tendencia (regresión lineal simple)
    if len(daily_temp) > 1:
        x = np.array(range(len(daily_temp)))
        y = daily_temp.values

        # Eliminar valores NaN
        mask = ~np.isnan(y)
        x = x[mask]
        y = y[mask]

        if len(x) > 1:
            slope, intercept, r_value, p_value, std_err = stats.linregress(x, y)
            stats_temp['tendencia'] = slope
            stats_temp['p_valor'] = p_value
            stats_temp['r_cuadrado'] = r_value**2

            # Interpretación de tendencia
            if p_value < 0.05:
                if slope > 0:
                    stats_temp['interpretacion'] = f"Tendencia significativa al calentamiento: {slope:.4f}°C/día"
                else:
                    stats_temp['interpretacion'] = f"Tendencia significativa al enfriamiento: {slope:.4f}°C/día"
            else:
                stats_temp['interpretacion'] = "No hay tendencia significativa en la temperatura"

    # Guardar en un archivo JSON
    with open(f"{OUTPUT_DIR}/{city}_temperatura_stats.json", 'w') as f:
        json.dump(stats_temp, f, indent=4)

    # Crear gráfico de serie temporal
    plt.figure(figsize=(12, 6))
    plt.plot(daily_temp.index, daily_temp.values, marker='o', markersize=3, linestyle='-')
    plt.title(f'Temperatura Media Diaria - {city}')
    plt.xlabel('Fecha')
    plt.ylabel('Temperatura (°C)')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(f"{OUTPUT_DIR}/{city}_temperatura_tendencia.png")
    plt.close()

    # Crear histograma de temperaturas
    plt.figure(figsize=(10, 6))
    sns.histplot(df['temp'], kde=True)
    plt.title(f'Distribución de Temperaturas - {city}')
    plt.xlabel('Temperatura (°C)')
    plt.ylabel('Frecuencia')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(f"{OUTPUT_DIR}/{city}_temperatura_distribucion.png")
    plt.close()

    return stats_temp

def analyze_weather_patterns(df, city):
    """Analiza patrones de condiciones climáticas"""
    if df is None or len(df) < 10:
        logger.warning(f"Datos insuficientes para analizar patrones climáticos en {city}")
        return None

    # Contar frecuencia de cada tipo de clima
    if 'weather' in df.columns:
        weather_counts = df['weather'].value_counts().to_dict()

        # Guardar en un archivo JSON
        with open(f"{OUTPUT_DIR}/{city}_weather_patterns.json", 'w') as f:
            json.dump(weather_counts, f, indent=4)

        # Crear gráfico de tarta
        plt.figure(figsize=(10, 8))
        plt.pie(weather_counts.values(), labels=weather_counts.keys(), autopct='%1.1f%%',
                shadow=True, startangle=90)
        plt.axis('equal')
        plt.title(f'Distribución de Condiciones Climáticas - {city}')
        plt.tight_layout()
        plt.savefig(f"{OUTPUT_DIR}/{city}_weather_distribution.png")
        plt.close()

        return weather_counts

    return None

def analyze_correlations(df, city):
    """Analiza correlaciones entre variables meteorológicas"""
    if df is None or len(df) < 10:
        logger.warning(f"Datos insuficientes para analizar correlaciones en {city}")
        return None

    # Seleccionar columnas numéricas para correlación
    numeric_columns = ['temp', 'feels_like', 'pressure', 'humidity', 'wind_speed', 'clouds']
    df_numeric = df[numeric_columns].dropna()

    if len(df_numeric) < 10:
        logger.warning(f"Datos numéricos insuficientes para analizar correlaciones en {city}")
        return None

    # Calcular matriz de correlación
    corr_matrix = df_numeric.corr()

    # Guardar en un archivo CSV
    corr_matrix.to_csv(f"{OUTPUT_DIR}/{city}_correlations.csv")

    # Crear mapa de calor
    plt.figure(figsize=(10, 8))
    sns.heatmap(corr_matrix, annot=True, cmap='coolwarm', vmin=-1, vmax=1, center=0)
    plt.title(f'Correlaciones entre Variables Meteorológicas - {city}')
    plt.tight_layout()
    plt.savefig(f"{OUTPUT_DIR}/{city}_correlations.png")
    plt.close()

    return corr_matrix.to_dict()

def generate_monthly_report(city):
    """Genera un informe mensual de condiciones meteorológicas"""
    # Obtener datos del último mes
    df = get_data_for_city(city, days=30)

    if df is None or len(df) < 10:
        logger.warning(f"Datos insuficientes para generar informe mensual para {city}")
        return None

    # Calcular estadísticas mensuales
    monthly_stats = {
        'ciudad': city,
        'periodo': f"{df['date'].min().strftime('%Y-%m-%d')} a {df['date'].max().strftime('%Y-%m-%d')}",
        'temperatura': {
            'media': df['temp'].mean(),
            'max': df['temp'].max(),
            'min': df['temp'].min(),
            'std': df['temp'].std()
        },
        'humedad': {
            'media': df['humidity'].mean(),
            'max': df['humidity'].max(),
            'min': df['humidity'].min()
        },
        'viento': {
            'velocidad_media': df['wind_speed'].mean(),
            'max': df['wind_speed'].max()
        }
    }

    # Calcular días con cada condición climática
    if 'weather' in df.columns:
        weather_counts = df['weather'].value_counts().to_dict()
        monthly_stats['condiciones'] = weather_counts

    # Guardar en un archivo JSON
    report_path = f"{OUTPUT_DIR}/{city}_monthly_report.json"
    with open(report_path, 'w') as f:
        json.dump(monthly_stats, f, indent=4)

    logger.info(f"Informe mensual generado para {city}: {report_path}")

    return monthly_stats

def compare_cities(cities, days=30):
    """Compara condiciones climáticas entre varias ciudades"""
    if not cities or len(cities) < 2:
        logger.warning("Se necesitan al menos dos ciudades para la comparación")
        return None

    comparison_data = {}

    for city in cities:
        df = get_data_for_city(city, days=days)

        if df is None or len(df) < 10:
            logger.warning(f"Datos insuficientes para {city}, omitiendo de la comparación")
            continue

        # Calcular promedios diarios
        df_daily = df.set_index('date')
        daily_avg = {
            'temp': df_daily['temp'].resample('D').mean(),
            'humidity': df_daily['humidity'].resample('D').mean(),
            'wind_speed': df_daily['wind_speed'].resample('D').mean()
        }

        comparison_data[city] = {
            'temp_avg': daily_avg['temp'].mean(),
            'humidity_avg': daily_avg['humidity'].mean(),
            'wind_avg': daily_avg['wind_speed'].mean(),
            'daily_temp': daily_avg['temp'].to_dict()
        }

    if len(comparison_data) < 2:
        logger.warning("Datos insuficientes para al menos dos ciudades")
        return None

    # Guardar comparación en JSON
    with open(f"{OUTPUT_DIR}/cities_comparison.json", 'w') as f:
        json.dump(comparison_data, f, indent=4)

    # Crear gráfico de comparación de temperaturas
    plt.figure(figsize=(12, 6))

    for city, data in comparison_data.items():
        if 'daily_temp' in data:
            dates = list(data['daily_temp'].keys())
            temps = list(data['daily_temp'].values())
            plt.plot(dates, temps, marker='o', markersize=3, label=city)

    plt.title(f'Comparación de Temperaturas Diarias (Últimos {days} días)')
    plt.xlabel('Fecha')
    plt.ylabel('Temperatura (°C)')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(f"{OUTPUT_DIR}/cities_temp_comparison.png")
    plt.close()

    # Crear gráfico de barras para comparar promedios
    plt.figure(figsize=(10, 6))

    cities_list = list(comparison_data.keys())
    temp_avgs = [data['temp_avg'] for data in comparison_data.values()]
    humidity_avgs = [data['humidity_avg'] for data in comparison_data.values()]

    x = np.arange(len(cities_list))
    width = 0.35

    plt.bar(x - width/2, temp_avgs, width, label='Temperatura Media (°C)')
    plt.bar(x + width/2, humidity_avgs, width, label='Humedad Media (%)')

    plt.title(f'Comparación de Condiciones Climáticas entre Ciudades')
    plt.xlabel('Ciudad')
    plt.ylabel('Valor')
    plt.xticks(x, cities_list)
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(f"{OUTPUT_DIR}/cities_avg_comparison.png")
    plt.close()

    return comparison_data

def main():
    """Función principal que ejecuta todos los análisis"""
    logger.info("Iniciando análisis de datos climáticos")

    # Obtener lista de ciudades disponibles
    cities = db.current_weather.distinct("name")
    logger.info(f"Ciudades disponibles: {len(cities)}")

    for city in cities:
        logger.info(f"Analizando datos para {city}")

        # Obtener datos históricos
        df = get_data_for_city(city)

        if df is not None and len(df) > 0:
            # Análisis de temperatura
            analyze_temperature_trends(df, city)

            # Análisis de patrones climáticos
            analyze_weather_patterns(df, city)

            # Análisis de correlaciones
            analyze_correlations(df, city)

            # Generar informe mensual
            generate_monthly_report(city)

            logger.info(f"Análisis completado para {city}")
        else:
            logger.warning(f"No hay datos suficientes para analizar {city}")

    # Comparar las 5 ciudades con más datos
    cities_with_most_data = []
    for city in cities:
        count = db.current_weather.count_documents({"name": city})
        cities_with_most_data.append((city, count))

    # Ordenar por cantidad de datos (descendente)
    cities_with_most_data.sort(key=lambda x: x[1], reverse=True)

    # Tomar las 5 primeras ciudades
    top_cities = [city for city, _ in cities_with_most_data[:5]]

    if len(top_cities) >= 2:
        logger.info(f"Comparando ciudades: {top_cities}")
        compare_cities(top_cities)

    logger.info("Análisis de datos completado")

if __name__ == "__main__":
    main()
