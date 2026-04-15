"""SMS message templates for ORBIT campaigns.

Pre-written, brandded text message templates for:
- Welcome texts (new customer)
- Requote campaign touches
- Payment reminders
- Renewal alerts
- General follow-ups

All templates use {placeholders} for personalization.
"""


def welcome_text(first_name: str, agent_name: str = "your agent") -> str:
    """Welcome text sent after a new policy bind."""
    return (
        f"Hi {first_name}! 🎉 Welcome to Better Choice Insurance Group. "
        f"We're excited to have you! Your agent {agent_name} is here for anything you need. "
        f"Save our number — you can text or call us anytime at (847) 908-5665."
    )


def requote_touch1(first_name: str, x_date_str: str = "") -> str:
    """First requote campaign touch — friendly intro, X-date approaching."""
    date_note = f" Your policy renews {x_date_str}." if x_date_str else ""
    return (
        f"Hi {first_name}, this is Better Choice Insurance Group. "
        f"We help families save on auto & home insurance by comparing top carriers.{date_note} "
        f"Want to see if we can find you a better rate? Reply YES and we'll get started!"
    )


def requote_touch2(first_name: str) -> str:
    """Second touch — urgency, value prop."""
    return (
        f"Hi {first_name}, just following up! Our clients save an average of $600/year "
        f"when we shop their insurance. It takes 5 minutes and there's no obligation. "
        f"Ready to see your options? Reply YES or call (847) 908-5665."
    )


def requote_touch3(first_name: str) -> str:
    """Third touch — last chance before X-date."""
    return (
        f"Last chance, {first_name}! Your renewal is coming up soon. "
        f"Let us do a quick comparison before you auto-renew. "
        f"Reply YES or call us at (847) 908-5665 — it only takes a few minutes."
    )


def payment_reminder(first_name: str, carrier: str = "", policy_number: str = "") -> str:
    """Non-payment reminder text."""
    policy_ref = f" ({carrier} {policy_number})" if carrier else ""
    return (
        f"Hi {first_name}, this is Better Choice Insurance. "
        f"We wanted to let you know your insurance payment{policy_ref} may be past due. "
        f"Please contact your carrier to make a payment and avoid a lapse in coverage. "
        f"Questions? Call us at (847) 908-5665."
    )


def renewal_reminder(first_name: str, days_until: int = 30) -> str:
    """Upcoming renewal text."""
    return (
        f"Hi {first_name}! Your insurance policy renews in about {days_until} days. "
        f"Want us to shop your renewal to make sure you're getting the best rate? "
        f"Reply YES or call (847) 908-5665."
    )


def review_request(first_name: str) -> str:
    """Post-sale review request (after 30+ days)."""
    return (
        f"Hi {first_name}! It's been a few weeks since we set up your insurance. "
        f"How has your experience been? If you're happy with our service, "
        f"we'd love a quick Google review — it really helps our small business. "
        f"Reply REVIEW and we'll send you the link!"
    )


def referral_ask(first_name: str) -> str:
    """Referral request text."""
    return (
        f"Hi {first_name}! Know anyone who could use better insurance rates? "
        f"We'd love to help your friends & family save. "
        f"Just reply with their name and number and we'll take great care of them!"
    )


def cross_sell_life(first_name: str) -> str:
    """Life insurance cross-sell text."""
    return (
        f"Hi {first_name}, this is Better Choice Insurance. "
        f"Did you know we can also help protect your family with affordable life insurance? "
        f"Most of our clients qualify for coverage starting around $25/month. "
        f"Want a free quote? Reply YES or call (847) 908-5665."
    )


def appointment_confirmation(first_name: str, date_str: str, agent_name: str = "") -> str:
    """Appointment/callback confirmation."""
    agent_note = f" with {agent_name}" if agent_name else ""
    return (
        f"Hi {first_name}! This confirms your appointment{agent_note} "
        f"on {date_str}. We'll call you at your scheduled time. "
        f"Need to reschedule? Reply to this text or call (847) 908-5665."
    )


def generic_followup(first_name: str, message: str) -> str:
    """Generic branded follow-up wrapper."""
    return (
        f"Hi {first_name}, this is Better Choice Insurance. "
        f"{message} "
        f"Questions? Text us back or call (847) 908-5665."
    )


# ── Template registry for campaign system ───────────────────────────

TEMPLATES = {
    "welcome": welcome_text,
    "requote_touch1": requote_touch1,
    "requote_touch2": requote_touch2,
    "requote_touch3": requote_touch3,
    "payment_reminder": payment_reminder,
    "renewal_reminder": renewal_reminder,
    "review_request": review_request,
    "referral_ask": referral_ask,
    "cross_sell_life": cross_sell_life,
    "appointment_confirmation": appointment_confirmation,
    "generic_followup": generic_followup,
}


def get_template(template_name: str, **kwargs) -> str:
    """Get a rendered template by name. Returns empty string if not found."""
    fn = TEMPLATES.get(template_name)
    if fn:
        return fn(**kwargs)
    return ""
