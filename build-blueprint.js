const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  HeadingLevel, AlignmentType, BorderStyle, WidthType, ShadingType,
  LevelFormat, PageBreak, TabStopType
} = require("docx");

// ─── Color palette ───
const NAVY = "1B2A4A";
const CYAN = "0EA5E9";
const GREEN = "10B981";
const AMBER = "F59E0B";
const RED = "EF4444";
const SLATE = "64748B";
const LIGHT_BG = "F0F7FF";
const WHITE = "FFFFFF";

// ─── Helpers ───
const spacer = (pts = 120) => new Paragraph({ spacing: { before: pts, after: pts } });

const sectionTitle = (text) => new Paragraph({
  spacing: { before: 360, after: 200 },
  children: [new TextRun({ text, bold: true, size: 36, color: NAVY, font: "Arial" })],
});

const subTitle = (text) => new Paragraph({
  spacing: { before: 280, after: 160 },
  children: [new TextRun({ text, bold: true, size: 28, color: CYAN, font: "Arial" })],
});

const subSubTitle = (text) => new Paragraph({
  spacing: { before: 200, after: 120 },
  children: [new TextRun({ text, bold: true, size: 24, color: NAVY, font: "Arial" })],
});

const bodyText = (text) => new Paragraph({
  spacing: { before: 60, after: 60 },
  children: [new TextRun({ text, size: 21, color: "334155", font: "Arial" })],
});

const boldBody = (label, text) => new Paragraph({
  spacing: { before: 60, after: 60 },
  children: [
    new TextRun({ text: label, bold: true, size: 21, color: NAVY, font: "Arial" }),
    new TextRun({ text, size: 21, color: "334155", font: "Arial" }),
  ],
});

const stepItem = (num, text) => new Paragraph({
  spacing: { before: 80, after: 80 },
  indent: { left: 360 },
  children: [
    new TextRun({ text: `Step ${num}: `, bold: true, size: 21, color: CYAN, font: "Arial" }),
    new TextRun({ text, size: 21, color: "334155", font: "Arial" }),
  ],
});

const bulletItem = (text, level = 0) => new Paragraph({
  numbering: { reference: "bullets", level },
  spacing: { before: 40, after: 40 },
  children: [new TextRun({ text, size: 21, color: "334155", font: "Arial" })],
});

const codeBlock = (text) => new Paragraph({
  spacing: { before: 80, after: 80 },
  indent: { left: 360 },
  shading: { fill: "F1F5F9", type: ShadingType.CLEAR },
  children: [new TextRun({ text, size: 18, color: "1E293B", font: "Courier New" })],
});

const divider = () => new Paragraph({
  spacing: { before: 200, after: 200 },
  border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: CYAN, space: 1 } },
});

const border = { style: BorderStyle.SINGLE, size: 1, color: "CBD5E1" };
const borders = { top: border, bottom: border, left: border, right: border };
const cellMargins = { top: 60, bottom: 60, left: 100, right: 100 };

const headerCell = (text, width) => new TableCell({
  borders,
  width: { size: width, type: WidthType.DXA },
  shading: { fill: NAVY, type: ShadingType.CLEAR },
  margins: cellMargins,
  children: [new Paragraph({ children: [new TextRun({ text, bold: true, size: 18, color: WHITE, font: "Arial" })] })],
});

const cell = (text, width, fill) => new TableCell({
  borders,
  width: { size: width, type: WidthType.DXA },
  shading: fill ? { fill, type: ShadingType.CLEAR } : undefined,
  margins: cellMargins,
  children: [new Paragraph({ children: [new TextRun({ text, size: 18, color: "334155", font: "Arial" })] })],
});

// ═══════════════════════════════════════════════════════════════
// DOCUMENT CONTENT
// ═══════════════════════════════════════════════════════════════

const children = [];

// ─── COVER PAGE ───
children.push(
  spacer(2400),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 200 },
    children: [new TextRun({ text: "BETTER CHOICE INSURANCE GROUP", bold: true, size: 44, color: NAVY, font: "Arial" })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 120 },
    children: [new TextRun({ text: "Automation & AI Blueprint", size: 36, color: CYAN, font: "Arial" })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 600 },
    children: [new TextRun({ text: "GHL Workflows | BCI CRM Integrations | Email Campaigns | AI Voice Calls", size: 22, color: SLATE, font: "Arial" })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "February 2026", size: 24, color: SLATE, font: "Arial" })],
  }),
  new Paragraph({ children: [new PageBreak()] }),
);

// ─── TABLE OF CONTENTS ───
children.push(
  sectionTitle("Table of Contents"),
  spacer(60),
  bodyText("1. Non-Pay AI Calling Workflow (GHL)"),
  bodyText("2. Renewal Workflow with Rate-Based Branching (GHL)"),
  bodyText("3. BCI CRM: Pre-Renewal & Onboarding Email/SMS Campaigns"),
  bodyText("4. Cross-Sell Life Insurance Campaign (GHL)"),
  bodyText("5. Sales Producer Automation: Quote-to-Close Pipeline"),
  bodyText("6. Webhook Integration Architecture"),
  bodyText("7. Implementation Timeline"),
  new Paragraph({ children: [new PageBreak()] }),
);

