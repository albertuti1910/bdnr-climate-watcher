# Sistema de Análisis Climático con MongoDB y OpenWeatherMap

Este proyecto implementa un sistema completo para recopilar, almacenar y analizar datos climáticos utilizando MongoDB y la API de OpenWeatherMap. Está diseñado con una arquitectura basada en contenedores Docker para facilitar su despliegue y escalabilidad.

## Características

- **Recolección de datos**: Consulta periódica a la API de OpenWeatherMap para obtener datos climáticos actuales y pronósticos.
- **Almacenamiento en MongoDB**: Los datos se almacenan de forma estructurada y optimizada para consultas.
- **Análisis de datos**: Procesamiento estadístico, detección de tendencias y generación de informes.
- **Interfaz de usuario**: Dashboard web para visualizar datos actuales, históricos y alertas.
- **Sistema de alertas**: Detección automática de condiciones climáticas extremas.
- **Configuración centralizada**: Archivo centralizado para gestionar ciudades y umbrales de alertas.

## Estructura del Proyecto

El proyecto está organizado en varios componentes Docker:

```
proyecto/
├── .env                         # Variables de entorno (no incluir en git)
├── .env.example                 # Ejemplo de variables de entorno
├── .gitignore                   # Archivos ignorados por git
├── config.py                    # Configuración centralizada del sistema
├── docker-compose.yml           # Configuración principal de los servicios
├── docker-compose-telegram.yml # Configuración de telegram
├── docker-compose-data-analyzer.yml  # Configuración del analisis
├── weather_collector/           # Servicio de recolección de datos
│   ├── Dockerfile
│   ├── app.py
│   └── requirements.txt
├── weather_api/                 # API REST y dashboard web
│   ├── Dockerfile
│   ├── app.py
│   ├── requirements.txt
│   └── templates/
│       └── index.html
├── data_analyzer/               # Análisis estadístico y reportes
│   ├── Dockerfile
│   ├── app.py
│   └── requirements.txt
├── telegram_bot/                # Bot de alertas por Telegram
│   ├── Dockerfile
│   ├── app.py
│   └── requirements.txt
└── README.md
```

## Requisitos

- Docker y Docker Compose
- Clave API de OpenWeatherMap

## Instalación y Uso

### 1. Clonar el repositorio

```bash
git clone https://github.com/tu-usuario/sistema-analisis-climatico.git
cd sistema-analisis-climatico
```

### 2. Configurar variables de entorno

```bash
cp .env.example .env
```

Edita el archivo `.env` con tu información:
- Añade tu clave API de OpenWeatherMap
- Configura credenciales para MongoDB
- Ajusta los umbrales para alertas si lo deseas

**⚠️ IMPORTANTE**: No incluyas comentarios en la misma línea que los valores en el archivo `.env`

```
# Correcto:
# Este es un comentario sobre la API
OPENWEATHER_API_KEY=tu_api_key

# Incorrecto:
OPENWEATHER_API_KEY=tu_api_key  # Este comentario causará problemas
```

### 3. Personalizar ciudades a monitorizar

Edita el archivo `config.py` para añadir o quitar ciudades:

```python
CITIES = [
    {"id": 3117735, "name": "Madrid", "country": "ES"},
    {"id": 3128760, "name": "Barcelona", "country": "ES"},
    # Añade más ciudades según necesites
]
```

Puedes encontrar los IDs de ciudades en OpenWeatherMap buscando la ciudad y extrayendo el ID de la URL.

### 4. Ejecutar el sistema

```bash
docker-compose up -d
```

Esto iniciará los siguientes servicios:
- MongoDB para almacenamiento de datos
- Weather Collector para obtener datos de la API
- Weather API para el dashboard web

### 5. Verificar que todo funciona correctamente

```bash
docker-compose ps
docker-compose logs
```

## Acceso y uso

- **Dashboard web**: Accede a http://localhost:5000 en tu navegador
- **MongoDB**: Disponible en localhost:27017 (requiere autenticación)

## Gestión de la Base de Datos

### Acceder a MongoDB desde la línea de comandos

