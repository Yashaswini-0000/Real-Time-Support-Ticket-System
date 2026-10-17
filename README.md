
# Real-Time Support Ticket System

## Project Overview
A backend application built with FastAPI to manage customer support tickets, agent assignments, real-time chat, notifications, SLA monitoring, customer feedback, and reports.

## Technology Stack
- Python
- FastAPI
- SQLAlchemy (Async)
- MySQL
- Alembic
- JWT Authentication
- WebSockets
- APScheduler
- Pydantic

## Features
- User authentication and role-based access control
- Ticket creation and lifecycle management
- Category and SLA policy management
- Automatic ticket assignment to available agents
- Real-time ticket chat using WebSockets
- Internal notes and message history
- Notifications and read-status tracking
- SLA breach monitoring and ticket escalation
- Customer feedback and ratings
- Input validation and error handling
- Ticket search, filtering, sorting, and pagination
- Reports and analytics

## Project Setup

### 1. Clone the repository
```bash
git clone YOUR_GITHUB_REPOSITORY_URL
cd real_time_support_ticket_system
```

### 2. Create a virtual environment
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure environment variables
Create a `.env` file using `.env.example` as a reference. Configure your database URL, JWT secret, and other required settings.

Do not upload your `.env` file or share secret keys.

### 5. Run database migrations
```bash
alembic upgrade head
```

### 6. Start the application
```bash
uvicorn app.main:app --reload
```

## API Documentation
After starting the server, visit:

http://127.0.0.1:8000/docs

## Testing
Run the available test scripts as appropriate for your project configuration.

## Author
Srirangam Yashaswini
