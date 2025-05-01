# BDNR Climate Watcher

A comprehensive weather monitoring and analysis system that collects, processes, and visualizes weather data for specified locations. The system provides real-time weather monitoring, historical data analysis, and alert notifications through multiple channels.

## Features

- **Real-time Weather Data Collection**: Automatically collects weather data for configured locations
- **Data Storage**: MongoDB-based storage for weather data
- **REST API**: Access weather data through a RESTful API
- **Telegram Bot**: Receive weather alerts and notifications
- **Data Analysis**: Automated analysis of weather patterns and trends
- **Alert System**: Configurable thresholds for weather alerts
- **Docker Support**: Easy deployment using Docker containers

## System Architecture

The system consists of several microservices:

1. **Weather Collector**: Collects weather data from OpenWeatherMap API
2. **Weather API**: Provides REST endpoints for data access
3. **Telegram Bot**: Sends notifications and alerts
4. **Data Analyzer**: Processes and analyzes historical weather data
5. **MongoDB**: Database for storing weather data

## Project Structure

```
bdnr-climate-watcher/
├── .env                         # Environment variables (not in git)
├── .env.example                 # Example environment variables
├── config.py                    # Centralized system configuration
├── docker-compose.yml           # Docker services configuration
├── requirements.txt             # Main project dependencies
├── weather_collector/           # Data collection service
│   ├── collector_main.py        # Main collection logic
│   ├── requirements.txt         # Service-specific dependencies
│   └── Dockerfile              # Container configuration
├── weather_api/                 # API and web dashboard
│   ├── api_main.py             # API endpoints and logic
│   ├── requirements.txt        # Service-specific dependencies
│   ├── Dockerfile             # Container configuration
│   ├── static/                # Static files (JS, CSS)
│   │   └── js/               # JavaScript files
│   └── templates/             # HTML templates
├── telegram_bot/               # Telegram notification service
│   ├── telegram_main.py       # Bot logic and handlers
│   ├── requirements.txt       # Service-specific dependencies
│   └── Dockerfile            # Container configuration
├── data_analyzer/             # Data analysis service
│   ├── analyzer_main.py      # Analysis logic
│   ├── requirements.txt      # Service-specific dependencies
│   └── Dockerfile           # Container configuration
└── README.md                  # Project documentation
```

## Prerequisites

- Docker and Docker Compose
- OpenWeatherMap API key
- (Optional) Telegram Bot token
- (Optional) Email configuration for alerts

## Installation

1. Clone the repository:
```bash
git clone [https://github.com/albertuti1910/bdnr-climate-watcher]
cd bdnr-climate-watcher
```

2. Copy the environment file and configure it:
```bash
cp .env.example .env
```

3. Edit the `.env` file with your configuration:
- Set your OpenWeatherMap API key
- Configure MongoDB credentials
- Set up optional services (Telegram, email alerts)

4. Start the services:
```bash
docker-compose up -d --build
```

## Configuration

The system can be configured through:

1. **Environment Variables** (`.env` file):
   - API keys and credentials
   - Service ports and endpoints
   - Alert thresholds
   - Data collection intervals

2. **Config File** (`config.py`):
   - Cities to monitor
   - Weather thresholds
   - MongoDB configuration
   - API settings

## Services

### Weather Collector
- Collects weather data at configurable intervals
- Stores data in MongoDB
- Monitors weather conditions against thresholds

### Weather API
- RESTful API for accessing weather data
- Rate limiting and caching
- CORS support
- API key authentication

### Telegram Bot
- Sends weather alerts and notifications
- Configurable check intervals
- Admin user support

### Data Analyzer
- Processes historical weather data
- Generates analysis reports
- Creates weather trend visualizations

## API Documentation

The Weather API provides the following endpoints:

- `GET /api/weather/current`: Current weather data
- `GET /api/weather/history`: Historical weather data
- `GET /api/weather/forecast`: Weather forecasts
- `GET /api/alerts`: Active weather alerts

## Monitoring

The system includes monitoring capabilities:
- Prometheus metrics endpoint
- Logging configuration
- Rate limiting monitoring

## Contributing

### Core Contributors
- Mariana Bordes Bueno https://github.com/marianabordes
- Alberto Rivero Monzon https://github.com/albertuti1910

## License

MIT License

Copyright (c) 2024 BDNR Climate Watcher

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.