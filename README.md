# BDNR Climate Watcher

A comprehensive weather monitoring system that collects, stores, and analyzes weather data using MongoDB and OpenWeatherMap API. The system features real-time data collection, historical analysis, and a user-friendly dashboard.

## Key Features

- **Real-time Weather Monitoring**: Collects and displays current weather conditions for multiple cities
- **Historical Data Analysis**: Tracks and visualizes temperature trends over time
- **Data Verification System**: Implements a robust verification system that tracks both data collection and verification times
- **Interactive Dashboard**: Modern web interface for viewing current and historical weather data
- **Multi-city Support**: Monitor weather conditions across multiple cities simultaneously
- **Data Integrity**: Ensures data accuracy through verification timestamps and update checks

## Project Structure

```
bdnr-climate-watcher/
├── .env                         # Environment variables (not in git)
├── .env.example                 # Example environment variables
├── config.py                    # Centralized system configuration
├── docker-compose.yml           # Main service configuration
├── weather_collector/           # Data collection service
│   ├── collector_main.py        # Main collection logic
│   └── requirements.txt
├── weather_api/                 # API and web dashboard
│   ├── api_main.py             # API endpoints and logic
│   ├── static/                 # Static files (JS, CSS)
│   │   └── js/
│   │       └── main.js         # Frontend logic
│   └── templates/
│       └── index.html          # Dashboard template
└── README.md
```

## Core Components

### Weather Collector
- Periodically fetches weather data from OpenWeatherMap API
- Stores data in MongoDB with timestamps
- Implements data verification tracking

### Weather API
- RESTful API endpoints for weather data
- Web dashboard for data visualization
- Data verification and update management

### MongoDB Database
- Stores weather data with timestamps
- Tracks data collection and verification times
- Optimized for weather data queries

## Installation

### Prerequisites
- Docker and Docker Compose
- OpenWeatherMap API key
- Python 3.8 or higher
- MongoDB 4.4 or higher

### Setup

1. Clone the repository:
```bash
git clone https://github.com/your-username/bdnr-climate-watcher.git
cd bdnr-climate-watcher
```

2. Configure environment variables:
```bash
cp .env.example .env
```
Edit `.env` with your:
- OpenWeatherMap API key
- MongoDB credentials
- System configuration

3. Start the services:
```bash
docker-compose up -d
```

## API Endpoints

### Current Weather
```
GET /api/current/<city>
```
Returns current weather data including:
- Temperature, humidity, pressure
- Weather conditions
- Last verification timestamp

### Historical Data
```
GET /api/historical/<city>?days=7
```
Returns historical temperature data:
- Daily average, minimum, and maximum temperatures
- Data sorted chronologically
- Configurable time range (7, 14, or 30 days)

### System Statistics
```
GET /api/stats
```
Returns system-wide statistics:
- Total number of forecasts
- Number of monitored cities
- Last verification timestamp across all cities

## Data Verification System

The system implements a sophisticated data verification system:

1. **Data Collection Time**: When weather data is first collected from OpenWeatherMap
2. **Last Verification Time**: When the data was last checked/verified
3. **Update Frequency**: Data is verified if older than 1 hour

This ensures:
- Accurate tracking of data freshness
- Clear distinction between collection and verification times
- Automatic updates when data becomes stale

## Dashboard Features

The web dashboard provides:

1. **Current Weather Display**
   - Real-time weather conditions
   - Last verification time for the selected city
   - Temperature, humidity, and other metrics

2. **Temperature History**
   - Interactive chart showing temperature trends
   - Daily average, minimum, and maximum temperatures
   - Configurable time range selection

3. **System Statistics**
   - Overview of monitored cities
   - Last verification time across all data
   - Total number of forecasts

## Configuration

### Cities Configuration
Edit `config.py` to add or remove cities:
```python
CITIES = [
    {"id": 3117735, "name": "Madrid", "country": "ES"},
    {"id": 3128760, "name": "Barcelona", "country": "ES"},
    # Add more cities as needed
]
```

### Environment Variables
Key configuration options in `.env`:
```
OPENWEATHER_API_KEY=your_api_key
MONGODB_URI=mongodb://user:password@mongodb:27017
VERIFICATION_INTERVAL=3600  # Data verification interval in seconds
```

## Troubleshooting

### Common Issues

1. **Data Not Updating**
   - Check OpenWeatherMap API key
   - Verify MongoDB connection
   - Check collector service logs

2. **Verification Times Not Updating**
   - Ensure MongoDB is accessible
   - Check system time synchronization
   - Verify API endpoint responses

3. **Dashboard Not Loading**
   - Check browser console for errors
   - Verify API connectivity
   - Check network connectivity

### Logs and Monitoring

View service logs:
```bash
docker-compose logs weather_collector
docker-compose logs weather_api
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.
