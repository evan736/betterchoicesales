# Insurance Agency Operating System

A full-stack internal operating system for insurance agencies with producer sales tracking, commission calculations, and carrier statement imports.

## Features

### Core Functionality
- **Producer Management**: User accounts with role-based access (admin, producer, manager)
- **Sales Tracking**: Log policy sales with client info, premium amounts, lead sources
- **PDF Upload**: Upload application PDFs for e-signature processing
- **Commission Calculation**: 
  - Tier-based on monthly written premium
  - Paid on recognized premium
  - Negative carry-forward for chargebacks
- **Statement Import**: Import carrier commission statements (CSV/XLSX/PDF)
- **Policy Matching**: Automatic matching by policy number
- **Async Processing**: Celery workers for background tasks

### Planned Integrations
- WeSignature API for e-signatures
- NowCerts AMS integration
- National General statement imports
- Progressive statement imports

## Tech Stack

- **Frontend**: Next.js 14, React, TypeScript, Tailwind CSS
- **Backend**: FastAPI (Python), SQLAlchemy
- **Worker**: Celery with Redis
- **Database**: PostgreSQL 15
- **Cache/Queue**: Redis 7
- **Dev Environment**: Docker Compose

## Quick Start

### Prerequisites
- Docker Desktop installed
- Docker Compose installed

### 1. Start All Services
```bash
docker-compose up -d
```

This will start:
- PostgreSQL database (port 5432)
- Redis cache (port 6379)
- FastAPI backend (port 8000)
- Celery worker
- Celery beat scheduler
- Next.js frontend (port 3000)

### 2. Initialize Database
```bash
# Wait for services to be healthy (~30 seconds)
docker-compose exec backend python init_db.py
```

This creates:
- All database tables
- Admin user (username: `admin`, password: `admin123`)
- Sample producer (username: `producer1`, password: `producer123`)
- Commission tier structure

### 3. Access the Application

- **Frontend**: http://localhost:3000
- **API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health

### Default Credentials

**Admin Account:**
- Username: `admin`
- Password: `admin123`

**Producer Account:**
- Username: `producer1`
- Password: `producer123`

## Commission Calculation Logic

### Tier Determination
- Based on **total written premium** for the month
- Three default tiers:
  - Tier 1: $0 - $50K → 10% commission
  - Tier 2: $50K - $100K → 12.5% commission
  - Tier 3: $100K+ → 15% commission

### Payment Calculation
- Commission **paid** based on **recognized premium**
- Recognized premium comes from carrier statements
- If no statement match, uses written premium

### Chargeback Handling
- Chargebacks create negative commission records
- If total commissions for period are negative:
  - Net commission = $0
  - Negative amount carries forward to next period

## API Endpoints

### Authentication
- `POST /api/auth/register` - Register new user
- `POST /api/auth/login` - Login and get JWT token
- `GET /api/auth/me` - Get current user info

### Sales
- `POST /api/sales/` - Create new sale
- `GET /api/sales/` - List sales (filtered by role)
- `GET /api/sales/{id}` - Get sale details
- `PATCH /api/sales/{id}` - Update sale
- `POST /api/sales/{id}/upload-application` - Upload PDF
- `DELETE /api/sales/{id}` - Delete sale (admin only)

### Commissions
- `GET /api/commissions/calculate/{producer_id}/{period}` - Calculate period commissions
- `GET /api/commissions/my-commissions` - Get current user's commissions
- `GET /api/commissions/tiers` - List commission tiers
- `POST /api/commissions/tiers` - Create tier (admin only)

### Statements
- `POST /api/statements/upload` - Upload statement file
- `POST /api/statements/{id}/process` - Process uploaded statement
- `GET /api/statements/` - List statement imports
- `GET /api/statements/{id}` - Get import details

## Development Commands

```bash
# View logs
docker-compose logs -f backend

# Restart services
docker-compose restart

# Stop services
docker-compose down

# Access database
docker-compose exec db psql -U insurance_user -d insurance_db

# Run migrations
docker-compose exec backend alembic upgrade head
```

## Troubleshooting

### psycopg/libpq Error (FIXED)
This project uses `psycopg[binary]` v3 which includes libpq. No manual installation needed.

### Database connection refused
Wait for healthcheck: `docker-compose ps` should show "healthy"

### Worker not processing tasks
Check: `docker-compose logs worker`

## License

Proprietary - Internal Use Only
