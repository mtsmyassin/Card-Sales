# UI Redesign — Sidebar Layout Design Doc

## Goal
Replace the current flat horizontal-tab layout with a fixed left sidebar and card-based content area. The result should feel serious and official, clean and fast, and branded to Farmacia Carimas.

## Layout

### Sidebar (fixed, left, 220px wide)
- Background: dark teal `#00697d`
- Top: Farmacia Carimas logo (centered, ~120px wide)
- Nav links below logo: Audit Entry, Calendar, Command Center, History, Users
  - Each link has a simple icon (emoji or SVG) + label
  - Active link: white background pill, dark teal text
  - Inactive: white text, teal hover highlight
- Bottom of sidebar: "User: admin" label + red Log Out button

### Main Content Area
- Background: `#f0f4f8` (light blue-gray)
- Left margin: 220px to clear the sidebar
- Padding: 30px

### Page Title
- Small breadcrumb at top of content: e.g. "Audit Entry" in dark teal, bold
- Replaces the old header bar entirely

### Section Cards
- Each form section (1. Store & Metadata, 2. Revenue, etc.) is a white card
- Border-radius: 12px
- Box shadow: `0 2px 8px rgba(0,0,0,0.08)`
- Section header inside card: teal numbered circle badge + bold uppercase label
- Margin between cards: 20px

### Input Fields
- Border: `1px solid #cbd5e1`
- Border-radius: 8px
- Focus: teal glow `box-shadow: 0 0 0 3px rgba(0,151,178,0.15)`, teal border
- Label text: small, bold, dark gray above each field

### Buttons
- Primary (Finalize & Upload): teal, rounded, auto-width centered — NOT full width stretched
- Secondary (Cancel, Auto 11.5%): gray outline style
- Danger (Log Out): red, pill shape in sidebar

## Colors
| Token | Value | Use |
|---|---|---|
| `--sidebar` | `#00697d` | Sidebar background |
| `--p` | `#0097b2` | Buttons, focus, accents |
| `--bg` | `#f0f4f8` | Page background |
| `--card` | `#ffffff` | Card background |
| `--txt` | `#1e293b` | Body text |
| `--muted` | `#64748b` | Labels, secondary text |

## Typography
- Font: `'Segoe UI', system-ui, sans-serif` (no change)
- Section badges: bold white number in teal circle
- Nav labels: 14px, font-weight 700
- Field labels: 12px, font-weight 700, uppercase, muted color

## What Does NOT Change
- All form fields, logic, API calls — untouched
- Section order and content
- All JavaScript behavior
- Mobile is not a priority for this version (pharmacy runs on desktop)