```bash
docker-compose exec mongodb mongosh -u admin -p password_seguro
```

Una vez dentro de la consola de MongoDB:

```javascript
// Listar bases de datos
show dbs

// Usar la base de datos del clima
use weather_db

// Listar colecciones
show collections

// Consultar datos de clima
db.current_weather.find().sort({collected_at: -1}).limit(5)

// Consultar ciudades disponibles
db.current_weather.distinct("name")
```

## Opciones de Implementación

### 1. Dashboard Web

Una interfaz web interactiva que muestra:
- Clima actual para diferentes ciudades
- Gráficos históricos de temperatura y otras variables
- Pronóstico a 5 días
- Alertas meteorológicas activas

### 2. Bot de Telegram (Opcional)

Si deseas activar el bot de Telegram:

1. Obtén un token de bot a través de @BotFather en Telegram
2. Añade el token a tu archivo `.env`:
   ```
   ENABLE_TELEGRAM=true
   TELEGRAM_TOKEN=tu_token_de_telegram
   ```
3. Inicia el servicio:
   ```bash
   docker-compose -f docker-compose.yml -f docker-compose-telegram.yml up -d
   ```

### 3. Análisis de Datos y Reportes (Opcional)

Para activar el análisis de datos:

```bash
docker-compose -f docker-compose.yml -f docker-compose-data-analyzer.yml up -d
```

Este sistema genera:
- Estadísticas detalladas sobre tendencias climáticas
- Comparativas entre ciudades
- Informes mensuales con gráficos
- Detección de patrones y correlaciones entre variables meteorológicas

## Personalización de Umbrales de Alertas

Los umbrales para las alertas se pueden configurar en `config.py` o a través de variables de entorno `.env`:

```python
# En config.py
THRESHOLDS = {
    'temp_high': 35.0,  # Temperatura alta (°C)
    'temp_low': 0.0,    # Temperatura baja (°C)
    'wind': 20.0,       # Viento fuerte (m/s)
    'humidity': 95.0,   # Humedad extrema (%)
    'rain': 10.0        # Lluvia intensa (mm en 3h)
}
```

O en `.env`:
```
THRESHOLD_TEMP_HIGH=35.0
THRESHOLD_TEMP_LOW=0.0
THRESHOLD_WIND=20.0
THRESHOLD_HUMIDITY=95.0
THRESHOLD_RAIN=10.0
```

## Configuración Avanzada

### Frecuencia de recolección de datos

Modifica el valor de `COLLECTION_INTERVAL` en `.env` (en segundos):

```
COLLECTION_INTERVAL=3600
```

### Montar volúmenes externos

Para persistir datos fuera de Docker:

```yaml
# En docker-compose.yml
volumes:
  - ${DATA_DIR:-./data}:/app/data
```

## Solución de Problemas

### MongoDB no es accesible desde el navegador

MongoDB no proporciona una interfaz web en su puerto nativo (27017). Es normal ver un mensaje como "It looks like you are trying to access MongoDB over HTTP on the native driver port" si intentas acceder desde un navegador.

### Variables de entorno con comentarios

Los archivos `.env` no manejan comentarios en la misma línea que los valores. Asegúrate de poner los comentarios en líneas separadas.

### API no responde

Verifica los logs con `docker-compose logs weather_api` y asegúrate de que puede conectarse a MongoDB correctamente.

## Próximos Pasos y Extensiones

Algunas ideas para expandir el proyecto:

1. **Integración con otros servicios meteorológicos**: Añadir soporte para otras APIs como AccuWeather, Weather Underground, etc.
2. **Aprendizaje automático**: Implementar modelos predictivos para mejorar las previsiones.
3. **Notificaciones por correo electrónico o SMS**: Expandir el sistema de alertas.
4. **Aplicación móvil**: Desarrollar una app para consultar datos en dispositivos móviles.
5. **Visualización avanzada**: Implementar mapas interactivos con capas de información meteorológica.
6. **Integración con sistemas domóticos**: Conectar con dispositivos IoT para automatizar respuestas a cambios climáticos.

## Licencia

Este proyecto está bajo la licencia MIT.
