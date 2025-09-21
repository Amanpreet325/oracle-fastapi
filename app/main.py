import os
import httpx
import hashlib
import base64
import secrets
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, RedirectResponse
from dotenv import load_dotenv
from typing import Optional

# Load environment variables
load_dotenv()

app = FastAPI(title="Oracle Health FHIR API Integration", version="1.0.0")

# Mount static files
app.mount("/static", StaticFiles(directory="frontend"), name="static")

# Configuration - Updated with correct Cerner URLs and Client ID
ORACLE_CLIENT_ID = os.getenv("ORACLE_CLIENT_ID", "1f2fbb4d-d9e4-4790-b37f-d54c6656ee71")
TENANT_ID = os.getenv("TENANT_ID", "ec2458f2-1e24-41c8-b71b-0e701af7583d")
REDIRECT_URI = os.getenv("REDIRECT_URI", "http://localhost:8080/callback")

# Oracle Health FHIR R4 URLs (updated for your public app configuration)
AUTH_URL = f"https://authorization.cerner.com/tenants/{TENANT_ID}/protocols/oauth2/profiles/smart-v1/personas/provider/authorize"
TOKEN_URL = f"https://authorization.cerner.com/tenants/{TENANT_ID}/protocols/oauth2/profiles/smart-v1/token"
FHIR_BASE_URL = f"https://fhir-ehr-code.cerner.com/r4/{TENANT_ID}"

# Global variables for PKCE and token storage
code_verifier_store = {}
access_token_cache: Optional[str] = None


# --- PKCE Helpers ---
def generate_code_verifier():
    """Generate a cryptographically random code verifier for PKCE"""
    return base64.urlsafe_b64encode(secrets.token_bytes(40)).rstrip(b'=').decode('utf-8')

def generate_code_challenge(verifier: str):
    """Generate code challenge from verifier using SHA256"""
    digest = hashlib.sha256(verifier.encode('utf-8')).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b'=').decode('utf-8')

async def exchange_code_for_token(authorization_code: str, code_verifier: str) -> dict:
    """
    Exchange authorization code for access token using PKCE
    """
    if not ORACLE_CLIENT_ID:
        raise HTTPException(
            status_code=500, 
            detail="Oracle client ID not configured. Please check your .env file."
        )
    
    data = {
        "grant_type": "authorization_code",
        "code": authorization_code,
        "redirect_uri": REDIRECT_URI,
        "client_id": ORACLE_CLIENT_ID,
        "code_verifier": code_verifier
    }
    
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(TOKEN_URL, headers=headers, data=data)
            response.raise_for_status()
            
            token_data = response.json()
            
            if not token_data.get("access_token"):
                raise HTTPException(status_code=500, detail="No access token received from Oracle")
            
            return token_data
            
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Failed to exchange code for token: {e.response.text}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error exchanging code for token: {str(e)}")


@app.get("/")
async def root():
    """
    Root endpoint that serves the frontend.
    """
    return {"message": "Oracle Health FHIR API Integration", "auth_url": "/login", "frontend": "/static/index.html"}


@app.get("/login")
async def login():
    """
    Start OAuth2 PKCE flow for Oracle Health FHIR R4 - Public Standalone App
    """
    if not ORACLE_CLIENT_ID:
        raise HTTPException(status_code=500, detail="Oracle client ID not configured")
    
    # Generate PKCE parameters
    code_verifier = generate_code_verifier()
    code_challenge = generate_code_challenge(code_verifier)
    
    # Generate a unique state parameter for security
    state = secrets.token_urlsafe(32)
    
    # Store code verifier with state for later retrieval
    code_verifier_store[state] = code_verifier
    
    # Updated scopes for Oracle Health FHIR R4 public app - removed 'launch' for standalone
    scope = "patient/Patient.read patient/Observation.read patient/MedicationHistory.read openid profile"
    auth_url = (
        f"{AUTH_URL}?"
        f"response_type=code&"
        f"client_id={ORACLE_CLIENT_ID}&"
        f"redirect_uri={REDIRECT_URI}&"
        f"scope={scope.replace(' ', '%20')}&"
        f"code_challenge={code_challenge}&"
        f"code_challenge_method=S256&"
        f"state={state}&"
        f"aud={FHIR_BASE_URL}"
    )
    
    print(f"=== OAuth2 Configuration Debug ===")
    print(f"Client ID: {ORACLE_CLIENT_ID}")
    print(f"Auth URL: {AUTH_URL}")
    print(f"FHIR Base: {FHIR_BASE_URL}")
    print(f"Redirect URI: {REDIRECT_URI}")
    print(f"Scopes: {scope}")
    print(f"Generated Auth URL: {auth_url}")
    print(f"====================================")
    
    return {
        "auth_url": auth_url,
        "message": "Visit the auth_url to authorize the application",
        "state": state,
        "api_product": "Oracle Health FHIR APIs for Millennium: FHIR R4, All",
        "privacy": "Public",
        "launch_type": "Standalone",
        "fhir_version": "R4"
    }


