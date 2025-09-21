# Oracle Health FHIR API Integration

A FastAPI backend that integrates with Oracle Health FHIR APIs to fetch patient data, with a simple HTML frontend for testing.
<img width="1607" height="612" alt="image" src="https://github.com/user-attachments/assets/57050e5e-6b87-4eae-8b72-4a88b8dc2084" />

<img width="1412" height="685" alt="image" src="https://github.com/user-attachments/assets/c45c95cd-8e60-4b6b-8004-e5942a88f490" />


## Features

- **FastAPI Backend**: Modern, fast web framework for building APIs
- **OAuth2 PKCE Flow**: Secure authentication without client secrets (perfect for Oracle Health)
- **Patient Data Retrieval**: Fetch patient information from Oracle Health FHIR R4 endpoints
- **Interactive Frontend**: Clean HTML interface with step-by-step authorization process
- **Session Management**: Handles token storage and expiration
- **Error Handling**: Comprehensive error handling and user feedback
- **Health Check**: Built-in health check endpoint

## Project Structure

```
fastapi-oracle/
├── app/
│   └── main.py              # FastAPI backend application
├── frontend/
│   └── index.html           # HTML frontend interface
├── .env                     # Environment variables (create from .env.example)
├── .env.example             # Environment variables template
├── requirements.txt         # Python dependencies
└── README.md               # This file
```

## Prerequisites

- Python 3.12 or higher
- Oracle Health FHIR API credentials (Client ID and Client Secret)
- pip (Python package installer)

## Setup Instructions

### 1. Clone or Download the Project

Ensure you have all the project files in your working directory.

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables

1. Copy the example environment file:
   ```bash
   copy .env.example .env
   ```

2. Edit the `.env` file and add your Oracle Health FHIR API credentials:
   ```
   ORACLE_CLIENT_ID=your_actual_client_id
   TENANT_ID=ec2458f2-1e24-41c8-b71b-0e701af7583d
   REDIRECT_URI=http://localhost:8000/callback
   ```

   **Important**: 
   - Replace `your_actual_client_id` with your Client ID from Oracle Health
   - Update `TENANT_ID` if you have a different tenant ID  
   - Keep `REDIRECT_URI` as shown (this must match what you configured in Oracle Health)

### 4. Run the Application

```bash
uvicorn app.main:app --reload
```

The application will start on `http://127.0.0.1:8000`

### 5. Access the Frontend

Open your web browser and navigate to:
```
http://127.0.0.1:8000/static/index.html
```

## API Endpoints

### Backend Endpoints

- **GET /** - Root endpoint with basic information
- **GET /login** - Start OAuth2 PKCE authorization flow
- **GET /callback** - Handle OAuth2 callback (used automatically)
- **GET /patients** - Fetch patients from Oracle Health FHIR API (requires authorization)
- **GET /health** - Health check endpoint
- **GET /docs** - Auto-generated API documentation (Swagger UI)
- **GET /redoc** - Alternative API documentation

### Frontend

- **/static/** - Serves the HTML frontend from the `frontend/` directory

## Usage

### Step-by-Step Authorization Process

1. **Start the server** using the command above
2. **Open the frontend** in your browser: `http://127.0.0.1:8000/static/index.html`
3. **Click "Start Authorization"** - this will provide you with an Oracle Health authorization link
4. **Click the authorization link** - you'll be redirected to Oracle Health to log in
5. **Complete Oracle Health login** - after login, you'll be redirected back to your app
6. **Click "Fetch Patients"** - now you can retrieve patient data from Oracle Health FHIR API
7. **View the results** - patient data will be displayed in JSON format

### What You'll See

The frontend will display:
- Step-by-step authorization instructions
- Success/error messages for each step
- Patient statistics (total count, resource type, etc.) 
- Full JSON response from the FHIR API
- Token status and expiration handling

## Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `ORACLE_CLIENT_ID` | Your Oracle Health FHIR API Client ID | Yes |
| `TENANT_ID` | Your Oracle Health Tenant/Organization ID | Yes |
| `REDIRECT_URI` | OAuth2 callback URI (must match Oracle Health config) | Yes |

### Oracle Health (Cerner) FHIR API Endpoints

The application connects to these Oracle Health endpoints:

- **Authorization URL**: `https://fhir-ehr.sandboxcerner.com/{TENANT_ID}/auth/authorize`
- **Token URL**: `https://fhir-ehr.sandboxcerner.com/{TENANT_ID}/auth/token`
- **Patient API**: `https://fhir-ehr.sandboxcerner.com/{TENANT_ID}/r4/Patient`

Note: Replace `{TENANT_ID}` with your actual tenant ID from the `.env` file.

## Development

### Running in Development Mode

The `--reload` flag enables auto-reload when you make changes to the code:

```bash
uvicorn app.main:app --reload
```

### Testing the API

You can test the API endpoints directly:

1. **Health Check**:
   ```bash
   curl http://127.0.0.1:8000/health
   ```

2. **Fetch Patients**:
   ```bash
   curl http://127.0.0.1:8000/patients
   ```

3. **API Documentation**:
   Visit `http://127.0.0.1:8000/docs` for interactive API documentation.

## Error Handling

The application includes comprehensive error handling:

- **Configuration Errors**: Missing environment variables
- **Authentication Errors**: Invalid credentials or token issues
- **API Errors**: FHIR API request failures
- **Network Errors**: Connection timeouts or network issues

Error messages are displayed both in the API responses and the frontend interface.

## Security Notes

- Keep your `.env` file secure and never commit it to version control
- The `.env.example` file is safe to commit as it contains only placeholders
- Access tokens are cached in memory (consider using Redis for production)
- All API communications use HTTPS

## Troubleshooting

### Common Issues

1. **"Oracle client credentials not configured"**
   - Ensure your `.env` file exists and contains valid credentials
   - Check that environment variable names match exactly

2. **"Failed to get access token"**
   - Verify your Client ID and Client Secret are correct
   - Ensure you have proper permissions with Oracle Health

3. **"FHIR API request failed"**
   - Check your internet connection
   - Verify the FHIR endpoints are accessible
   - Ensure your Oracle Health account has FHIR API access

4. **Frontend not loading**
   - Make sure you're accessing `http://127.0.0.1:8000/index.html` (note the `/index.html`)
   - Check that the `frontend/` directory exists and contains `index.html`

### Logs

The application logs detailed information about requests and errors. Check the console output where you ran the `uvicorn` command for diagnostic information.

## Dependencies

- **fastapi==0.104.1**: Modern web framework for building APIs
- **uvicorn[standard]==0.24.0**: ASGI server implementation
- **httpx==0.25.2**: HTTP client for making API requests
- **python-dotenv==1.0.0**: Load environment variables from .env files
- **pydantic==2.5.0**: Data validation and settings management

## License

This project is provided as-is for integration with Oracle Health FHIR APIs. Please ensure compliance with Oracle Health's terms of service and API usage guidelines.
