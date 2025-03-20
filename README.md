# Sistema de Análisis Climático con MongoDB y OpenWeatherMap API

Este proyecto permite recopilar, almacenar y analizar datos climáticos utilizando MongoDB y la API de OpenWeatherMap.

## Requisitos previos

- Docker y Docker Compose
- Cuenta en OpenWeatherMap y API Key (regístrate en [OpenWeatherMap](https://home.openweathermap.org/users/sign_up))

## Configuración

1. Clona este repositorio:
   ```bash
   git clone <url-del-repositorio>
   cd sistema-analisis-climatico
   ```

2. Configura tu API Key y datos de MongoDB:
   - Edita el archivo `.env` y añade tu API Key de OpenWeatherMap

## Ejecución con Docker

El proyecto está completamente dockerizado para facilitar su despliegue:

1. Inicia los contenedores:
   ```bash
   docker-compose up -d
   ```

   Esto iniciará:
   - Un contenedor con MongoDB
   - Un contenedor para la aplicación de recolección de datos

2. Verifica que los contenedores estén funcionando:
   ```bash
   docker-compose ps
   ```

## Consultar datos (desde el host)

Puedes consultar los datos almacenados utilizando el script `weather_query.py`:

1. Instala las dependencias:
   ```bash
   pip install -r requirements.txt
   pip install tabulate
   ```

2. Ejemplos de consultas:

   - Ver los datos más recientes:
     ```bash
     python weather_query.py latest
     ```

   - Ver datos de una ciudad específica:
     ```bash
     python weather_query.py latest --city "Madrid"
     ```

   - Ver datos en un rango de fechas:
     ```bash
     python weather_query.py range --start 2024-03-01 --end 2024-03-13
     ```

   - Ver temperaturas extremas de los últimos 7 días:
     ```bash
     python weather_query.py extreme
     ```

   - Ver temperaturas extremas de los últimos 30 días:
     ```bash
     python weather_query.py extreme --days 30
     ```

## Estructura del proyecto

- `docker-compose.yml`: Configuración de Docker Compose para los servicios
- `Dockerfile`: Instrucciones para construir la imagen del recolector de datos
- `weather_collector.py`: Script que obtiene y almacena datos climáticos
- `weather_query.py`: Script para consultar los datos almacenados
- `.env`: Archivo de configuración con variables de entorno

## Personalización

- Para añadir más ciudades, edita la lista `CITIES` en `weather_collector.py`
- Para cambiar la frecuencia de recolección, modifica el valor de `time.sleep()` en la función `main()` de `weather_collector.py`
