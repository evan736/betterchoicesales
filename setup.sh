#!/bin/bash

echo "========================================"
echo "Insurance Agency OS - Setup Script"
echo "========================================"
echo ""

# Color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}✗ Docker is not running. Please start Docker Desktop.${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Docker is running${NC}"

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null; then
    echo -e "${RED}✗ docker-compose not found. Please install Docker Compose.${NC}"
    exit 1
fi

echo -e "${GREEN}✓ docker-compose is available${NC}"
echo ""

# Stop any existing containers
echo -e "${YELLOW}Stopping any existing containers...${NC}"
docker-compose down 2>/dev/null

# Build and start containers
echo -e "${YELLOW}Building and starting containers...${NC}"
docker-compose up -d --build

echo ""
echo -e "${YELLOW}Waiting for services to be healthy (this may take 30-60 seconds)...${NC}"

# Wait for backend to be healthy
COUNTER=0
MAX_TRIES=60

while [ $COUNTER -lt $MAX_TRIES ]; do
    if docker-compose exec -T backend curl -f http://localhost:8000/health > /dev/null 2>&1; then
        echo -e "${GREEN}✓ Backend is healthy${NC}"
        break
    fi
    
    if [ $COUNTER -eq $MAX_TRIES ]; then
        echo -e "${RED}✗ Backend failed to start. Check logs with: docker-compose logs backend${NC}"
        exit 1
    fi
    
    echo -n "."
    sleep 2
    COUNTER=$((COUNTER+1))
done

echo ""

# Initialize database
echo -e "${YELLOW}Initializing database...${NC}"
docker-compose exec -T backend python init_db.py

echo ""
echo "========================================"
echo -e "${GREEN}✓ Setup Complete!${NC}"
echo "========================================"
echo ""
echo "Services are running at:"
echo "  • Frontend:  http://localhost:3000"
echo "  • Backend:   http://localhost:8000"
echo "  • API Docs:  http://localhost:8000/docs"
echo ""
echo "Default Credentials:"
echo "  • Admin:    username: admin     password: admin123"
echo "  • Producer: username: producer1 password: producer123"
echo ""
echo "Useful Commands:"
echo "  • View logs:        docker-compose logs -f"
echo "  • Stop services:    docker-compose down"
echo "  • Restart:          docker-compose restart"
echo ""
echo "========================================"