// ═══════════════════════════════════════════════════════════════
// 1. NON-PAY AI CALLING
// ═══════════════════════════════════════════════════════════════
children.push(
  sectionTitle("1. Non-Pay AI Calling Workflow"),
  bodyText("Automated outbound AI voice calls to customers with past-due payments, triggered from BCI CRM non-pay email pipeline."),
  divider(),

  subTitle("1A. BCI CRM Side (I Build This)"),
  bodyText("After a non-pay email is successfully sent, the backend fires a webhook to GHL with all customer and policy data."),
  spacer(60),

  subSubTitle("Webhook Payload"),
  codeBlock("POST https://services.leadconnectorhq.com/hooks/{YOUR_WEBHOOK_ID}"),
  codeBlock("Content-Type: application/json"),
  codeBlock("{"),
  codeBlock('  "first_name": "Rosa",'),
  codeBlock('  "last_name": "Ayala",'),
  codeBlock('  "email": "rosa.ayala1331@gmail.com",'),
  codeBlock('  "phone": "+16145551234",'),
  codeBlock('  "policy_number": "HM 6605796",'),
  codeBlock('  "carrier": "Grange",'),
  codeBlock('  "amount_due": "$1,494.00",'),
  codeBlock('  "due_date": "02/28/2026",'),
  codeBlock('  "carrier_phone": "(800) 425-1100",'),
  codeBlock('  "event_type": "nonpay_email_sent",'),
  codeBlock('  "sent_at": "2026-02-21T14:30:00Z"'),
  codeBlock("}"),
  spacer(60),

  subSubTitle("Implementation"),
  bulletItem("Fires automatically after successful Mailgun email send + NowCerts note"),
  bulletItem("Only fires if customer has a phone number on file"),
  bulletItem("Respects existing 1x/week rate limit per policy"),
  bulletItem("Logs GHL webhook response in non-pay history"),
  spacer(60),

  subTitle("1B. GHL Workflow (Build in GHL UI)"),
  subSubTitle("Trigger"),
  boldBody("Type: ", "Inbound Webhook"),
  bodyText("Copy the generated webhook URL and provide it to me. I will configure the BCI CRM to POST to this URL."),
  spacer(60),

  subSubTitle("Workflow Steps"),
  stepItem(1, "Inbound Webhook Trigger receives payload from BCI CRM"),
  stepItem(2, "Create/Update Contact - Map webhook fields to GHL contact: first_name, last_name, email, phone. Add tag: 'nonpay-notice'"),
  stepItem(3, "Update Custom Fields - Map: policy_number, carrier, amount_due, due_date, carrier_phone to GHL custom fields (create these first)"),
  stepItem(4, "Wait 1 Business Day - Gives customer time to act on email first"),
  stepItem(5, "If/Else: Check if contact has tag 'payment-confirmed' (skip call if already paid)"),
  stepItem(6, "Voice AI Outbound Call - Select your Non-Pay AI Agent, assign calling number"),
  stepItem(7, "If/Else Branch on Call Outcome:"),
  bulletItem("Connected: Add tag 'nonpay-called-connected', send webhook back to BCI CRM with result"),
  bulletItem("Voicemail: Add tag 'nonpay-called-voicemail', wait 2 days, retry call (max 2 retries)"),
  bulletItem("No Answer: Add tag 'nonpay-called-noanswer', wait 1 day, retry"),
  stepItem(8, "After final attempt: Send webhook to BCI CRM with call outcome for NowCerts note"),
  spacer(60),

  subSubTitle("Voice AI Agent Configuration"),
  boldBody("Agent Name: ", "BCI Non-Pay Reminder"),
  boldBody("Scenario: ", "Outbound"),
  boldBody("Voice: ", "Professional female or male (your preference)"),
  boldBody("Initial Greeting: ", "Standard"),
  spacer(60),
  boldBody("Agent Prompt:", ""),
  bodyText("You are a friendly representative from Better Choice Insurance Group. You are calling {{contact.first_name}} {{contact.last_name}} about a past-due payment on their {{custom.carrier}} insurance policy."),
  spacer(40),
  bodyText("Key information:"),
  bulletItem("Policy number: {{custom.policy_number}}"),
  bulletItem("Amount due: {{custom.amount_due}}"),
  bulletItem("Due date: {{custom.due_date}}"),
  bulletItem("Carrier payment phone: {{custom.carrier_phone}}"),
  spacer(40),
  bodyText("Your script flow:"),
  bulletItem("Introduce yourself: 'Hi, this is [Agent Name] calling from Better Choice Insurance Group.'"),
  bulletItem("State purpose: 'I am calling about your [carrier] insurance policy. We received a notice that a payment of [amount] was due on [date].'"),
  bulletItem("Provide help: 'You can make a payment by calling [carrier] directly at [carrier_phone], or I can transfer you to our service team if you have any questions.'"),
  bulletItem("If they want to transfer: Transfer to your office number"),
  bulletItem("If they say they already paid: 'Great! It may take a few days to process. If you have any issues, call us at (your office number).'"),
  bulletItem("If voicemail: 'Hi, this is Better Choice Insurance Group calling about your [carrier] policy. We wanted to let you know a payment of [amount] is due. Please call us or your carrier at [carrier_phone]. Thank you!'"),
  spacer(40),
  bodyText("Rules: Be polite and brief. Do not discuss coverage details. Do not negotiate payment amounts. Do not threaten cancellation. If the customer is upset, offer to transfer to a live agent immediately."),
  spacer(60),

  subSubTitle("GHL Custom Fields to Create"),
  new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [2800, 2000, 4560],
    rows: [
      new TableRow({ children: [headerCell("Field Name", 2800), headerCell("Type", 2000), headerCell("Purpose", 4560)] }),
      new TableRow({ children: [cell("policy_number", 2800), cell("Text", 2000), cell("Customer policy number", 4560)] }),
      new TableRow({ children: [cell("carrier", 2800, LIGHT_BG), cell("Text", 2000, LIGHT_BG), cell("Insurance carrier name", 4560, LIGHT_BG)] }),
      new TableRow({ children: [cell("amount_due", 2800), cell("Text", 2000), cell("Past-due amount", 4560)] }),
      new TableRow({ children: [cell("due_date", 2800, LIGHT_BG), cell("Text", 2000, LIGHT_BG), cell("Payment due date", 4560, LIGHT_BG)] }),
      new TableRow({ children: [cell("carrier_phone", 2800), cell("Text", 2000), cell("Carrier payment number", 4560)] }),
      new TableRow({ children: [cell("event_type", 2800, LIGHT_BG), cell("Text", 2000, LIGHT_BG), cell("Tracks which BCI event triggered this", 4560, LIGHT_BG)] }),
    ],
  }),

  new Paragraph({ children: [new PageBreak()] }),
);