@app.get("/callback")
async def callback(request: Request):
    """
    Handle OAuth2 callback from Oracle Health authorization server
    """
    # Get query parameters
    query_params = dict(request.query_params)
    
    # Check for OAuth errors first
    if "error" in query_params:
        error_code = query_params.get("error")
        error_description = query_params.get("error_description", "No description provided")
        error_uri = query_params.get("error_uri", "")
        
        print(f"OAuth Error: {error_code}")
        print(f"Error Description: {error_description}")
        print(f"Error URI: {error_uri}")
        
        # Handle specific launch context error
        if "launch:code-required" in error_uri or error_code == "invalid_request":
            return JSONResponse(
                status_code=400,
                content={
                    "error": "Launch Context Required",
                    "message": "This app requires EHR launch context. Please configure your Oracle app for 'Standalone Launch'.",
                    "details": {
                        "error_code": error_code,
                        "error_description": error_description,
                        "error_uri": error_uri,
                        "solution": "In your Oracle developer portal, change app launch type to 'Standalone' or remove 'launch' scope"
                    }
                }
            )
        
        return JSONResponse(
            status_code=400,
            content={
                "error": "Authorization Failed",
                "error_code": error_code,
                "error_description": error_description,
                "error_uri": error_uri
            }
        )
    
    # Check for authorization code
    code = query_params.get("code")
    state = query_params.get("state")
    
    if not code:
        return JSONResponse(
            status_code=400,
            content={
                "error": "Missing authorization code",
                "message": "No authorization code received from Oracle Health",
                "query_params": query_params
            }
        )
    
    if not state or state not in code_verifier_store:
        return JSONResponse(
            status_code=400,
            content={
                "error": "Invalid state parameter",
                "message": "State parameter missing or invalid"
            }
        )
    
    try:
        # Exchange code for token
        code_verifier = code_verifier_store.pop(state)
        token_data = await exchange_code_for_token(code, code_verifier)
        
        # Store access token globally
        global access_token_cache
        access_token_cache = token_data.get("access_token")
        
        print(f"Token exchange successful!")
        print(f"Access token received: {access_token_cache[:20]}...")
        print(f"Token type: {token_data.get('token_type')}")
        print(f"Expires in: {token_data.get('expires_in')}")
        print(f"Scope: {token_data.get('scope')}")
        
        return JSONResponse(content={
            "message": "Authorization successful! You can now fetch patient data.",
            "token_type": token_data.get("token_type"),
            "expires_in": token_data.get("expires_in"),
            "scope": token_data.get("scope"),
            "patient": token_data.get("patient"),
            "redirect_to": "/static/index.html"
        })
        
    except Exception as e:
        print(f"Token exchange error: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={
                "error": "Token exchange failed",
                "message": str(e)
            }
        )


@app.get("/patients")
async def get_patients():
    """
    Fetch patients from Oracle Health FHIR R4 API.
    Requires prior authorization via /login and /callback flow.
    """
    global access_token_cache
    
    if not access_token_cache:
        raise HTTPException(
            status_code=401, 
            detail="No access token available. Please complete authorization flow first by visiting /login"
        )
    
    try:
        # Set up headers for FHIR R4 API call
        headers = {
            "Authorization": f"Bearer {access_token_cache}",
            "Accept": "application/fhir+json",  # FHIR R4 format
            "Content-Type": "application/fhir+json"
        }
        
        # Make request to FHIR Patient endpoint
        patient_url = f"{FHIR_BASE_URL}/Patient"
        
        print(f"=== FHIR R4 API Request ===")
        print(f"URL: {patient_url}")
        print(f"Headers: {headers}")
        print(f"Access Token: {access_token_cache[:20]}...")
        print(f"==========================")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(patient_url, headers=headers)
            
            print(f"FHIR Response Status: {response.status_code}")
            print(f"FHIR Response Headers: {dict(response.headers)}")
            print(f"FHIR Response Preview: {response.text[:200]}...")
            
            response.raise_for_status()
            
            fhir_data = response.json()
            
            return {
                "message": "Successfully fetched patients from Oracle Health FHIR R4",
                "api_version": "FHIR R4",
                "total": fhir_data.get("total", 0),
                "resource_type": fhir_data.get("resourceType"),
                "request_url": patient_url,
                "response": fhir_data
            }
            
    except httpx.HTTPStatusError as e:
        error_response = e.response.text if hasattr(e.response, 'text') else str(e)
        print(f"FHIR API error: {e.response.status_code} - {error_response}")
        
        if e.response.status_code == 401:
            access_token_cache = None
            raise HTTPException(
                status_code=401, 
                detail="Access token expired or invalid. Please re-authorize."
            )
        
        raise HTTPException(
            status_code=e.response.status_code, 
            detail=f"FHIR API error: {error_response}"
        )
    except Exception as e:
        print(f"Error fetching patients: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/health")
