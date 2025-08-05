# Windrush Development Makefile

.PHONY: help build up down logs shell-backend shell-frontend test migrate createsuperuser collectstatic

# Default command
help:
	@echo "Available commands:"
	@echo "  build          - Build all Docker containers"
	@echo "  up             - Start all services in development mode"
	@echo "  up-prod        - Start all services in production mode"
	@echo "  down           - Stop all services"
	@echo "  logs           - Show logs for all services"
	@echo "  logs-backend   - Show backend logs"
	@echo "  logs-frontend  - Show frontend logs"
	@echo "  shell-backend  - Access backend container shell"
	@echo "  shell-frontend - Access frontend container shell"
	@echo "  shell-db       - Access database shell"
	@echo "  migrate        - Run Django migrations"
	@echo "  createsuperuser- Create Django superuser"
	@echo "  collectstatic  - Collect Django static files"
	@echo "  test           - Run backend tests"
	@echo "  test-frontend  - Run frontend tests"
	@echo "  clean          - Remove all containers and volumes"
	@echo "  reset-db       - Reset database (WARNING: destroys data)"

# Development commands
build:
	docker-compose -f docker-compose.dev.yml build

up:
	docker-compose -f docker-compose.dev.yml up -d
	@echo "Services starting..."
	@echo "Frontend: http://localhost:3000"
	@echo "Backend API: http://localhost:8000"
	@echo "Admin Panel: http://localhost:8000/admin"

up-prod:
	docker-compose up -d
	@echo "Production services started"

down:
	docker-compose -f docker-compose.dev.yml down

# Logging
logs:
	docker-compose -f docker-compose.dev.yml logs -f

logs-backend:
	docker-compose -f docker-compose.dev.yml logs -f backend

logs-frontend:
	docker-compose -f docker-compose.dev.yml logs -f frontend

# Shell access
shell-backend:
	docker-compose -f docker-compose.dev.yml exec backend bash

shell-frontend:
	docker-compose -f docker-compose.dev.yml exec frontend sh

shell-db:
	docker-compose -f docker-compose.dev.yml exec db psql -U windrush_user -d windrush_db

# Django management commands
migrate:
	docker-compose -f docker-compose.dev.yml exec backend python manage.py migrate

makemigrations:
	docker-compose -f docker-compose.dev.yml exec backend python manage.py makemigrations

createsuperuser:
	docker-compose -f docker-compose.dev.yml exec backend python manage.py createsuperuser

collectstatic:
	docker-compose -f docker-compose.dev.yml exec backend python manage.py collectstatic --noinput

# Testing
test:
	docker-compose -f docker-compose.dev.yml exec backend python manage.py test

test-frontend:
	docker-compose -f docker-compose.dev.yml exec frontend npm test

# Maintenance
clean:
	docker-compose -f docker-compose.dev.yml down --volumes --remove-orphans
	docker-compose down --volumes --remove-orphans
	docker system prune -f

reset-db:
	docker-compose -f docker-compose.dev.yml stop db
	docker-compose -f docker-compose.dev.yml rm -f db
	docker volume rm windrush_postgres_data_dev || true
	docker-compose -f docker-compose.dev.yml up -d db
	@echo "Database reset complete. Run 'make migrate' to apply migrations."

# Quality checks
lint-backend:
	docker-compose -f docker-compose.dev.yml exec backend black --check .
	docker-compose -f docker-compose.dev.yml exec backend isort --check-only .
	docker-compose -f docker-compose.dev.yml exec backend flake8 .

format-backend:
	docker-compose -f docker-compose.dev.yml exec backend black .
	docker-compose -f docker-compose.dev.yml exec backend isort .

# Backup and restore
backup-db:
	docker-compose -f docker-compose.dev.yml exec db pg_dump -U windrush_user windrush_db > backup_$(shell date +%Y%m%d_%H%M%S).sql

restore-db:
	@read -p "Enter backup file path: " backup_file; \
	docker-compose -f docker-compose.dev.yml exec -T db psql -U windrush_user -d windrush_db < $$backup_file