// ═══════════════════════════════════════════════════════════════
// 2. RENEWAL WORKFLOW
// ═══════════════════════════════════════════════════════════════
children.push(
  sectionTitle("2. Renewal Workflow with Rate-Based Branching"),
  bodyText("Smart renewal outreach that adapts messaging based on rate increase percentage, with de-duplication logic for customers with multiple policies renewing within 30 days."),
  divider(),

  subTitle("2A. BCI CRM Side (I Build This)"),
  subSubTitle("Renewal Detection Engine"),
  bodyText("New backend service that runs daily, scanning NowCerts for policies expiring in the next 90/60/30 days."),
  spacer(60),

  boldBody("Data Gathered Per Policy:", ""),
  bulletItem("Policy number, carrier, current premium, renewal premium (if available)"),
  bulletItem("Rate change percentage: (renewal_premium - current_premium) / current_premium * 100"),
  bulletItem("Customer name, email, phone, mailing address"),
  bulletItem("All policies for this customer with upcoming renewals"),
  spacer(60),

  subSubTitle("Multi-Policy De-Duplication Logic"),
  bodyText("When a customer has multiple policies renewing within 30 days of each other:"),
  bulletItem("Group all renewals for the same customer"),
  bulletItem("Calculate rate change % for each policy"),
  bulletItem("Select the HIGHEST rate increase % as the trigger policy"),
  bulletItem("Send ONE outreach covering all renewing policies"),
  bulletItem("Webhook payload includes an array of all renewing policies"),
  spacer(60),

  subSubTitle("Webhook Payload"),
  codeBlock("POST https://services.leadconnectorhq.com/hooks/{YOUR_WEBHOOK_ID}"),
  codeBlock("{"),
  codeBlock('  "first_name": "John",'),
  codeBlock('  "last_name": "Smith",'),
  codeBlock('  "email": "john@example.com",'),
  codeBlock('  "phone": "+16145551234",'),
  codeBlock('  "event_type": "renewal_approaching",'),
  codeBlock('  "days_until_renewal": 60,'),
  codeBlock('  "highest_rate_change_pct": 14.5,'),
  codeBlock('  "rate_category": "high_increase",'),
  codeBlock('  "policies": ['),
  codeBlock('    {'),
  codeBlock('      "policy_number": "HM 6605796",'),
  codeBlock('      "carrier": "Grange",'),
  codeBlock('      "current_premium": "$1,200",'),
  codeBlock('      "renewal_premium": "$1,374",'),
  codeBlock('      "rate_change_pct": 14.5,'),
  codeBlock('      "expiration_date": "04/15/2026"'),
  codeBlock("    },"),
  codeBlock("    {"),
  codeBlock('      "policy_number": "PA 8812345",'),
  codeBlock('      "carrier": "Grange",'),
  codeBlock('      "current_premium": "$890",'),
  codeBlock('      "renewal_premium": "$920",'),
  codeBlock('      "rate_change_pct": 3.4,'),
  codeBlock('      "expiration_date": "04/20/2026"'),
  codeBlock("    }"),
  codeBlock("  ]"),
  codeBlock("}"),
  spacer(60),

  subTitle("2B. GHL Renewal Workflow"),
  subSubTitle("Trigger"),
  boldBody("Type: ", "Inbound Webhook (from BCI CRM renewal scanner)"),
  spacer(60),

  subSubTitle("Workflow Steps"),
  stepItem(1, "Inbound Webhook Trigger"),
  stepItem(2, "Create/Update Contact with renewal data"),
  stepItem(3, "Update Custom Fields: highest_rate_change_pct, rate_category, renewal_policies_summary, days_until_renewal"),
  stepItem(4, "If/Else: rate_category"),
  spacer(40),

  boldBody("Branch A: High Increase (10%+ rate change)", ""),
  bodyText("These customers are at risk of shopping. Proactive, consultative approach."),
  bulletItem("Immediate: Send 'Rate Review' email (see template below)"),
  bulletItem("Wait 2 days"),
  bulletItem("AI Outbound Call with retention script"),
  bulletItem("Wait 3 days: If no response, send SMS: 'Hi {{first_name}}, we noticed a rate change on your policy and want to help. Can we schedule a quick review? Reply YES or call us.'"),
  bulletItem("Wait 5 days: If still no engagement, assign to producer for personal follow-up task"),
  spacer(40),

  boldBody("Branch B: Low/No Increase (under 10% rate change)", ""),
  bodyText("Straightforward renewal reminder. No urgency needed."),
  bulletItem("Send 'Renewal Reminder' email at 60 days"),
  bulletItem("Send SMS reminder at 30 days: 'Hi {{first_name}}, your {{carrier}} policy renews on {{expiration_date}}. No action needed if you want to continue. Questions? Call us!'"),
  bulletItem("Send final email reminder at 14 days"),
  spacer(60),

  subSubTitle("Voice AI Agent: Renewal - High Rate Increase"),
  boldBody("Agent Name: ", "BCI Renewal Review"),
  boldBody("Scenario: ", "Outbound"),
  spacer(40),
  boldBody("Agent Prompt:", ""),
  bodyText("You are a friendly representative from Better Choice Insurance Group. You are calling {{contact.first_name}} about an upcoming policy renewal with a rate change."),
  spacer(40),
  bodyText("Script flow:"),
  bulletItem("'Hi, this is [Name] from Better Choice Insurance. I am calling because we noticed your {{custom.carrier}} policy is coming up for renewal, and there is a rate adjustment we wanted to discuss with you.'"),
  bulletItem("'We want to make sure you are getting the best rate possible. Would you like to schedule a quick review with one of our agents? It only takes about 10 minutes and we can shop other carriers for you.'"),
  bulletItem("If YES: 'Great! Let me transfer you to our team.' (Transfer to office)"),
  bulletItem("If NOT NOW: 'No problem! We will follow up by email with some options. You can always call us when you are ready.'"),
  bulletItem("If voicemail: 'Hi, this is Better Choice Insurance calling about your upcoming renewal. We noticed a rate change and want to help you explore your options. Please call us at (office number) or reply to our email. Thank you!'"),
  spacer(40),
  bodyText("Rules: Never quote specific rate amounts on the phone. Focus on offering a review, not alarming the customer. Position as proactive service, not a sales pitch."),
  spacer(60),

  subSubTitle("Email Templates"),
  boldBody("High Increase Email Subject: ", "Your {{carrier}} Policy Rate Review - Let Us Help"),
  bodyText("Body: Address rate change honestly, offer to shop alternatives, include click-to-call and click-to-schedule links. Mention all renewing policies if multiple."),
  spacer(40),
  boldBody("Low Increase Email Subject: ", "Your {{carrier}} Policy Renews on {{expiration_date}}"),
  bodyText("Body: Simple reminder, no action needed, contact info if questions. Friendly and brief."),

  new Paragraph({ children: [new PageBreak()] }),
);