async def health_check():
    """
    Health check endpoint with updated configuration details.
    """
    return {
        "status": "healthy",
        "service": "Oracle Health FHIR API Integration",
        "auth_flow": "OAuth2 PKCE",
        "client_id": ORACLE_CLIENT_ID,
        "tenant_id": TENANT_ID,
        "redirect_uri": REDIRECT_URI,
        "endpoints": {
            "auth_url": AUTH_URL,
            "token_url": TOKEN_URL,
            "fhir_base_url": FHIR_BASE_URL
        },
        "has_active_token": bool(access_token_cache)
    }


@app.get("/test-fhir-metadata")
async def test_fhir_metadata():
    """
    Test FHIR metadata endpoint to verify the R4 endpoint is working
    """
    try:
        metadata_url = f"{FHIR_BASE_URL}/metadata"
        headers = {
            "Accept": "application/fhir+json"  # FHIR R4 format
        }
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(metadata_url, headers=headers)
            
            result = {
                "url": metadata_url,
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "reachable": True
            }
            
            if response.status_code == 200:
                try:
                    metadata = response.json()
                    result["fhir_version"] = metadata.get("fhirVersion", "Unknown")
                    result["server_name"] = metadata.get("name", "Unknown")
                    result["server_description"] = metadata.get("description", "No description")
                except:
                    result["response_preview"] = response.text[:500]
            else:
                result["error_text"] = response.text
            
            return result
            
    except Exception as e:
        return {
            "url": f"{FHIR_BASE_URL}/metadata",
            "error": str(e),
            "reachable": False
        }


# === ORACLE HEALTH OPEN SANDBOX ENDPOINTS (NO LOGIN REQUIRED) ===

@app.get("/oracle-sandbox/patients")
async def get_sandbox_patients(
    family: Optional[str] = None,
    given: Optional[str] = None, 
    name: Optional[str] = None,
    gender: Optional[str] = None,
    birthdate: Optional[str] = None,
    _count: int = 20
):
    """
    Search demo patients from Oracle Health Open Sandbox with filters
    Required: At least one search parameter (family, given, name, gender, or birthdate)
    
    Parameters:
    - family: Family name (last name) to search for
    - given: Given name (first name) to search for  
    - name: Any part of the name to search for
    - gender: Gender filter (male, female, other, unknown)
    - birthdate: Birth date in YYYY-MM-DD format
    - _count: Number of results to return (default 20)
    """
    try:
        # Oracle Health Open Sandbox (no auth required)
        sandbox_base_url = f"https://fhir-open.cerner.com/r4/{TENANT_ID}"
        
        # Build query parameters - at least one is required
        query_params = []
        if family:
            query_params.append(f"family={family}")
        if given:
            query_params.append(f"given={given}")
        if name:
            query_params.append(f"name={name}")
        if gender:
            query_params.append(f"gender={gender}")
        if birthdate:
            query_params.append(f"birthdate={birthdate}")
        
        # Add count parameter
        query_params.append(f"_count={_count}")
        
        # If no search parameters provided, use default searches
        if not any([family, given, name, gender, birthdate]):
            # Default search - try common names
            query_params = ["family=Smart", f"_count={_count}"]
        
        query_string = "&".join(query_params)
        patients_url = f"{sandbox_base_url}/Patient?{query_string}"
        
        headers = {
            "Accept": "application/fhir+json",
            "User-Agent": "Oracle-Health-Demo-Client"
        }
        
        print(f"=== Oracle Sandbox Patient Search ===")
        print(f"URL: {patients_url}")
        print(f"Search Parameters: {query_params}")
        print(f"=====================================")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(patients_url, headers=headers)
            
            print(f"Sandbox Response Status: {response.status_code}")
            
            response.raise_for_status()
            fhir_data = response.json()
            
            # Extract patient summaries for easy viewing
            patient_summaries = []
            if fhir_data.get("entry"):
                for entry in fhir_data["entry"]:
                    resource = entry.get("resource", {})
                    if resource.get("resourceType") == "Patient":
                        # Format names nicely
                        formatted_names = []
                        for name_obj in resource.get("name", []):
                            name_parts = []
                            if name_obj.get("given"):
                                name_parts.extend(name_obj["given"])
                            if name_obj.get("family"):
                                name_parts.append(name_obj["family"])
                            if name_parts:
                                formatted_names.append(" ".join(name_parts))
                        
                        # Calculate age from birth date
                        birth_date = resource.get("birthDate")
                        age = None
                        birth_year = None
                        if birth_date:
                            from datetime import datetime
                            birth_year = int(birth_date.split("-")[0])
                            current_year = datetime.now().year
                            age = current_year - birth_year
                        
                        # Format addresses nicely
                        formatted_addresses = []
                        for addr in resource.get("address", []):
                            address_parts = []
                            if addr.get("line"):
                                address_parts.extend(addr["line"])
                            if addr.get("city"):
                                address_parts.append(addr["city"])
                            if addr.get("state"):
                                address_parts.append(addr["state"])
                            if addr.get("postalCode"):
                                address_parts.append(addr["postalCode"])
                            formatted_addresses.append({
                                "use": addr.get("use", "unknown"),
                                "formatted_text": ", ".join(address_parts) if address_parts else "No address"
                            })
                        
                        # Format contact info nicely
                        formatted_contacts = []
                        for contact in resource.get("telecom", []):
                            formatted_contacts.append({
                                "type": contact.get("system", "unknown"),  # phone, email
                                "value": contact.get("value", ""),
                                "use": contact.get("use", "unknown")       # home, work, mobile
                            })
                        
                        summary = {
                            "id": resource.get("id"),
                            "active": resource.get("active"),
                            "gender": resource.get("gender"),
                            "birthDate": birth_date,
                            "birth_year": birth_year,
                            "calculated_age": age,
                            "formatted_names": formatted_names,
                            "formatted_addresses": formatted_addresses,
                            "formatted_contacts": formatted_contacts,
                            "raw_names": resource.get("name", []),
                            "raw_telecom": resource.get("telecom", []),
                            "raw_address": resource.get("address", []),
                            "maritalStatus": resource.get("maritalStatus", {})
                        }
                        patient_summaries.append(summary)
            
            return {
                "mode": "Oracle Health Open Sandbox - Patient Search",
                "description": "Searched demo patients with filters",
                "search_parameters": {
                    "family": family,
                    "given": given,
                    "name": name,
                    "gender": gender,
                    "birthdate": birthdate,
                    "count": _count
                },
                "total_found": fhir_data.get("total", 0),
                "patients_summary": patient_summaries,
                "raw_fhir_response": fhir_data,
                "endpoint_used": patients_url,
                "tenant_id": TENANT_ID
            }
            
    except httpx.HTTPStatusError as e:
        error_text = e.response.text
        print(f"Sandbox API error: {e.response.status_code} - {error_text}")
        
        # More helpful error message
        if "at least one of" in error_text:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "Search parameters required",
                    "message": "Oracle sandbox requires at least one search parameter",
                    "available_parameters": ["family", "given", "name", "gender", "birthdate"],
                    "examples": [
                        "?family=Smith",
                        "?given=John", 
                        "?name=John",
                        "?gender=male",
                        "?birthdate=1990-01-01"
                    ],
                    "oracle_error": error_text
                }
            )
        
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Oracle sandbox failed: {error_text}"
        )
    except Exception as e:
        print(f"Sandbox request error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Sandbox error: {str(e)}")


