"""Employee welcome email — sent when a new employee is added in Admin.

Delivers the employee's credentials and flags that they must change their
password on first login. BCI-branded HTML template, Mailgun delivery.

Separate from services/welcome_email.py which is for CUSTOMER welcome emails.
"""
import logging
import requests
from app.core.config import settings

logger = logging.getLogger(__name__)

AGENCY_NAME = "Better Choice Insurance Group"
AGENCY_PHONE = "847-908-5665"
AGENCY_EMAIL = "service@betterchoiceins.com"
BCI_NAVY = "#1a2b5f"
BCI_DARK = "#162249"
BCI_CYAN = "#2cb5e8"
BCI_GRADIENT = "linear-gradient(135deg, #1a2b5f 0%, #162249 60%, #0c4a6e 100%)"

# Login URL — matches custom domain used in esign redirect
LOGIN_URL = "https://orbit.betterchoiceins.com/login"


def _role_display(role: str) -> str:
    """Human-readable role for the email body."""
    mapping = {
        "admin": "Admin",
        "manager": "Manager",
        "producer": "Producer",
        "retention_specialist": "Retention Specialist",
    }
    return mapping.get((role or "").lower(), (role or "Team Member").replace("_", " ").title())


def build_employee_welcome_html(
    full_name: str,
    username: str,
    temp_password: str,
    role: str,
) -> str:
    """Build the BCI-branded HTML body for an employee welcome email."""
    role_label = _role_display(role)
    first_name = (full_name or "there").split(" ")[0]

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Welcome to ORBIT</title>
</head>
<body style="margin:0; padding:0; background-color:#f4f6fa; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color:#f4f6fa;">
  <tr>
    <td align="center" style="padding: 32px 16px;">
      <table role="presentation" width="600" cellspacing="0" cellpadding="0" border="0" style="max-width:600px; background-color:#ffffff; border-radius:12px; overflow:hidden; box-shadow: 0 4px 16px rgba(0,0,0,0.06);">

        <!-- Header -->
        <tr>
          <td style="background: {BCI_GRADIENT}; padding: 36px 32px; text-align: center;">
            <div style="color:#ffffff; font-size: 14px; font-weight:600; letter-spacing: 2px; text-transform: uppercase; opacity: 0.85;">
              Better Choice Insurance Group
            </div>
            <div style="color:#ffffff; font-size: 32px; font-weight: 800; margin-top: 8px; letter-spacing: 1px;">
              Welcome to ORBIT
            </div>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding: 36px 36px 24px 36px; color: #1a1a1a; font-size: 15px; line-height: 1.6;">
            <p style="margin:0 0 16px 0; font-size: 18px; font-weight: 600; color:{BCI_NAVY};">
              Hi {first_name},
            </p>
            <p style="margin:0 0 16px 0;">
              Your ORBIT account has been created. ORBIT is our agency's operations platform — it's
              where you'll manage sales, quotes, policies, customers, and everything else that keeps
              the business running.
            </p>
            <p style="margin:0 0 20px 0;">
              Here are your login credentials:
            </p>

            <!-- Credentials box -->
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"
                   style="background-color:#f7faff; border: 1px solid #dbe5f5; border-radius:8px; margin-bottom: 20px;">
              <tr>
                <td style="padding: 20px 24px;">
                  <div style="margin-bottom: 14px;">
                    <div style="color:#64748b; font-size: 12px; font-weight: 600; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 4px;">
                      Username
                    </div>
                    <div style="color:#0f172a; font-size: 18px; font-weight: 700; font-family: 'Courier New', monospace;">
                      {username}
                    </div>
                  </div>
                  <div style="margin-bottom: 14px;">
                    <div style="color:#64748b; font-size: 12px; font-weight: 600; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 4px;">
                      Temporary Password
                    </div>
                    <div style="color:#0f172a; font-size: 18px; font-weight: 700; font-family: 'Courier New', monospace;">
                      {temp_password}
                    </div>
                  </div>
                  <div>
                    <div style="color:#64748b; font-size: 12px; font-weight: 600; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 4px;">
                      Role
                    </div>
                    <div style="color:#0f172a; font-size: 16px; font-weight: 600;">
                      {role_label}
                    </div>
                  </div>
                </td>
              </tr>
            </table>

            <!-- Security note -->
            <div style="background-color:#fff8e6; border-left: 4px solid #f59e0b; padding: 14px 18px; border-radius: 4px; margin-bottom: 24px;">
              <div style="color:#92400e; font-weight:700; font-size: 13px; margin-bottom: 4px;">
                First-Login Security Step
              </div>
              <div style="color:#78350f; font-size: 14px;">
                You'll be asked to set a new password immediately after your first login. The
                temporary password above won't work after that.
              </div>
            </div>

            <!-- CTA button -->
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin: 8px 0 24px 0;">
              <tr>
                <td align="center">
                  <a href="{LOGIN_URL}" style="display: inline-block; background-color:{BCI_NAVY}; color:#ffffff; padding: 14px 36px; border-radius: 8px; font-weight: 700; font-size: 16px; text-decoration: none; letter-spacing: 0.5px;">
                    Log In to ORBIT
                  </a>
                </td>
              </tr>
            </table>

            <p style="margin: 20px 0 0 0; color:#64748b; font-size: 14px;">
              If the button above doesn't work, paste this URL into your browser:<br>
              <a href="{LOGIN_URL}" style="color:{BCI_CYAN}; word-break: break-all;">{LOGIN_URL}</a>
            </p>

            <p style="margin: 24px 0 0 0;">
              Questions? Just reply to this email or call the office at {AGENCY_PHONE}.
            </p>

            <p style="margin: 20px 0 0 0;">
              Welcome to the team,<br>
              <strong>Evan Larson</strong><br>
              <span style="color:#64748b;">Better Choice Insurance Group</span>
            </p>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background-color:#f7faff; padding: 20px 32px; border-top: 1px solid #e5ebf5; text-align: center; color:#64748b; font-size: 12px;">
            <div style="font-weight:600; color:{BCI_NAVY};">{AGENCY_NAME}</div>
            <div style="margin-top: 4px;">300 Cardinal Dr, Suite 220 · Saint Charles, IL 60175</div>
            <div style="margin-top: 4px;">{AGENCY_PHONE} · <a href="mailto:{AGENCY_EMAIL}" style="color:{BCI_CYAN}; text-decoration:none;">{AGENCY_EMAIL}</a></div>
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
</body>
</html>"""


def send_employee_welcome_email(
    to_email: str,
    full_name: str,
    username: str,
    temp_password: str,
    role: str,
) -> dict:
    """Send the BCI-branded employee welcome email via Mailgun.

    Returns {"success": bool, "message_id": str, "error": str}.
    On failure, logs and returns success=False but does NOT raise. The
    calling endpoint should NOT fail the employee creation just because
    the email didn't go out — the user account is still valid.
    """
    if not settings.MAILGUN_API_KEY or not settings.MAILGUN_DOMAIN:
        logger.warning("MAILGUN_API_KEY/DOMAIN not configured — skipping employee welcome email")
        return {"success": False, "error": "Mailgun not configured"}

    if not to_email:
        return {"success": False, "error": "No recipient email"}

    html = build_employee_welcome_html(
        full_name=full_name,
        username=username,
        temp_password=temp_password,
        role=role,
    )

    mail_data = {
        "from": "Better Choice Insurance <service@" + settings.MAILGUN_DOMAIN + ">",
        "to": to_email,
        "subject": "Welcome to ORBIT — Your login credentials",
        "html": html,
        "h:Reply-To": "service@betterchoiceins.com",
        # BCC Evan so he has a record of every employee credential sent
        "bcc": "evan@betterchoiceins.com",
        "o:tag": ["employee-welcome"],
    }

    try:
        resp = requests.post(
            "https://api.mailgun.net/v3/" + settings.MAILGUN_DOMAIN + "/messages",
            auth=("api", settings.MAILGUN_API_KEY),
            data=mail_data,
            timeout=30,
        )
        if resp.status_code == 200:
            msg_id = resp.json().get("id", "")
            logger.info("Employee welcome email sent to %s — msg_id=%s", to_email, msg_id)
            return {"success": True, "message_id": msg_id}
        logger.error("Mailgun error on employee welcome %s: %s", resp.status_code, resp.text[:300])
        return {"success": False, "error": "Mailgun " + str(resp.status_code)}
    except Exception as e:
        logger.error("Failed to send employee welcome email: %s", e)
        return {"success": False, "error": str(e)}