// ═══════════════════════════════════════════════════════════════
// 3. BCI CRM: PRE-RENEWAL & ONBOARDING
// ═══════════════════════════════════════════════════════════════
children.push(
  sectionTitle("3. BCI CRM: Pre-Renewal & Onboarding Campaigns"),
  bodyText("Email and SMS campaigns built directly into BCI CRM (not GHL) for internal operational flows."),
  divider(),

  subTitle("3A. Pre-Renewal Email Campaign (BCI CRM)"),
  bodyText("Automated sequence triggered by the renewal scanner. Carrier-branded emails sent directly from your BCI CRM via Mailgun."),
  spacer(60),

  subSubTitle("90-Day Sequence"),
  new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [1200, 1600, 3000, 3560],
    rows: [
      new TableRow({ children: [headerCell("Day", 1200), headerCell("Channel", 1600), headerCell("Subject / Content", 3000), headerCell("Purpose", 3560)] }),
      new TableRow({ children: [cell("Day 90", 1200), cell("Email", 1600), cell("Your policy renewal is approaching", 3000), cell("Early heads-up, offer review appointment", 3560)] }),
      new TableRow({ children: [cell("Day 60", 1200, LIGHT_BG), cell("Email", 1600, LIGHT_BG), cell("Renewal update + rate info", 3000, LIGHT_BG), cell("Share rate change if known, offer alternatives", 3560, LIGHT_BG)] }),
      new TableRow({ children: [cell("Day 45", 1200), cell("SMS", 1600), cell("Quick check-in about renewal", 3000), cell("Text reminder for customers who did not open emails", 3560)] }),
      new TableRow({ children: [cell("Day 30", 1200, LIGHT_BG), cell("Email", 1600, LIGHT_BG), cell("30 days until renewal - action needed?", 3000, LIGHT_BG), cell("Urgency nudge, final review offer", 3560, LIGHT_BG)] }),
      new TableRow({ children: [cell("Day 14", 1200), cell("Email + SMS", 1600), cell("Your policy renews in 2 weeks", 3000), cell("Final reminder with carrier payment info", 3560)] }),
      new TableRow({ children: [cell("Day 7", 1200, LIGHT_BG), cell("SMS", 1600, LIGHT_BG), cell("Renewal in 1 week", 3000, LIGHT_BG), cell("Last touch before renewal date", 3560, LIGHT_BG)] }),
    ],
  }),
  spacer(60),

  bodyText("All emails use existing carrier-branded templates (same system as welcome emails). NowCerts note added for each touchpoint."),
  spacer(60),

  subTitle("3B. New Customer Onboarding Campaign (BCI CRM)"),
  bodyText("Triggered after welcome email is sent from the sales review page. Multi-touch sequence to set expectations and drive engagement."),
  spacer(60),

  subSubTitle("Onboarding Sequence"),
  new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [1200, 1600, 3000, 3560],
    rows: [
      new TableRow({ children: [headerCell("Day", 1200), headerCell("Channel", 1600), headerCell("Subject / Content", 3000), headerCell("Purpose", 3560)] }),
      new TableRow({ children: [cell("Day 0", 1200), cell("Email", 1600), cell("Welcome email (existing)", 3000), cell("Policy docs, agent intro, carrier info", 3560)] }),
      new TableRow({ children: [cell("Day 1", 1200, LIGHT_BG), cell("SMS", 1600, LIGHT_BG), cell("Welcome! Your new policy is active", 3000, LIGHT_BG), cell("Quick confirmation + office contact info", 3560, LIGHT_BG)] }),
      new TableRow({ children: [cell("Day 3", 1200), cell("Email", 1600), cell("3 things to know about your new policy", 3000), cell("Set expectations: ID cards, billing, claims process", 3560)] }),
      new TableRow({ children: [cell("Day 7", 1200, LIGHT_BG), cell("Email", 1600, LIGHT_BG), cell("Have questions? We are here to help", 3000, LIGHT_BG), cell("Reinforce availability, link to FAQ or portal", 3560, LIGHT_BG)] }),
      new TableRow({ children: [cell("Day 14", 1200), cell("SMS", 1600), cell("Quick check-in on your new policy", 3000), cell("Ask if everything is good, open door for questions", 3560)] }),
      new TableRow({ children: [cell("Day 30", 1200, LIGHT_BG), cell("Email", 1600, LIGHT_BG), cell("You are covered! + referral ask", 3000, LIGHT_BG), cell("Satisfaction check + referral incentive", 3560, LIGHT_BG)] }),
      new TableRow({ children: [cell("Day 60", 1200), cell("Email", 1600), cell("Did you know? Bundling saves money", 3000), cell("Cross-sell intro (home, auto, umbrella, life)", 3560)] }),
      new TableRow({ children: [cell("Day 90", 1200, LIGHT_BG), cell("Email", 1600, LIGHT_BG), cell("Google Review request", 3000, LIGHT_BG), cell("Request review with direct link", 3560, LIGHT_BG)] }),
    ],
  }),
  spacer(60),

  bodyText("SMS sent via Mailgun SMS or GHL (your preference). Each touchpoint logged in NowCerts as a note. Sequence pauses if customer opens a support ticket or has a claim."),

  new Paragraph({ children: [new PageBreak()] }),
);

