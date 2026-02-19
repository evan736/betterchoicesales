# Quick Start Guide

## Installation (One Command)

```bash
./setup.sh
```

That's it! The script will:
1. Check Docker is running
2. Build all containers
3. Start all services
4. Initialize the database
5. Create default users and commission tiers

## Access the Application

- **Frontend**: http://localhost:3000
- **API Documentation**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health

## Default Login

**Admin Account:**
```
Username: admin
Password: admin123
```

**Producer Account:**
```
Username: producer1
Password: producer123
```

## Key Features

### 1. Create a Sale
```bash
POST http://localhost:8000/api/sales/
Authorization: Bearer <your-token>

{
  "policy_number": "POL-12345",
  "written_premium": 1500.00,
  "lead_source": "referral",
  "item_count": 1,
  "client_name": "John Doe",
  "client_email": "john@example.com"
}
```

### 2. Upload Application PDF
```bash
POST http://localhost:8000/api/sales/{sale_id}/upload-application
Authorization: Bearer <your-token>
Content-Type: multipart/form-data

file: <your-pdf-file>
```

### 3. Import Commission Statement
```bash
# Upload
POST http://localhost:8000/api/statements/upload?carrier=national_general
Authorization: Bearer <your-token>
Content-Type: multipart/form-data

file: <your-csv-or-xlsx>

# Process
POST http://localhost:8000/api/statements/{import_id}/process
Authorization: Bearer <your-token>
```

### 4. Calculate Commissions
```bash
GET http://localhost:8000/api/commissions/calculate/{producer_id}/2024-01
Authorization: Bearer <your-token>
```

## Commission Tiers (Default)

| Tier | Written Premium Range | Commission Rate |
|------|----------------------|-----------------|
| 1    | $0 - $50,000        | 10%             |
| 2    | $50,001 - $100,000  | 12.5%           |
| 3    | $100,001+           | 15%             |

## Common Commands

```bash
# View all logs
docker-compose logs -f

# View specific service logs
docker-compose logs -f backend
docker-compose logs -f worker

# Restart services
docker-compose restart

# Stop all services
docker-compose down

# Stop and delete all data (WARNING!)
docker-compose down -v

# Access database
docker-compose exec db psql -U insurance_user -d insurance_db

# Run database migrations
docker-compose exec backend alembic upgrade head

# Create new migration
docker-compose exec backend alembic revision --autogenerate -m "description"
```

## API Authentication Flow

1. **Login to get token:**
```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin123"
```

Response:
```json
{
  "access_token": "eyJhbGc...",
  "token_type": "bearer"
}
```

2. **Use token in requests:**
```bash
curl -X GET http://localhost:8000/api/sales/ \
  -H "Authorization: Bearer eyJhbGc..."
```

## Troubleshooting

### Backend won't start
```bash
# Check logs
docker-compose logs backend

# Common issue: Database not ready
# Solution: Wait for DB health check
docker-compose ps
```

### Database connection error
```bash
# Verify DB is running
docker-compose ps db

# Check DB logs
docker-compose logs db
```

### Worker not processing
```bash
# Check worker status
docker-compose logs worker

# Restart worker
docker-compose restart worker
```

## File Structure

```
insurance-agency-os/
├── backend/              # FastAPI backend
│   ├── app/
│   │   ├── api/         # API routes
│   │   ├── models/      # Database models
│   │   ├── services/    # Business logic
│   │   └── main.py      # FastAPI app
│   ├── alembic/         # Database migrations
│   └── init_db.py       # Database initialization
├── frontend/            # Next.js frontend
├── docker-compose.yml   # Docker orchestration
└── README.md           # Full documentation
```

## Next Steps

1. ✅ System is running
2. 📝 Create your first sale via API
3. 📄 Upload an application PDF
4. 📊 Import a commission statement
5. 💰 Calculate commissions
6. 🚀 Customize for your agency

For full documentation, see README.md
