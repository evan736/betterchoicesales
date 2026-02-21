"""NowCerts API integration service.

Handles authentication, searching insureds, fetching policies,
and pushing new insureds/policies to NowCerts.

API docs: https://api.nowcerts.com/Help
"""
import logging
import requests
from datetime import datetime, timedelta
from typing import Optional
from app.core.config import settings

logger = logging.getLogger(__name__)


class NowCertsClient:
    """Client for the NowCerts REST API."""

    def __init__(self):
        self.base_url = settings.NOWCERTS_API_URL.rstrip("/")
        self.username = settings.NOWCERTS_USERNAME
        self.password = settings.NOWCERTS_PASSWORD
        self._token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None
        self._last_auth_errors: list[str] = []

    @property
    def is_configured(self) -> bool:
        return bool(self.username and self.password)

    def _authenticate(self) -> str:
        """Get an OAuth2 token from NowCerts. Tries multiple auth methods."""
        if self._token and self._token_expiry and datetime.utcnow() < self._token_expiry:
            return self._token

        if not self.is_configured:
            raise ValueError("NowCerts credentials not configured")

        errors = []

        # Method 1: OAuth2 password grant at /api/token
        try:
            resp = requests.post(
                f"{self.base_url}/api/token",
                data={
                    "username": self.username,
                    "password": self.password,
                    "grant_type": "password",
                    "client_id": "ngAuthApp",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15,
            )
            logger.info("NowCerts /api/token response: status=%s", resp.status_code)

            if resp.status_code == 200:
                data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                token = data.get("access_token")
                if token:
                    self._token = token
                    expires_in = data.get("expires_in", 3300)
                    self._token_expiry = datetime.utcnow() + timedelta(seconds=max(expires_in - 60, 60))
                    logger.info("NowCerts authenticated via /token")
                    return self._token
                # Some responses return token as plain text
                if resp.text and not resp.text.startswith("{"):
                    self._token = resp.text.strip().strip('"')
                    self._token_expiry = datetime.utcnow() + timedelta(minutes=55)
                    logger.info("NowCerts authenticated via /token (plain text)")
                    return self._token
                errors.append(f"/api/token 200 but no access_token in response: {resp.text[:200]}")
            else:
                errors.append(f"/api/token returned {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            errors.append(f"/api/token exception: {str(e)}")

        # Method 2: Identity/Login JSON endpoint
        try:
            resp = requests.post(
                f"{self.base_url}/Identity/Login",
                json={"username": self.username, "password": self.password},
                headers={"Content-Type": "application/json"},
                timeout=15,
            )
            logger.info("NowCerts /Identity/Login response: status=%s body=%s", resp.status_code, resp.text[:300])

            if resp.status_code == 200:
                data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                token = (
                    data.get("access_token")
                    or data.get("token")
                    or data.get("Token")
                    or data.get("accessToken")
                )
                if token:
                    self._token = token
                    self._token_expiry = datetime.utcnow() + timedelta(minutes=55)
                    logger.info("NowCerts authenticated via /Identity/Login")
                    return self._token
                # Plain text token
                if resp.text and not resp.text.startswith("{") and not resp.text.startswith("<"):
                    self._token = resp.text.strip().strip('"')
                    self._token_expiry = datetime.utcnow() + timedelta(minutes=55)
                    logger.info("NowCerts authenticated via /Identity/Login (plain text)")
                    return self._token
                errors.append(f"/Identity/Login 200 but no token found: {resp.text[:200]}")
            else:
                errors.append(f"/Identity/Login returned {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            errors.append(f"/Identity/Login exception: {str(e)}")

        # Method 3: /api/token with form-urlencoded but no client_id
        try:
            resp = requests.post(
                f"{self.base_url}/api/token",
                data=f"username={self.username}&password={self.password}&grant_type=password",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json() if "json" in resp.headers.get("content-type", "") else {}
                token = data.get("access_token")
                if token:
                    self._token = token
                    self._token_expiry = datetime.utcnow() + timedelta(minutes=55)
                    logger.info("NowCerts authenticated via /api/token (no client_id)")
                    return self._token
            errors.append(f"/api/token (no client_id) returned {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            errors.append(f"/api/token (no client_id) exception: {str(e)}")

        self._last_auth_errors = errors
        error_msg = " | ".join(errors)
        logger.error("NowCerts auth failed all methods: %s", error_msg)
        raise ConnectionError(f"NowCerts authentication failed: {error_msg}")

    def _headers(self) -> dict:
        token = self._authenticate()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: dict = None) -> dict:
        resp = requests.get(
            f"{self.base_url}{path}",
            headers=self._headers(),
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, data: dict = None) -> dict:
        resp = requests.post(
            f"{self.base_url}{path}",
            headers=self._headers(),
            json=data,
            timeout=30,
        )
        resp.raise_for_status()
        # NowCerts sometimes returns empty body or plain text on success
        if not resp.text or not resp.text.strip():
            return {"status": "ok", "http_status": resp.status_code}
        try:
            return resp.json()
        except Exception:
            return {"status": "ok", "http_status": resp.status_code, "raw": resp.text[:500]}

    # ── Search / Read (using OData InsuredDetailList) ────────────────

    def _odata_get(self, endpoint: str, skip: int = 0, top: int = 100,
                   orderby: str = "id asc", count: bool = True,
                   filter_expr: str = None) -> dict:
        """Make an OData GET request with pagination."""
        url = f"{self.base_url}/api/{endpoint}"
        params = f"$count={'true' if count else 'false'}&$orderby={orderby}&$skip={skip}&$top={top}"
        if filter_expr:
            params += f"&$filter={filter_expr}"
        resp = requests.get(
            f"{url}?{params}",
            headers=self._headers(),
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()

    def search_insureds(self, query: str, limit: int = 50) -> list[dict]:
        """Search insureds via InsuredDetailList with OData filter."""
        try:
            if query:
                # OData filter: contains on commercialName, firstName, lastName, eMail, phone
                q = query.replace("'", "''")
                filter_parts = [
                    f"contains(tolower(commercialName), '{q.lower()}')",
                    f"contains(tolower(firstName), '{q.lower()}')",
                    f"contains(tolower(lastName), '{q.lower()}')",
                    f"contains(tolower(eMail), '{q.lower()}')",
                    f"contains(tolower(phone), '{q.lower()}')",
                    f"contains(tolower(cellPhone), '{q.lower()}')",
                    f"contains(tolower(city), '{q.lower()}')",
                ]
                filter_expr = " or ".join(filter_parts)
                data = self._odata_get("InsuredDetailList", skip=0, top=limit, filter_expr=filter_expr)
            else:
                data = self._odata_get("InsuredDetailList", skip=0, top=limit)

            results = data.get("value", [])
            # Normalize camelCase to our format
            return [self._normalize_odata_insured(r) for r in results]
        except Exception as e:
            logger.error("NowCerts search failed: %s", e)
            # Fallback to Zapier endpoint
            try:
                return self._search_via_zapier(query, limit)
            except Exception:
                return []

    def _search_via_zapier(self, query: str, limit: int) -> list[dict]:
        """Fallback search using Zapier/GetInsureds."""
        data = self._get("/api/Zapier/GetInsureds")
        results = data if isinstance(data, list) else []
        if query:
            q = query.lower()
            results = [r for r in results if
                q in (r.get("commercial_name") or "").lower() or
                q in (r.get("first_name") or "").lower() or
                q in (r.get("last_name") or "").lower() or
                q in (r.get("email") or "").lower() or
                q in (r.get("phone_number") or "").lower()
            ]
        return results[:limit]

    def _normalize_odata_insured(self, raw: dict) -> dict:
        """Convert OData InsuredDetailList camelCase to our snake_case format."""
        return {
            "database_id": raw.get("id", ""),
            "commercial_name": raw.get("commercialName", ""),
            "first_name": raw.get("firstName", ""),
            "middle_name": raw.get("middleName", ""),
            "last_name": raw.get("lastName", ""),
            "email": raw.get("eMail", ""),
            "address_line_1": raw.get("addressLine1", ""),
            "address_Line_2": raw.get("addressLine2", ""),
            "city": raw.get("city", ""),
            "state": raw.get("state", ""),
            "zip_code": raw.get("zipCode", ""),
            "phone_number": raw.get("phone", ""),
            "cell_phone": raw.get("cellPhone", ""),
            "sms_phone": raw.get("smsPhone", ""),
            "type": raw.get("type", ""),
            "active": raw.get("active", True),
            "website": raw.get("website", ""),
            "agents": [],  # Not in this endpoint
            "insured_id": raw.get("insuredId", ""),
            "customer_id": raw.get("customerId", ""),
            "date_of_birth": raw.get("dateOfBirth", ""),
            "change_date": raw.get("changeDate", ""),
            "create_date": raw.get("createDate", ""),
            "_raw": raw,
        }

    def get_insured(self, insured_database_id: str) -> Optional[dict]:
        """Get a single insured by NowCerts database ID."""
        try:
            filter_expr = f"id eq {insured_database_id}"
            data = self._odata_get("InsuredDetailList", skip=0, top=1, filter_expr=filter_expr)
            results = data.get("value", [])
            if results:
                return self._normalize_odata_insured(results[0])
            return None
        except Exception as e:
            logger.error("NowCerts get insured failed: %s", e)
            return None

    def get_all_policies(self) -> list[dict]:
        """Get all policies from NowCerts via Zapier endpoint (legacy, capped)."""
        try:
            data = self._get("/api/Zapier/GetPolicies")
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.error("NowCerts get all policies (Zapier) failed: %s", e)
            return []

    def get_all_policies_paginated(self, page_size: int = 200) -> list[dict]:
        """Get ALL policies from NowCerts using OData PolicyDetailList pagination."""
        all_results = []
        skip = 0
        total = None

        while True:
            try:
                data = self._odata_get("PolicyDetailList", skip=skip, top=page_size,
                                       orderby="number asc")
                batch = data.get("value", [])
                if total is None:
                    total = data.get("@odata.count", 0)
                    logger.info("NowCerts PolicyDetailList total: %d", total)

                if not batch:
                    break

                all_results.extend(batch)
                skip += len(batch)
                logger.info("NowCerts policy sync progress: %d / %d", len(all_results), total or "?")

                if total and skip >= total:
                    break
                if skip > 50000:  # Safety limit
                    break
            except Exception as e:
                logger.error("NowCerts policy pagination failed at skip=%d: %s", skip, e)
                break

        return all_results

    def _normalize_odata_policy(self, raw: dict, customer_id: int = None) -> dict:
        """Convert OData PolicyDetailList camelCase to our format."""
        # Extract line of business from the lineOfBusinesses array
        lob = ""
        lob_list = raw.get("lineOfBusinesses")
        if isinstance(lob_list, list) and lob_list:
            lob = lob_list[0].get("name", "") if isinstance(lob_list[0], dict) else str(lob_list[0])
        elif isinstance(lob_list, str):
            lob = lob_list

        premium = raw.get("totalPremium")

        # Parse dates
        eff_date = self._parse_date(raw.get("effectiveDate"))
        exp_date = self._parse_date(raw.get("expirationDate"))

        return {
            "nowcerts_policy_id": raw.get("databaseId", ""),
            "customer_id": customer_id,
            "policy_number": raw.get("number", ""),
            "carrier": raw.get("carrierName", ""),
            "line_of_business": lob,
            "policy_type": raw.get("businessType", ""),
            "status": raw.get("status", ""),
            "effective_date": eff_date,
            "expiration_date": exp_date,
            "premium": premium,
            "agent_name": None,
        }

    @staticmethod
    def _parse_date(val):
        """Parse ISO date string to datetime, handling timezone offsets."""
        if not val:
            return None
        try:
            from dateutil.parser import parse as dateparse
            return dateparse(val)
        except Exception:
            try:
                # Fallback: strip timezone and parse
                clean = val.split("T")[0]
                return datetime.strptime(clean, "%Y-%m-%d")
            except Exception:
                return None

    def get_insured_policies(self, insured_database_id: str) -> list[dict]:
        """Get policies for a specific insured."""
        try:
            try:
                data = self._post("/api/Insured/InsuredPolicies", {
                    "databaseIdOrNumber": insured_database_id,
                })
                result = data if isinstance(data, list) else data.get("data", data.get("policies", []))
                if result:
                    return result
            except Exception:
                pass

            # Fallback: OData filter by insuredDatabaseId
            try:
                filter_expr = f"insuredDatabaseId eq {insured_database_id}"
                data = self._odata_get("PolicyDetailList", skip=0, top=100,
                                       orderby="number asc", filter_expr=filter_expr)
                return data.get("value", [])
            except Exception:
                pass

            return []
        except Exception as e:
            logger.error("NowCerts get policies failed: %s", e)
            return []

    def get_all_insureds_paginated(self, page_size: int = 200) -> list[dict]:
        """Get ALL insureds from NowCerts using OData pagination. Returns normalized list."""
        all_results = []
        skip = 0
        total = None

        while True:
            try:
                data = self._odata_get("InsuredDetailList", skip=skip, top=page_size)
                batch = data.get("value", [])
                if total is None:
                    total = data.get("@odata.count", 0)
                    logger.info("NowCerts InsuredDetailList total: %d", total)

                if not batch:
                    break

                all_results.extend([self._normalize_odata_insured(r) for r in batch])
                skip += len(batch)

                logger.info("NowCerts sync progress: %d / %d", len(all_results), total or "?")

                if total and skip >= total:
                    break
                if skip > 10000:  # Safety limit
                    break
            except Exception as e:
                logger.error("NowCerts pagination failed at skip=%d: %s", skip, e)
                break

        return all_results

    def get_all_insureds(self, page: int = 1, page_size: int = 100) -> dict:
        """Get insureds for a specific page (used by sync-all)."""
        try:
            skip = (page - 1) * page_size
            data = self._odata_get("InsuredDetailList", skip=skip, top=page_size)
            batch = data.get("value", [])
            total = data.get("@odata.count", 0)
            return {
                "insureds": [self._normalize_odata_insured(r) for r in batch],
                "page": page,
                "page_size": page_size,
                "total": total,
            }
        except Exception as e:
            logger.error("NowCerts get all insureds failed: %s", e)
            return {"insureds": [], "page": page, "page_size": page_size, "total": 0}

    # ── Write / Push ───────────────────────────────────────────────

    def insert_insured(self, insured_data: dict) -> Optional[dict]:
        """Insert or update an insured in NowCerts.
        
        Expected fields: firstName, lastName, email, phone, address,
        city, state, zipCode, etc.
        """
        try:
            data = self._post("/api/Insured/Insert", insured_data)
            logger.info("NowCerts insured inserted/updated: %s", str(data)[:200])
            return data
        except Exception as e:
            logger.error("NowCerts insert insured failed: %s", e)
            return None

    def insert_policy(self, policy_data: dict) -> Optional[dict]:
        """Insert or update a policy in NowCerts.
        
        Expected fields: insuredDatabaseId, policyNumber, carrier,
        effectiveDate, expirationDate, premium, lineOfBusiness, etc.
        """
        try:
            data = self._post("/api/Quote/Insert", policy_data)
            logger.info("NowCerts policy inserted/updated: %s", str(data)[:200])
            return data
        except Exception as e:
            logger.error("NowCerts insert policy failed: %s", e)
            return None

    def insert_note(self, note_data: dict) -> Optional[dict]:
        """Insert a note for an insured in NowCerts.
        
        Accepts either snake_case or camelCase keys and normalizes to camelCase
        for the NowCerts Zapier API.
        """
        try:
            # Normalize field names to what NowCerts expects (camelCase)
            payload = {}
            
            # Note text/subject — NowCerts uses "subject" for the note content
            payload["subject"] = (
                note_data.get("subject") or 
                note_data.get("noteText") or 
                note_data.get("note_text") or ""
            )
            
            # Insured matching fields
            payload["insuredEmail"] = (
                note_data.get("insuredEmail") or 
                note_data.get("insured_email") or ""
            )
            payload["insuredFirstName"] = (
                note_data.get("insuredFirstName") or 
                note_data.get("insured_first_name") or ""
            )
            payload["insuredLastName"] = (
                note_data.get("insuredLastName") or 
                note_data.get("insured_last_name") or ""
            )
            
            # Note metadata
            payload["type"] = (
                note_data.get("type") or 
                note_data.get("noteType") or "Email"
            )
            payload["creatorName"] = (
                note_data.get("creatorName") or 
                note_data.get("creator_name") or "BCI System"
            )
            payload["createDate"] = (
                note_data.get("createDate") or 
                note_data.get("create_date") or 
                datetime.now().strftime("%m/%d/%Y %I:%M %p")
            )
            
            logger.info(
                "NowCerts InsertNote: insured=%s %s, email=%s, subject=%s",
                payload["insuredFirstName"], payload["insuredLastName"],
                payload["insuredEmail"], payload["subject"][:80]
            )
            
            data = self._post("/api/Zapier/InsertNote", payload)
            return data
        except Exception as e:
            logger.error("NowCerts insert note failed: %s", e)
            return None


# Singleton instance
_client: Optional[NowCertsClient] = None


def get_nowcerts_client() -> NowCertsClient:
    global _client
    if _client is None:
        _client = NowCertsClient()
    return _client


def normalize_insured(raw: dict) -> dict:
    """Normalize a NowCerts insured API response into our Customer fields."""
    return {
        "nowcerts_insured_id": str(raw.get("database_id", raw.get("databaseId", ""))),
        "first_name": raw.get("first_name", raw.get("firstName", "")),
        "last_name": raw.get("last_name", raw.get("lastName", "")),
        "full_name": _build_name(raw),
        "email": raw.get("email", "") or "",
        "phone": raw.get("phone_number", raw.get("phone", "")) or "",
        "mobile_phone": raw.get("cell_phone", raw.get("mobilePhone", "")) or "",
        "address": raw.get("address_line_1", raw.get("address", "")) or "",
        "city": raw.get("city", "") or "",
        "state": raw.get("state", "") or "",
        "zip_code": raw.get("zip_code", raw.get("zipCode", "")) or "",
        "is_prospect": raw.get("type", "").lower() == "prospect" if raw.get("type") else False,
        "is_active": not raw.get("is_deleted", False),
        "agent_name": (raw.get("agents", []) or [None])[0] if raw.get("agents") else raw.get("agentName", ""),
        "tags": raw.get("tags", []) or [],
        "nowcerts_raw": raw,
    }


def normalize_policy(raw: dict, customer_id: int) -> dict:
    """Normalize a NowCerts policy API response into our CustomerPolicy fields."""
    return {
        "customer_id": customer_id,
        "nowcerts_policy_id": str(raw.get("database_id", raw.get("databaseId", raw.get("databaseID", "")))),
        "policy_number": raw.get("policy_number", raw.get("policyNumber", raw.get("number", ""))),
        "carrier": raw.get("carrier_name", raw.get("companyName", raw.get("carrier", ""))),
        "line_of_business": raw.get("line_of_business", raw.get("lineOfBusiness", raw.get("lob", ""))),
        "policy_type": raw.get("business_type", raw.get("policyType", "")),
        "status": raw.get("status", raw.get("policyStatus", "")),
        "effective_date": _parse_date(raw.get("effective_date", raw.get("effectiveDate"))),
        "expiration_date": _parse_date(raw.get("expiration_date", raw.get("expirationDate"))),
        "premium": raw.get("premium", raw.get("totalPremium", 0)),
        "agent_name": _extract_agent(raw),
        "nowcerts_raw": raw,
    }


def _extract_agent(raw: dict) -> str:
    agents = raw.get("agents", [])
    if isinstance(agents, list) and agents:
        if isinstance(agents[0], str):
            return agents[0]
        if isinstance(agents[0], dict):
            return agents[0].get("name", agents[0].get("agentName", ""))
    return raw.get("agentName", raw.get("agent_name", ""))


def _build_name(raw: dict) -> str:
    first = raw.get("first_name", raw.get("firstName", "")) or ""
    last = raw.get("last_name", raw.get("lastName", "")) or ""
    commercial = raw.get("commercial_name", raw.get("commercialName", "")) or ""
    if first and last:
        return f"{first} {last}"
    if commercial:
        return commercial
    return first or last or raw.get("insuredName", "Unknown")


def _parse_date(val):
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    try:
        # NowCerts often returns "/Date(timestamp)/" format
        if "/Date(" in str(val):
            ts = int(str(val).split("(")[1].split(")")[0].split("-")[0].split("+")[0])
            return datetime.fromtimestamp(ts / 1000)
        return datetime.fromisoformat(str(val).replace("Z", "+00:00"))
    except Exception:
        try:
            return datetime.strptime(str(val)[:10], "%Y-%m-%d")
        except Exception:
            return None