// ═══════════════════════════════════════════════════════════════
// 4. CROSS-SELL LIFE INSURANCE
// ═══════════════════════════════════════════════════════════════
children.push(
  sectionTitle("4. Cross-Sell Life Insurance Campaign"),
  bodyText("Targeted campaign to sell life insurance to existing P&C customers who do not currently have a life policy."),
  divider(),

  subTitle("4A. BCI CRM: Audience Selection"),
  bodyText("Backend query identifies cross-sell candidates:"),
  bulletItem("Active customer with at least one P&C policy (auto, home, renters)"),
  bulletItem("No existing life insurance policy in NowCerts"),
  bulletItem("Has email and/or phone on file"),
  bulletItem("Not currently in a non-pay or cancellation workflow"),
  bulletItem("Has not opted out of marketing"),
  spacer(60),
  bodyText("BCI CRM pushes qualified contacts to GHL via webhook with tag 'life-cross-sell-candidate' and relevant data (age if known, policy types, family status)."),
  spacer(60),

  subTitle("4B. GHL Life Insurance Campaign Workflow"),
  subSubTitle("Trigger"),
  boldBody("Type: ", "Inbound Webhook OR Tag Added: 'life-cross-sell-candidate'"),
  spacer(60),

  subSubTitle("Campaign Sequence"),
  stepItem(1, "Email 1 - Educational: 'Why life insurance matters for homeowners' - Not salesy, informational. Links to a simple quote request form."),
  stepItem(2, "Wait 4 days"),
  stepItem(3, "If/Else: Did they open Email 1?"),
  bodyText("   YES branch:"),
  bulletItem("Email 2 - Specific: 'Life insurance for as little as $XX/month' with quick-quote CTA", 1),
  bulletItem("Wait 3 days", 1),
  bulletItem("AI Voice Call with life insurance script (see below)", 1),
  bodyText("   NO branch:"),
  bulletItem("SMS: 'Hi {{first_name}}, did you know life insurance for homeowners can be surprisingly affordable? Reply INFO for a free quote.'", 1),
  bulletItem("Wait 5 days", 1),
  bulletItem("Email 2 - Re-engage with different subject line", 1),
  stepItem(4, "Wait 7 days after last touch"),
  stepItem(5, "Email 3 - Urgency/testimonial: Customer story or limited-time offer"),
  stepItem(6, "Wait 5 days"),
  stepItem(7, "Final AI Voice Call (if no conversion)"),
  stepItem(8, "If no conversion after full sequence: Add tag 'life-cross-sell-completed', remove from workflow. Re-enter eligible after 6 months."),
  spacer(60),

  subSubTitle("Voice AI Agent: Life Insurance Cross-Sell"),
  boldBody("Agent Name: ", "BCI Life Insurance Outreach"),
  boldBody("Scenario: ", "Outbound"),
  spacer(40),
  boldBody("Agent Prompt:", ""),
  bodyText("You are a friendly representative from Better Choice Insurance Group. You are calling {{contact.first_name}} because they are an existing customer and you want to let them know about life insurance options."),
  spacer(40),
  bodyText("Script flow:"),
  bulletItem("'Hi, this is [Name] from Better Choice Insurance. I hope I am not catching you at a bad time. I am reaching out because as your insurance agency, we like to make sure our customers have complete coverage.'"),
  bulletItem("'I noticed you have your [auto/home] insurance with us, and I wanted to let you know we can also help with life insurance. A lot of our customers are surprised at how affordable it can be.'"),
  bulletItem("'Would you be open to a quick 5-minute conversation with one of our agents about your options? No pressure at all.'"),
  bulletItem("If YES: Transfer to office or schedule callback"),
  bulletItem("If NOT INTERESTED: 'Totally understand! If you ever want to explore it, we are here. Have a great day!'"),
  bulletItem("If voicemail: Leave brief message about life insurance availability, no hard sell"),
  spacer(40),
  bodyText("Rules: Never pressure. This is relationship-building. If they say no, respect it immediately. Never quote rates - only licensed agents can do that."),

  new Paragraph({ children: [new PageBreak()] }),
);