@app.get("/oracle-sandbox/patient/{patient_id}")
async def get_sandbox_patient_details(patient_id: str):
    """
    Get detailed information for a specific demo patient from Oracle sandbox
    """
    try:
        sandbox_base_url = f"https://fhir-open.cerner.com/r4/{TENANT_ID}"
        patient_url = f"{sandbox_base_url}/Patient/{patient_id}"
        
        headers = {
            "Accept": "application/fhir+json"
        }
        
        print(f"Fetching sandbox patient details: {patient_id}")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(patient_url, headers=headers)
            response.raise_for_status()
            
            patient_data = response.json()
            
            return {
                "mode": "Oracle Health Open Sandbox",
                "patient_id": patient_id,
                "data_type": "Demo Patient Details",
                "patient_data": patient_data,
                "endpoint_used": patient_url
            }
            
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Demo patient {patient_id} not found in sandbox")
        raise HTTPException(status_code=e.response.status_code, detail=f"Sandbox error: {e.response.text}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/oracle-sandbox/observations")
async def get_sandbox_observations():
    """
    Fetch demo observations/vitals from Oracle sandbox (no auth required)
    """
    try:
        sandbox_base_url = f"https://fhir-open.cerner.com/r4/{TENANT_ID}"
        obs_url = f"{sandbox_base_url}/Observation?_count=20"  # Limit to 20 results
        
        headers = {
            "Accept": "application/fhir+json"
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(obs_url, headers=headers)
            response.raise_for_status()
            
            obs_data = response.json()
            
            # Extract observation summaries
            observations = []
            if obs_data.get("entry"):
                for entry in obs_data["entry"]:
                    resource = entry.get("resource", {})
                    if resource.get("resourceType") == "Observation":
                        obs_summary = {
                            "id": resource.get("id"),
                            "status": resource.get("status"),
                            "category": resource.get("category", []),
                            "code": resource.get("code", {}),
                            "subject": resource.get("subject", {}),
                            "effectiveDateTime": resource.get("effectiveDateTime"),
                            "valueQuantity": resource.get("valueQuantity", {}),
                            "valueString": resource.get("valueString"),
                            "valueCodeableConcept": resource.get("valueCodeableConcept", {})
                        }
                        observations.append(obs_summary)
            
            return {
                "mode": "Oracle Health Open Sandbox - Observations",
                "data_type": "Demo Vitals/Observations",
                "total": obs_data.get("total", 0),
                "observations_summary": observations,
                "raw_fhir_response": obs_data,
                "endpoint_used": obs_url
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sandbox observations failed: {str(e)}")


@app.get("/oracle-sandbox/medications")
async def get_sandbox_medications():
    """
    Fetch demo medications from Oracle sandbox (no auth required)
    """
    try:
        sandbox_base_url = f"https://fhir-open.cerner.com/r4/{TENANT_ID}"
        med_url = f"{sandbox_base_url}/MedicationRequest?_count=15"
        
        headers = {
            "Accept": "application/fhir+json"
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(med_url, headers=headers)
            response.raise_for_status()
            
            med_data = response.json()
            
            # Extract medication summaries
            medications = []
            if med_data.get("entry"):
                for entry in med_data["entry"]:
                    resource = entry.get("resource", {})
                    if resource.get("resourceType") == "MedicationRequest":
                        med_summary = {
                            "id": resource.get("id"),
                            "status": resource.get("status"),
                            "medicationCodeableConcept": resource.get("medicationCodeableConcept", {}),
                            "subject": resource.get("subject", {}),
                            "authoredOn": resource.get("authoredOn"),
                            "dosageInstruction": resource.get("dosageInstruction", [])
                        }
                        medications.append(med_summary)
            
            return {
                "mode": "Oracle Health Open Sandbox - Medications",
                "data_type": "Demo Medications/Prescriptions",
                "total": med_data.get("total", 0),
                "medications_summary": medications,
                "raw_fhir_response": med_data,
                "endpoint_used": med_url
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sandbox medications failed: {str(e)}")


@app.get("/oracle-sandbox/test-known-patients")
async def test_known_sandbox_patients():
    """
    Test specific known demo patient IDs that should work in Oracle sandbox
    """
    # Known test patient IDs in Oracle Health sandbox
    test_patients = [
        "12724066", "12724067", "12724068", "4342012", "4342009", "4342008"
    ]
    
    results = {}
    sandbox_base_url = f"https://fhir-open.cerner.com/r4/{TENANT_ID}"
    
    for patient_id in test_patients:
        try:
            patient_url = f"{sandbox_base_url}/Patient/{patient_id}"
            headers = {"Accept": "application/fhir+json"}
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(patient_url, headers=headers)
                
                if response.status_code == 200:
                    patient_data = response.json()
                    results[patient_id] = {
                        "status": "found",
                        "name": patient_data.get("name", []),
                        "gender": patient_data.get("gender"),
                        "birthDate": patient_data.get("birthDate"),
                        "active": patient_data.get("active")
                    }
                else:
                    results[patient_id] = {
                        "status": "not_found",
                        "http_status": response.status_code
                    }
                    
        except Exception as e:
            results[patient_id] = {
                "status": "error",
                "error": str(e)
            }
    
    return {
        "mode": "Oracle Health Open Sandbox - Testing Known Patients",
        "data_type": "Demo Patient ID Tests",
        "base_url": sandbox_base_url,
        "tenant_id": TENANT_ID,
        "test_results": results,
        "note": "These are common test patient IDs in Oracle sandbox"
    }


# === PRESET PATIENT SEARCHES FOR EASY TESTING ===

@app.get("/oracle-sandbox/patients-by-gender/{gender}")
async def get_patients_by_gender(gender: str, _count: int = 15):
    """
    Quick search for patients by gender (male, female, other, unknown)
    """
    return await get_sandbox_patients(gender=gender.lower(), _count=_count)


@app.get("/oracle-sandbox/patients-by-family/{family_name}")
async def get_patients_by_family(family_name: str, _count: int = 15):
    """
    Quick search for patients by family/last name
    """
    return await get_sandbox_patients(family=family_name, _count=_count)


@app.get("/oracle-sandbox/patients-by-given/{given_name}")
async def get_patients_by_given(given_name: str, _count: int = 15):
    """
    Quick search for patients by given/first name
    """
    return await get_sandbox_patients(given=given_name, _count=_count)


@app.get("/oracle-sandbox/common-patient-searches")
async def get_common_patient_searches():
    """
    Get suggestions for common patient searches that work in Oracle sandbox
    """
    return {
        "mode": "Oracle Health Open Sandbox - Search Suggestions",
        "description": "Common searches that typically return demo data",
        "search_examples": {
            "by_gender": {
                "male": "/oracle-sandbox/patients?gender=male",
                "female": "/oracle-sandbox/patients?gender=female"
            },
            "by_family_name": {
                "Smart": "/oracle-sandbox/patients?family=Smart",
                "Peters": "/oracle-sandbox/patients?family=Peters",
                "Bond": "/oracle-sandbox/patients?family=Bond",
                "Shaw": "/oracle-sandbox/patients?family=Shaw"
            },
            "by_given_name": {
                "Nancy": "/oracle-sandbox/patients?given=Nancy",
                "Timmy": "/oracle-sandbox/patients?given=Timmy",  
                "Aaron": "/oracle-sandbox/patients?given=Aaron"
            },
            "by_any_name": {
                "Smart": "/oracle-sandbox/patients?name=Smart",
                "Nancy": "/oracle-sandbox/patients?name=Nancy"
            }
        },
        "quick_endpoints": {
            "male_patients": "/oracle-sandbox/patients-by-gender/male",
            "female_patients": "/oracle-sandbox/patients-by-gender/female",
            "smart_family": "/oracle-sandbox/patients-by-family/Smart",
            "nancy_patients": "/oracle-sandbox/patients-by-given/Nancy"
        },
        "notes": [
            "Oracle sandbox requires at least one search parameter",
            "Try searching for common names like Smart, Peters, Nancy, Timmy",
            "Gender options: male, female, other, unknown",
            "Use _count parameter to limit results (default 20)"
        ]
    }


# === INSURANCE PLANS ENDPOINTS ===

@app.get("/oracle-sandbox/insurance-plans")
async def get_sandbox_insurance_plans(owned_by: Optional[str] = None, _count: int = 20):
    """
    Fetch demo insurance plans from Oracle sandbox (no auth required)
    
    Parameters:
    - owned_by: Organization ID that owns the insurance plans (e.g., "Organization/589783")
    - _count: Number of results to return (default 20)
    """
    try:
        sandbox_base_url = f"https://fhir-open.cerner.com/r4/{TENANT_ID}"
        
        # Build query parameters
        query_params = [f"_count={_count}"]
        if owned_by:
            query_params.append(f"owned-by={owned_by}")
        else:
            # Default to a known organization if none provided
            query_params.append("owned-by=Organization/589783")
        
        query_string = "&".join(query_params)
        insurance_url = f"{sandbox_base_url}/InsurancePlan?{query_string}"
        
        headers = {
            "Accept": "application/fhir+json",
            "User-Agent": "Oracle-Health-Demo-Client"
        }
        
        print(f"=== Oracle Sandbox Insurance Plans ===")
        print(f"URL: {insurance_url}")
        print(f"======================================")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(insurance_url, headers=headers)
            
            print(f"Insurance Plans Response Status: {response.status_code}")
            response.raise_for_status()
            
            insurance_data = response.json()
            
            # Extract insurance plan summaries
            plans_summary = []
            if insurance_data.get("entry"):
                for entry in insurance_data["entry"]:
                    resource = entry.get("resource", {})
                    if resource.get("resourceType") == "InsurancePlan":
                        plan_summary = {
                            "id": resource.get("id"),
                            "status": resource.get("status"),
                            "type": resource.get("type", []),
                            "name": resource.get("name"),
                            "alias": resource.get("alias", []),
                            "ownedBy": resource.get("ownedBy", {}),
                            "administeredBy": resource.get("administeredBy", {}),
                            "coverageArea": resource.get("coverageArea", []),
                            "contact": resource.get("contact", []),
                            "endpoint": resource.get("endpoint", [])
                        }
                        plans_summary.append(plan_summary)
            
            return {
                "mode": "Oracle Health Open Sandbox - Insurance Plans",
                "data_type": "Demo Insurance Plans",
                "search_parameters": {
                    "owned_by": owned_by or "Organization/589783",
                    "count": _count
                },
                "total_found": insurance_data.get("total", 0),
                "plans_summary": plans_summary,
                "raw_fhir_response": insurance_data,
                "endpoint_used": insurance_url,
                "tenant_id": TENANT_ID
            }
            
    except httpx.HTTPStatusError as e:
        error_text = e.response.text
        print(f"Insurance Plans API error: {e.response.status_code} - {error_text}")
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Oracle insurance plans sandbox failed: {error_text}"
        )
    except Exception as e:
        print(f"Insurance plans request error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Insurance plans error: {str(e)}")


@app.get("/oracle-sandbox/insurance-plan/{plan_id}")
async def get_sandbox_insurance_plan_by_id(plan_id: str):
    """
    Get detailed information for a specific insurance plan from Oracle sandbox
    Example: plan_id = "2798233"
    """
    try:
        sandbox_base_url = f"https://fhir-open.cerner.com/r4/{TENANT_ID}"
        plan_url = f"{sandbox_base_url}/InsurancePlan/{plan_id}"
        
        headers = {
            "Accept": "application/fhir+json",
            "User-Agent": "Oracle-Health-Demo-Client"
        }
        
        print(f"Fetching sandbox insurance plan: {plan_id}")
        print(f"URL: {plan_url}")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(plan_url, headers=headers)
            response.raise_for_status()
            
            plan_data = response.json()
            
            return {
                "mode": "Oracle Health Open Sandbox - Insurance Plan Details",
                "plan_id": plan_id,
                "data_type": "Demo Insurance Plan Details",
                "plan_data": plan_data,
                "endpoint_used": plan_url,
                "tenant_id": TENANT_ID
            }
            
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Insurance plan {plan_id} not found in sandbox")
        raise HTTPException(status_code=e.response.status_code, detail=f"Insurance plan error: {e.response.text}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching insurance plan: {str(e)}")


# === SPECIFIC MEDICATION REQUEST ENDPOINT ===

@app.get("/oracle-sandbox/medication-request/{request_id}")
async def get_sandbox_medication_request_by_id(request_id: str):
    """
    Get detailed information for a specific medication request from Oracle sandbox
    Example: request_id = "56770371"
    """
    try:
        sandbox_base_url = f"https://fhir-open.cerner.com/r4/{TENANT_ID}"
        med_request_url = f"{sandbox_base_url}/MedicationRequest/{request_id}"
        
        headers = {
            "Accept": "application/fhir+json",
            "User-Agent": "Oracle-Health-Demo-Client"
        }
        
        print(f"Fetching sandbox medication request: {request_id}")
        print(f"URL: {med_request_url}")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(med_request_url, headers=headers)
            response.raise_for_status()
            
            med_request_data = response.json()
            
            # Extract key medication details for easier viewing
            medication_summary = {
                "id": med_request_data.get("id"),
                "status": med_request_data.get("status"),
                "intent": med_request_data.get("intent"),
                "medicationCodeableConcept": med_request_data.get("medicationCodeableConcept", {}),
                "subject": med_request_data.get("subject", {}),
                "encounter": med_request_data.get("encounter", {}),
                "authoredOn": med_request_data.get("authoredOn"),
                "requester": med_request_data.get("requester", {}),
                "dosageInstruction": med_request_data.get("dosageInstruction", []),
                "dispenseRequest": med_request_data.get("dispenseRequest", {}),
                "substitution": med_request_data.get("substitution", {})
            }
            
            return {
                "mode": "Oracle Health Open Sandbox - Medication Request Details",
                "medication_request_id": request_id,
                "data_type": "Demo Medication Request Details",
                "medication_summary": medication_summary,
                "raw_medication_data": med_request_data,
                "endpoint_used": med_request_url,
                "tenant_id": TENANT_ID
            }
            
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Medication request {request_id} not found in sandbox")
        raise HTTPException(status_code=e.response.status_code, detail=f"Medication request error: {e.response.text}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching medication request: {str(e)}")


# === PATIENT COVERAGE/INSURANCE LOOKUP ===

@app.get("/oracle-sandbox/patient-coverage/{patient_id}")
async def get_patient_coverage(patient_id: str):
    """
    Get insurance/coverage information for a specific patient
    This searches the Coverage resource for the patient's insurance plans
    """
    try:
        sandbox_base_url = f"https://fhir-open.cerner.com/r4/{TENANT_ID}"
        coverage_url = f"{sandbox_base_url}/Coverage?patient=Patient/{patient_id}"
        
        headers = {
            "Accept": "application/fhir+json",
            "User-Agent": "Oracle-Health-Demo-Client"
        }
        
        print(f"Fetching coverage for patient: {patient_id}")
        print(f"URL: {coverage_url}")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(coverage_url, headers=headers)
            response.raise_for_status()
            
            coverage_data = response.json()
            
            # Extract coverage summaries
            coverage_summaries = []
            if coverage_data.get("entry"):
                for entry in coverage_data["entry"]:
                    resource = entry.get("resource", {})
                    if resource.get("resourceType") == "Coverage":
                        coverage_summary = {
                            "id": resource.get("id"),
                            "status": resource.get("status"),
                            "type": resource.get("type", {}),
                            "beneficiary": resource.get("beneficiary", {}),
                            "payor": resource.get("payor", []),
                            "period": resource.get("period", {}),
                            "subscriberId": resource.get("subscriberId"),
                            "relationship": resource.get("relationship", {}),
                            "network": resource.get("network"),
                            "order": resource.get("order")
                        }
                        coverage_summaries.append(coverage_summary)
            
            return {
                "mode": "Oracle Health Open Sandbox - Patient Coverage",
                "patient_id": patient_id,
                "data_type": "Patient Insurance/Coverage Information",
                "total_coverage_plans": coverage_data.get("total", 0),
                "coverage_summaries": coverage_summaries,
                "raw_coverage_data": coverage_data,
                "endpoint_used": coverage_url,
                "tenant_id": TENANT_ID
            }
            
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail=f"No coverage found for patient {patient_id}")
        raise HTTPException(status_code=e.response.status_code, detail=f"Coverage lookup error: {e.response.text}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching patient coverage: {str(e)}")


@app.get("/oracle-sandbox/patient-complete/{patient_id}")
async def get_complete_patient_profile(patient_id: str):
    """
    Get complete patient profile including demographics, insurance, and calculated age
    This combines Patient resource with Coverage lookup
    """
    try:
        sandbox_base_url = f"https://fhir-open.cerner.com/r4/{TENANT_ID}"
        
        # Get patient demographics
        patient_url = f"{sandbox_base_url}/Patient/{patient_id}"
        coverage_url = f"{sandbox_base_url}/Coverage?patient=Patient/{patient_id}"
        
        headers = {
            "Accept": "application/fhir+json",
            "User-Agent": "Oracle-Health-Demo-Client"
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Get patient data
            patient_response = await client.get(patient_url, headers=headers)
            patient_response.raise_for_status()
            patient_data = patient_response.json()
            
            # Calculate age from birth date
            birth_date = patient_data.get("birthDate")
            age = None
            if birth_date:
                from datetime import datetime
                birth_year = int(birth_date.split("-")[0])
                current_year = datetime.now().year
                age = current_year - birth_year
            
            # Format patient summary with additional calculated fields
            patient_summary = {
                "id": patient_data.get("id"),
                "active": patient_data.get("active"),
                "gender": patient_data.get("gender"),
                "birthDate": birth_date,
                "calculated_age": age,
                "maritalStatus": patient_data.get("maritalStatus", {}),
                "communication": patient_data.get("communication", []),
                "generalPractitioner": patient_data.get("generalPractitioner", [])
            }
            
            # Format names
            formatted_names = []
            for name_obj in patient_data.get("name", []):
                name_parts = []
                if name_obj.get("given"):
                    name_parts.extend(name_obj["given"])
                if name_obj.get("family"):
                    name_parts.append(name_obj["family"])
                if name_parts:
                    formatted_names.append(" ".join(name_parts))
            patient_summary["formatted_names"] = formatted_names
            
            # Format addresses with more detail
            formatted_addresses = []
            for addr in patient_data.get("address", []):
                address_parts = []
                if addr.get("line"):
                    address_parts.extend(addr["line"])
                if addr.get("city"):
                    address_parts.append(addr["city"])
                if addr.get("state"):
                    address_parts.append(addr["state"])
                if addr.get("postalCode"):
                    address_parts.append(addr["postalCode"])
                if addr.get("country"):
                    address_parts.append(addr["country"])
                
                formatted_addresses.append({
                    "use": addr.get("use"),
                    "type": addr.get("type"),
                    "formatted_text": ", ".join(address_parts),
                    "period": addr.get("period", {})
                })
            patient_summary["formatted_addresses"] = formatted_addresses
            
            # Format contact info
            formatted_contacts = []
            for contact in patient_data.get("telecom", []):
                formatted_contacts.append({
                    "system": contact.get("system"),  # phone, email, etc.
                    "value": contact.get("value"),
                    "use": contact.get("use"),        # home, work, mobile
                    "rank": contact.get("rank")
                })
            patient_summary["formatted_contacts"] = formatted_contacts
            
            # Try to get coverage data (may not exist for all patients)
            coverage_summaries = []
            try:
                coverage_response = await client.get(coverage_url, headers=headers)
                if coverage_response.status_code == 200:
                    coverage_data = coverage_response.json()
                    if coverage_data.get("entry"):
                        for entry in coverage_data["entry"]:
                            resource = entry.get("resource", {})
                            if resource.get("resourceType") == "Coverage":
                                coverage_summaries.append({
                                    "id": resource.get("id"),
                                    "status": resource.get("status"),
                                    "type": resource.get("type", {}),
                                    "payor": resource.get("payor", []),
                                    "subscriberId": resource.get("subscriberId"),
                                    "relationship": resource.get("relationship", {}),
                                    "period": resource.get("period", {})
                                })
            except:
                pass  # Coverage data not available for this patient
            
            return {
                "mode": "Oracle Health Open Sandbox - Complete Patient Profile",
                "patient_id": patient_id,
                "data_type": "Complete Patient Demographics + Insurance",
                "patient_summary": patient_summary,
                "insurance_coverage": coverage_summaries,
                "has_insurance_data": len(coverage_summaries) > 0,
                "raw_patient_data": patient_data,
                "endpoints_used": [patient_url, coverage_url],
                "tenant_id": TENANT_ID
            }
            
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found in sandbox")
        raise HTTPException(status_code=e.response.status_code, detail=f"Patient lookup error: {e.response.text}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching complete patient profile: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8080, reload=True)