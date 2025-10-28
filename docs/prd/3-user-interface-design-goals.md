# 3. User Interface Design Goals

## 3.1 Overall UX Vision

The primary user interface is **conversational via WhatsApp**, where customers experience a warm, friendly AI assistant ("Maite") that feels human-like and helpful. The interaction should feel natural, not robotic—more like texting with a knowledgeable friend at the salon than interacting with a machine.

For the **admin interface**, the vision is functional simplicity: salon staff need a straightforward dashboard to manage business data (services, packs, pricing, policies, holiday closures) without technical complexity. No fancy UI animations needed—focus is on efficiency and clarity.

## 3.2 Key Interaction Paradigms

**For Customers (via WhatsApp):**
- **Conversational AI with Personality:** Warm greetings, emoji usage, natural language understanding
- **Progressive Disclosure:** System asks clarifying questions one at a time, never overwhelming with forms
- **Multi-Option Selection:** When presenting availability, always offer 2+ choices to empower customer decision-making
- **Confirmation Feedback:** Clear confirmation messages with booking details after successful payment
- **Proactive Assistance:** Bot suggests better deals (packs), offers consultation when customer is indecisive

**For Admin (Web Interface):**
- **Simple CRUD Operations:** Standard create/read/update/delete for services, packs, stylists, policies
- **Calendar Visibility:** View upcoming bookings per stylist without leaving admin panel
- **Minimal Clicks:** Common operations (add service, block holiday) should require ≤3 clicks

## 3.3 Core Screens and Views

**Customer-Facing (WhatsApp):**
1. Initial Greeting & Name Confirmation (new customers only)
2. Service Selection & Price Display (conversational, not form-based)
3. Availability Options Presentation (2+ time slot choices with professional names)
4. Payment Link Message (with clear anticipo amount and policy notice)
5. Booking Confirmation (with full details: date, time, professional, service, duration)
6. Automated Reminder (48h before appointment)
7. Escalation Handoff Message (when transferring to human team)

**Admin Interface (Web):**
1. Dashboard Home: Overview of today's bookings, system status, recent escalations
2. Services Management: List/add/edit/delete services (name, category, duration, price, anticipo required)
3. Packs Management: List/add/edit/delete service packages
4. Stylists Management: List/add/edit stylists (name, category: Hairdressing/Aesthetics, Google Calendar ID)
5. Policies Configuration: Edit cancellation policy, payment percentage, timeout values
6. Calendar View: Read-only view of upcoming bookings per stylist (next 7 days)
7. Holiday/Closure Management: Block dates in all calendars for festivos

## 3.4 Accessibility

**WCAG AA Compliance** for admin web interface:
- Semantic HTML structure
- Keyboard navigation support
- Sufficient color contrast (text/background)
- Form labels and error messages
- Screen reader compatibility

**WhatsApp Interface:** Accessibility handled by WhatsApp client (out of scope)

## 3.5 Branding

**Conversational Tone (Maite persona):**
- Warm, friendly, professional Spanish language
- Emoji usage: 🌸 (signature), 💕😊🎉💇‍♀️💇‍♂️ (contextual)
- Addressing customers by first name
- Conversational phrases: "Encantada de saludarte", "¡Perfecto!", "¡Te esperamos!"

**Admin Interface:**
- Clean, minimal design (no specific branding requirements for MVP)
- Color scheme: Neutral/professional (white background, dark text, accent color for buttons)
- Logo: "Atrévete Peluquería" text header (no fancy logo needed for MVP)

## 3.6 Target Device and Platforms

**Customer-Facing:**
- **Mobile-first** (WhatsApp on iOS/Android smartphones)
- All devices supported by WhatsApp (mobile, web, desktop app)

**Admin Interface:**
- **Web Responsive** (desktop-primary, tablet-compatible)
- Modern browsers: Chrome, Firefox, Safari, Edge (last 2 versions)
- Minimum resolution: 1280x720 (laptop standard)
- Mobile-friendly but not optimized (staff will primarily use desktop/laptop)

---