// ═══════════════════════════════════════════════════════════════
// 5. SALES PRODUCER AUTOMATION
// ═══════════════════════════════════════════════════════════════
children.push(
  sectionTitle("5. Sales Producer Automation: Quote-to-Close Pipeline"),
  bodyText("End-to-end automation from initial quote through sale or remarket. This is the biggest build and combines BCI CRM features with GHL workflows."),
  divider(),

  subTitle("5A. New Quote Flow (BCI CRM)"),
  subSubTitle("Quote Entry & PDF Upload"),
  bodyText("New 'Quotes' section in BCI CRM with the following features:"),
  bulletItem("Producer enters prospect details: name, email, phone, address, policy type (auto, home, renters, umbrella, life)"),
  bulletItem("Drag-and-drop zone for quote PDF uploads (one or multiple carrier quotes)"),
  bulletItem("System detects carrier from PDF filename or content (Grange, Travelers, Progressive, Safeco, etc.)"),
  bulletItem("Each quote tagged with: carrier, premium amount, effective date, quote date"),
  spacer(60),

  subSubTitle("Prospect Profile Creation in NowCerts"),
  bodyText("On quote entry, BCI CRM automatically:"),
  bulletItem("Creates a Prospect record in NowCerts via API (InsertInsuredPerson with is_prospect=true)"),
  bulletItem("Attaches quote details as a note"),
  bulletItem("Tags the prospect with 'Quoted - [Carrier]' and 'Quote - [Policy Type]'"),
  bulletItem("Links prospect to the producing agent"),
  spacer(60),

  subSubTitle("Carrier-Specific Quote Email"),
  bodyText("Producer clicks 'Send Quote' and the system generates a carrier-branded email:"),
  bulletItem("Uses carrier-specific email template (same design system as welcome emails - 18 carriers)"),
  bulletItem("Highlights the quoted premium amount prominently"),
  bulletItem("Attaches the quote PDF(s)"),
  bulletItem("Includes: carrier logo, agent name/photo, office contact info"),
  bulletItem("CTA button: 'Ready to bind? Click here or call us'"),
  bulletItem("Sent from: quotes@mg.betterchoiceins.com"),
  bulletItem("Reply-To: producing agent's email (or service@)"),
  spacer(60),

  boldBody("Email Subject: ", "Your {{carrier}} {{policy_type}} Insurance Quote - {{premium}}/{{term}}"),
  spacer(60),

  subTitle("5B. Follow-Up Automation"),
  subSubTitle("3-Day Check: Quote Not Converted"),
  bodyText("If the prospect is not uploaded as a sale within 3 days of the quote being sent:"),
  spacer(40),
  stepItem(1, "BCI CRM fires webhook to GHL: event_type = 'quote_followup_3day'"),
  stepItem(2, "GHL sends follow-up email: 'Hi {{first_name}}, just checking in on the {{carrier}} quote we sent. Any questions?'"),
  stepItem(3, "GHL sends SMS: 'Hi {{first_name}}, this is {{agent_name}} from Better Choice. Wanted to follow up on your insurance quote. Reply or call us!'"),
  stepItem(4, "GHL AI Voice Call with quote follow-up script"),
  stepItem(5, "Notify producer via internal alert: 'Quote for [prospect] has not converted in 3 days'"),
  spacer(60),

  subSubTitle("7-Day Check: Still No Conversion"),
  stepItem(1, "Second follow-up email: Different angle - highlight savings, coverage benefits, limited-time offer"),
  stepItem(2, "Producer gets escalation notification"),
  spacer(60),

  subSubTitle("14-Day Check: Final Follow-Up"),
  stepItem(1, "Final email: 'Your quote expires soon - lock in your rate'"),
  stepItem(2, "AI Call: Last check-in attempt"),
  stepItem(3, "If no response: Move prospect to 'Remarket Pipeline'"),
  spacer(60),

  subTitle("5C. 90-Day Remarket Campaign"),
  bodyText("If a prospect is not converted within 90 days, they enter a long-term nurture/remarket sequence that continues until they buy or opt out."),
  spacer(60),

  subSubTitle("Remarket Sequence (GHL Workflow)"),
  boldBody("Trigger: ", "Tag added: 'remarket-pipeline' (set by BCI CRM at day 90)"),
  spacer(40),
  new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [1400, 1400, 3000, 3560],
    rows: [
      new TableRow({ children: [headerCell("Timing", 1400), headerCell("Channel", 1400), headerCell("Content", 3000), headerCell("Goal", 3560)] }),
      new TableRow({ children: [cell("Monthly", 1400), cell("Email", 1400), cell("Insurance tips, seasonal reminders", 3000), cell("Stay top of mind without being pushy", 3560)] }),
      new TableRow({ children: [cell("Month 3", 1400, LIGHT_BG), cell("Email + SMS", 1400, LIGHT_BG), cell("'Rates have changed - want a new quote?'", 3000, LIGHT_BG), cell("Re-engage with fresh pricing", 3560, LIGHT_BG)] }),
      new TableRow({ children: [cell("Month 6", 1400), cell("AI Call", 1400), cell("Check in, offer re-quote", 3000), cell("Personal touch via voice", 3560)] }),
      new TableRow({ children: [cell("Month 9", 1400, LIGHT_BG), cell("Email", 1400, LIGHT_BG), cell("Annual rate comparison offer", 3000, LIGHT_BG), cell("Align with typical renewal cycles", 3560, LIGHT_BG)] }),
      new TableRow({ children: [cell("Month 12", 1400), cell("AI Call + Email", 1400), cell("Anniversary re-quote offer", 3000), cell("Full-circle outreach, final push", 3560)] }),
    ],
  }),
  spacer(60),

  bodyText("Exit conditions:"),
  bulletItem("Prospect converts to sale (tag removed, enters onboarding)"),
  bulletItem("Prospect opts out (tag 'opted-out-marketing')"),
  bulletItem("Prospect explicitly says not interested on AI call (tag 'not-interested')"),
  bulletItem("12-month cycle completes with no engagement (archive)"),
  spacer(60),

  subSubTitle("Voice AI Agent: Quote Follow-Up"),
  boldBody("Agent Name: ", "BCI Quote Follow-Up"),
  boldBody("Agent Prompt:", ""),
  bodyText("You are a friendly representative from Better Choice Insurance Group following up on an insurance quote."),
  bulletItem("'Hi, this is [Name] from Better Choice Insurance. I am calling to follow up on the {{custom.policy_type}} insurance quote we sent you recently for {{custom.carrier}}.'"),
  bulletItem("'Did you get a chance to review it? I would be happy to answer any questions or help you get started.'"),
  bulletItem("If interested: Transfer to producing agent or schedule callback"),
  bulletItem("If need more time: 'No rush at all! We will keep your quote on file. Feel free to call us anytime.'"),
  bulletItem("If went with another company: 'Totally understand! We are always here if you need us in the future.' (Tag: 'lost-to-competitor')"),

  new Paragraph({ children: [new PageBreak()] }),
);

