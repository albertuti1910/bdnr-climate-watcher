# Sistema de Análisis Climático con MongoDB y OpenWeatherMap

Este proyecto implementa un sistema completo para recopilar, almacenar y analizar datos climáticos utilizando MongoDB y la API de OpenWeatherMap. Está diseñado con una arquitectura basada en contenedores Docker para facilitar su despliegue y escalabilidad.

## Características

- **Recolección de datos**: Consulta periódica a la API de OpenWeatherMap para obtener datos climáticos actuales y pronósticos.
- **Almacenamiento en MongoDB**: Los datos se almacenan de forma estructurada y optimizada para consultas.
- **Análisis de datos**: Procesamiento estadístico, detección de tendencias y generación de informes.
- **Interfaz de usuario**: Dashboard web para visualizar datos actuales, históricos y alertas.
- **Sistema de alertas**: Detección automática de condiciones climáticas extremas.
- **Configuración centralizada**: Archivo centralizado para gestionar ciudades y umbrales de alertas.
- **Seguridad mejorada**: Rate limiting, validación de entrada, y caché implementados.
- **API RESTful**: Endpoints documentados con paginación y filtrado.

## Estructura del Proyecto

El proyecto está organizado en varios componentes Docker:

```
proyecto/
├── .env                         # Variables de entorno (no incluir en git)
├── .env.example                 # Ejemplo de variables de entorno
├── .gitignore                   # Archivos ignorados por git
├── config.py                    # Configuración centralizada del sistema
├── docker-compose.yml           # Configuración principal de los servicios
├── docker-compose-telegram.yml  # Configuración de telegram
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
- Python 3.8 o superior
- MongoDB 4.4 o superior

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
- Configura las opciones de seguridad y caché

### 3. Personalizar ciudades a monitorizar

Edita el archivo `config.py` para añadir o quitar ciudades:

```python
CITIES = [
    {"id": 3117735, "name": "Madrid", "country": "ES"},
    {"id": 3128760, "name": "Barcelona", "country": "ES"},
    # Añade más ciudades según necesites
]
```

### 4. Ejecutar el sistema

```bash
docker-compose up -d
```

Esto iniciará los siguientes servicios:
- MongoDB para almacenamiento de datos
- Weather Collector para obtener datos de la API
- Weather API para el dashboard web
- Redis para caché y rate limiting (opcional)

### 5. Verificar que todo funciona correctamente

```bash
docker-compose ps
docker-compose logs
```

## API Endpoints

### Clima Actual
```
GET /api/current/<city>
```
Obtiene el clima actual para una ciudad específica.

### Datos Históricos
```
GET /api/historical/<city>?days=7&page=1&per_page=100
```
Obtiene datos históricos con paginación.

### Lista de Ciudades
```
GET /api/cities
```
Obtiene la lista de ciudades disponibles.

### Métricas
```
GET /api/metrics/collector
GET /api/metrics/summary
```
Obtiene métricas del sistema.

## Seguridad

El sistema implementa las siguientes medidas de seguridad:

- **Rate Limiting**: Limita el número de peticiones por IP
- **Validación de Entrada**: Valida todos los parámetros de entrada
- **Caché**: Reduce la carga en la base de datos
- **Autenticación**: Protección de endpoints con API key
- **CORS**: Configuración de orígenes permitidos

## Monitoreo

El sistema incluye métricas y monitoreo:

- Prometheus para métricas
- Grafana para visualización
- Logs estructurados
- Health checks

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

## Configuración Avanzada

### Caché

El sistema utiliza Redis para caché y rate limiting. Para activar:

1. Añade Redis a tu docker-compose.yml
2. Configura las variables de entorno:
   ```
   CACHE_TYPE=redis
   CACHE_REDIS_URL=redis://redis:6379/0
   RATE_LIMIT_STORAGE_URL=redis://redis:6379/1
   ```

### Monitoreo

Para activar el monitoreo con Prometheus y Grafana:

1. Añade los servicios a docker-compose.yml
2. Configura las variables de entorno:
   ```
   ENABLE_METRICS=true
   METRICS_PORT=9090
   ```

## Solución de Problemas

### MongoDB no es accesible

Verifica la conexión y credenciales:
```bash
docker-compose exec mongodb mongosh -u admin -p password_seguro
```

### API no responde

Verifica los logs:
```bash
docker-compose logs weather_api
```

### Rate Limiting

Si recibes errores 429, ajusta los límites en `.env`:
```
API_RATE_LIMIT=200/minute
```

## Contribución

1. Fork el repositorio
2. Crea una rama para tu feature (`git checkout -b feature/AmazingFeature`)
3. Commit tus cambios (`git commit -m 'Add some AmazingFeature'`)
4. Push a la rama (`git push origin feature/AmazingFeature`)
5. Abre un Pull Request

## Licencia

Este proyecto está licenciado bajo la Licencia MIT - ver el archivo [LICENSE](LICENSE) para más detalles.
