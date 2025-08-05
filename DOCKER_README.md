# Windrush Docker Setup

This document explains how to run Windrush using Docker for both development and production environments.

## Quick Start

### Prerequisites
- Docker and Docker Compose installed
- Make (optional, for convenience commands)

### Development Environment

1. **Clone and Setup**
   ```bash
   git clone <repository-url>
   cd Windrush
   cp .env.example .env
   # Edit .env with your settings
   ```

2. **Build and Start Services**
   ```bash
   # Using Make (recommended)
   make build
   make up

   # Or using docker-compose directly
   docker-compose -f docker-compose.dev.yml build
   docker-compose -f docker-compose.dev.yml up -d
   ```

3. **Initialize Database**
   ```bash
   make migrate
   make createsuperuser
   ```

4. **Access the Application**
   - Frontend: http://localhost:3000
   - Backend API: http://localhost:8000
   - Admin Panel: http://localhost:8000/admin

## Services

### Core Services
- **db**: PostgreSQL 17 database
- **redis**: Redis 8 for caching and sessions
- **backend**: Django API server
- **frontend**: Next.js web application

### Development vs Production
- **Development**: Hot reload, debug mode, mounted volumes
- **Production**: Optimized builds, health checks, security settings

## Common Commands

### Make Commands (Recommended)
```bash
make help              # Show all available commands
make build             # Build all containers
make up                # Start development environment
make down              # Stop all services
make logs              # View all logs
make shell-backend     # Access backend container
make migrate           # Run database migrations
make test              # Run backend tests
```

### Docker Compose Commands
```bash
# Development
docker-compose -f docker-compose.dev.yml up -d
docker-compose -f docker-compose.dev.yml logs -f
docker-compose -f docker-compose.dev.yml down

# Production
docker-compose up -d
docker-compose logs -f
docker-compose down
```

## Database Management

### Migrations
```bash
make migrate                    # Apply migrations
make makemigrations            # Create new migrations
make shell-db                  # Access database shell
```

### Backup and Restore
```bash
make backup-db                 # Create database backup
make restore-db                # Restore from backup
make reset-db                  # Reset database (WARNING: destroys data)
```

## Development Workflow

### Backend Development
1. Make changes to Django code in `src/backend/`
2. Changes auto-reload in development mode
3. Run tests: `make test`
4. Access Django shell: `make shell-backend`

### Frontend Development
1. Make changes to Next.js code in `src/frontend/`
2. Changes auto-reload in development mode
3. Run tests: `make test-frontend`
4. Access container: `make shell-frontend`

## Environment Configuration

### Development (.env)
```bash
DEBUG=True
SECRET_KEY=dev-secret-key
DB_HOST=db
REDIS_URL=redis://redis:6379/0
FRONTEND_URL=http://localhost:3000
```

### Production
- Use secure secret keys
- Set `DEBUG=False`
- Configure proper ALLOWED_HOSTS
- Set up SSL certificates
- Use production database credentials

## File Structure
```
Windrush/
├── src/
│   ├── backend/              # Django API
│   │   ├── Dockerfile        # Production backend image
│   │   ├── Dockerfile.dev    # Development backend image
│   │   └── requirements.txt
│   └── frontend/             # Next.js app
│       ├── Dockerfile        # Production frontend image
│       └── Dockerfile.dev    # Development frontend image
├── docker-compose.yml        # Production compose file
├── docker-compose.dev.yml    # Development compose file
├── Makefile                  # Convenience commands
└── .env.example             # Environment variables template
```

## Troubleshooting

### Common Issues

1. **Port Already in Use**
   ```bash
   # Check what's using the port
   lsof -i :3000  # or :8000, :5432
   # Kill the process or change ports in docker-compose
   ```

2. **Database Connection Issues**
   ```bash
   # Check if database is ready
   make logs-backend
   # Reset database
   make reset-db
   make migrate
   ```

3. **Permission Issues**
   ```bash
   # Fix file permissions
   sudo chown -R $USER:$USER ./src
   ```

4. **Build Issues**
   ```bash
   # Clean rebuild
   make clean
   make build
   ```

### Logs and Debugging
```bash
make logs                    # All service logs
make logs-backend           # Backend logs only
make logs-frontend          # Frontend logs only
docker-compose -f docker-compose.dev.yml ps  # Service status
```

## Production Deployment

### Using Production Compose
```bash
docker-compose up -d
docker-compose exec backend python manage.py migrate
docker-compose exec backend python manage.py collectstatic --noinput
docker-compose exec backend python manage.py createsuperuser
```

### Environment Setup
1. Set secure environment variables
2. Configure SSL certificates
3. Set up proper database backups
4. Configure monitoring and logging
5. Set up CI/CD pipeline

## Health Checks

All services include health checks:
- **Database**: PostgreSQL connection test
- **Redis**: Redis ping command
- **Backend**: API health endpoint
- **Frontend**: HTTP response check

View health status:
```bash
docker-compose ps
```

## Volumes and Data Persistence

### Development Volumes
- Source code mounted for hot reload
- Database data persisted in `postgres_data_dev`
- Redis data persisted in `redis_data_dev`

### Production Volumes
- Static files and media persisted
- Database and Redis data persisted
- No source code mounting

## Security Considerations

### Development
- Default passwords (change in production)
- Debug mode enabled
- Permissive CORS settings

### Production
- Secure secret keys
- HTTPS enforcement
- Restricted CORS origins
- Security headers enabled
- Non-root container users