// ═══════════════════════════════════════════════════════════════
// 6. WEBHOOK ARCHITECTURE
// ═══════════════════════════════════════════════════════════════
children.push(
  sectionTitle("6. Webhook Integration Architecture"),
  bodyText("All communication between BCI CRM and GoHighLevel flows through webhooks. Here is the complete map of events."),
  divider(),

  subSubTitle("BCI CRM to GHL (Outbound Webhooks)"),
  new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [2600, 2200, 2200, 2360],
    rows: [
      new TableRow({ children: [headerCell("Event", 2600), headerCell("Trigger", 2200), headerCell("GHL Action", 2200), headerCell("Tags", 2360)] }),
      new TableRow({ children: [cell("nonpay_email_sent", 2600), cell("Non-pay email sent", 2200), cell("AI call workflow", 2200), cell("nonpay-notice", 2360)] }),
      new TableRow({ children: [cell("renewal_approaching", 2600, LIGHT_BG), cell("90/60/30 day scan", 2200, LIGHT_BG), cell("Renewal workflow", 2200, LIGHT_BG), cell("renewal-[high/low]", 2360, LIGHT_BG)] }),
      new TableRow({ children: [cell("welcome_email_sent", 2600), cell("Welcome email sent", 2200), cell("Onboarding drip", 2200), cell("new-customer", 2360)] }),
      new TableRow({ children: [cell("quote_sent", 2600, LIGHT_BG), cell("Quote email sent", 2200, LIGHT_BG), cell("Follow-up workflow", 2200, LIGHT_BG), cell("quoted-[carrier]", 2360, LIGHT_BG)] }),
      new TableRow({ children: [cell("quote_not_converted_3d", 2600), cell("3 days, no sale", 2200), cell("Follow-up sequence", 2200), cell("followup-3day", 2360)] }),
      new TableRow({ children: [cell("quote_stale_90d", 2600, LIGHT_BG), cell("90 days, no sale", 2200, LIGHT_BG), cell("Remarket campaign", 2200, LIGHT_BG), cell("remarket-pipeline", 2360, LIGHT_BG)] }),
      new TableRow({ children: [cell("life_cross_sell", 2600), cell("Audience query", 2200), cell("Life campaign", 2200), cell("life-cross-sell", 2360)] }),
    ],
  }),
  spacer(60),

  subSubTitle("GHL to BCI CRM (Inbound Webhooks / Callbacks)"),
  new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [2600, 2200, 4560],
    rows: [
      new TableRow({ children: [headerCell("Event", 2600), headerCell("GHL Trigger", 2200), headerCell("BCI CRM Action", 4560)] }),
      new TableRow({ children: [cell("call_completed", 2600), cell("AI call ends", 2200), cell("Add NowCerts note with call result, update non-pay/quote status", 4560)] }),
      new TableRow({ children: [cell("appointment_booked", 2600, LIGHT_BG), cell("Calendar booking", 2200, LIGHT_BG), cell("Create task in NowCerts, notify producer", 4560, LIGHT_BG)] }),
      new TableRow({ children: [cell("contact_opted_out", 2600), cell("DNC/unsubscribe", 2200), cell("Update customer preferences, stop all sequences", 4560)] }),
      new TableRow({ children: [cell("sms_reply", 2600, LIGHT_BG), cell("Customer texts back", 2200, LIGHT_BG), cell("Log in NowCerts, alert service team", 4560, LIGHT_BG)] }),
    ],
  }),
  spacer(60),

  subSubTitle("Webhook Security"),
  bulletItem("All webhooks use HTTPS"),
  bulletItem("BCI CRM outbound webhooks include a shared secret header: X-BCI-Webhook-Secret"),
  bulletItem("GHL callback webhooks verified by checking GHL signature"),
  bulletItem("Rate limited: max 10 webhook fires per second"),

  new Paragraph({ children: [new PageBreak()] }),
);

// ═══════════════════════════════════════════════════════════════
// 7. IMPLEMENTATION TIMELINE
// ═══════════════════════════════════════════════════════════════
children.push(
  sectionTitle("7. Implementation Timeline"),
  bodyText("Recommended build order based on impact and dependency chain."),
  divider(),
  spacer(60),

  new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [1200, 3500, 2400, 2260],
    rows: [
      new TableRow({ children: [headerCell("Phase", 1200), headerCell("What", 3500), headerCell("BCI CRM Work", 2400), headerCell("GHL Work", 2260)] }),
      new TableRow({ children: [cell("Phase 1", 1200), cell("Non-Pay AI Calling", 3500), cell("Webhook + NowCerts logging", 2400), cell("Voice AI agent + workflow", 2260)] }),
      new TableRow({ children: [cell("Phase 2", 1200, LIGHT_BG), cell("Onboarding Campaign", 3500, LIGHT_BG), cell("Email sequence engine", 2400, LIGHT_BG), cell("SMS touchpoints", 2260, LIGHT_BG)] }),
      new TableRow({ children: [cell("Phase 3", 1200), cell("Renewal Workflows", 3500), cell("Renewal scanner + de-dupe", 2400), cell("Rate-branched workflow", 2260)] }),
      new TableRow({ children: [cell("Phase 4", 1200, LIGHT_BG), cell("Quote-to-Close Pipeline", 3500, LIGHT_BG), cell("Quote UI + PDF + emails", 2400, LIGHT_BG), cell("Follow-up + remarket", 2260, LIGHT_BG)] }),
      new TableRow({ children: [cell("Phase 5", 1200), cell("Life Insurance Cross-Sell", 3500), cell("Audience query engine", 2400), cell("Campaign workflow", 2260)] }),
    ],
  }),
  spacer(60),

  bodyText("Phase 1 can start immediately - I just need your GHL Inbound Webhook URL to wire up the non-pay integration."),
  spacer(60),

  subTitle("What You Need to Do in GHL"),
  bulletItem("Enable Voice AI and register for outbound calling approval"),
  bulletItem("Create the custom contact fields listed in Section 1"),
  bulletItem("Create a Voice AI agent for each use case (prompts provided above)"),
  bulletItem("Build workflows following the step-by-step guides above"),
  bulletItem("Provide Inbound Webhook URLs back to me for each workflow"),
  bulletItem("Add your office phone number for call transfers"),
  spacer(60),

  subTitle("What I Build on BCI CRM"),
  bulletItem("GHL webhook integration layer (fire events on key actions)"),
  bulletItem("Renewal detection engine (daily NowCerts scan)"),
  bulletItem("Multi-policy de-duplication logic"),
  bulletItem("Quote entry UI with drag-and-drop PDF upload"),
  bulletItem("Carrier-specific quote email templates"),
  bulletItem("NowCerts prospect creation on quote entry"),
  bulletItem("Quote conversion tracking (3-day, 7-day, 14-day, 90-day checks)"),
  bulletItem("Cross-sell audience identification query"),
  bulletItem("Onboarding email sequence engine"),
  bulletItem("Pre-renewal email sequence engine"),
  bulletItem("Callback endpoint for GHL to report call results back"),
  bulletItem("NowCerts note creation for all touchpoints"),
);

// ═══════════════════════════════════════════════════════════════
// BUILD DOCUMENT
// ═══════════════════════════════════════════════════════════════
const doc = new Document({
  numbering: {
    config: [
      {
        reference: "bullets",
        levels: [
          { level: 0, format: LevelFormat.BULLET, text: "\u2022", alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 720, hanging: 360 } } } },
          { level: 1, format: LevelFormat.BULLET, text: "\u25E6", alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 1440, hanging: 360 } } } },
        ],
      },
    ],
  },
  styles: {
    default: { document: { run: { font: "Arial", size: 22 } } },
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
      },
    },
    children,
  }],
});

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync("/home/claude/BCI_Automation_Blueprint.docx", buffer);
  console.log("Document created successfully");
});
